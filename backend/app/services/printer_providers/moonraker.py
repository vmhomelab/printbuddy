from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx

from backend.app.services.bambu_mqtt import FilaSwitchState, NozzleInfo, PrintOptions


@dataclass
class MoonrakerPrinterState:
    connected: bool = False
    state: str = "unknown"
    current_print: str | None = None
    subtask_name: str | None = None
    progress: float = 0.0
    remaining_time: int = 0
    layer_num: int = 0
    total_layers: int = 0
    temperatures: dict[str, Any] = field(default_factory=dict)
    raw_status: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)
    gcode_file: str | None = None
    subtask_id: str | None = None
    hms_errors: list[Any] = field(default_factory=list)
    kprofiles: list[Any] = field(default_factory=list)
    sdcard: bool = False
    store_to_sdcard: bool = False
    timelapse: bool = False
    ipcam: bool = False
    wifi_signal: int | None = None
    wired_network: bool = False
    door_open: bool = False
    nozzles: list[Any] = field(default_factory=lambda: [NozzleInfo(), NozzleInfo()])
    nozzle_rack: list[dict[str, Any]] = field(default_factory=list)
    print_options: PrintOptions = field(default_factory=PrintOptions)
    stg_cur: int = -1
    stg: list[int] = field(default_factory=list)
    airduct_mode: int = 0
    speed_level: int = 2
    chamber_light: bool = False
    active_extruder: int = 0
    tray_now: int = 255
    ams_status_main: int = 0
    ams_status_sub: int = 0
    mc_print_sub_stage: int = 0
    ams_extruder_map: dict[str, int] = field(default_factory=dict)
    fila_switch: FilaSwitchState = field(default_factory=FilaSwitchState)
    last_ams_update: float = 0.0
    printable_objects: dict[str, str] = field(default_factory=dict)
    cooling_fan_speed: int | None = None
    big_fan1_speed: int | None = None
    big_fan2_speed: int | None = None
    heatbreak_fan_speed: int | None = None
    firmware_version: str | None = None
    developer_mode: bool | None = None


def _map_moonraker_state(raw_state: Any) -> str:
    """Map Klipper/Moonraker print states onto Printbuddy's existing status names."""
    state = str(raw_state or "").lower()
    return {
        "printing": "RUNNING",
        "paused": "PAUSE",
        "complete": "FINISH",
        "cancelled": "FAILED",
        "error": "FAILED",
        "standby": "IDLE",
        "ready": "IDLE",
    }.get(state, str(raw_state or "unknown"))


def _heater_temperature(values: dict[str, Any]) -> float:
    return float(values.get("temperature") or 0.0) if isinstance(values, dict) else 0.0


def _heater_target(values: dict[str, Any]) -> float:
    return float(values.get("target") or 0.0) if isinstance(values, dict) else 0.0


def _is_heating(values: dict[str, Any]) -> bool:
    current = _heater_temperature(values)
    target = _heater_target(values)
    return target > 0 and target - current > 1.0


def _moonraker_temperatures(status: dict[str, Any]) -> dict[str, Any]:
    """Normalize Moonraker heater objects to the temperature keys used by the UI."""
    extruder = status.get("extruder", {}) if isinstance(status, dict) else {}
    bed = status.get("heater_bed", {}) if isinstance(status, dict) else {}
    temps: dict[str, Any] = {
        "nozzle": _heater_temperature(extruder),
        "nozzle_target": _heater_target(extruder),
        "nozzle_heating": _is_heating(extruder),
        "bed": _heater_temperature(bed),
        "bed_target": _heater_target(bed),
        "bed_heating": _is_heating(bed),
    }

    for name, values in status.items():
        if isinstance(values, dict) and ("temperature" in values or "target" in values):
            temps[name] = values
    return temps


def _moonraker_fan_percent(values: Any) -> int | None:
    """Convert Moonraker fan speed values to a 0-100 percentage."""
    if not isinstance(values, dict) or "speed" not in values:
        return None
    try:
        speed = float(values.get("speed") or 0.0)
    except (TypeError, ValueError):
        return None
    percent = speed * 100 if speed <= 1.0 else speed
    return max(0, min(100, round(percent)))


def _apply_moonraker_fans(state: MoonrakerPrinterState, status: dict[str, Any]) -> None:
    """Map reported Klipper/Moonraker fan objects onto Printbuddy fan badges.

    Moonraker object names are printer-config dependent. Keep unsupported fans as
    None so the frontend can hide missing capabilities, while preserving 0% for
    fans that exist but are currently off.
    """
    state.cooling_fan_speed = None
    state.big_fan1_speed = None
    state.big_fan2_speed = None
    state.heatbreak_fan_speed = None

    for name, values in status.items():
        percent = _moonraker_fan_percent(values)
        if percent is None:
            continue

        normalized = name.lower()
        if normalized == "fan":
            state.cooling_fan_speed = percent
        elif normalized.startswith("heater_fan "):
            fan_name = normalized.removeprefix("heater_fan ")
            if state.heatbreak_fan_speed is None or any(
                marker in fan_name for marker in ("hotend", "heatbreak", "extruder", "nozzle")
            ):
                state.heatbreak_fan_speed = percent
        elif normalized.startswith("fan_generic "):
            fan_name = normalized.removeprefix("fan_generic ")
            if any(marker in fan_name for marker in ("chamber", "exhaust", "filter", "enclosure")):
                state.big_fan2_speed = percent
            elif any(marker in fan_name for marker in ("aux", "auxiliary", "side", "boost")):
                state.big_fan1_speed = percent


def _remaining_minutes(print_stats: dict[str, Any], progress: float) -> int:
    """Estimate remaining print time from Moonraker print duration and progress."""
    print_duration = float(print_stats.get("print_duration") or 0.0)
    if progress <= 0 or print_duration <= 0:
        return 0
    total_seconds = print_duration / min(progress / 100.0, 1.0)
    remaining_seconds = max(total_seconds - print_duration, 0.0)
    return int(remaining_seconds // 60)


def _moonraker_url_candidates(base_url: str) -> list[str]:
    """Return Moonraker probe URLs, including :7125 fallback for Fluidd UI URLs."""
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        return [base_url.rstrip("/") + "/"]

    primary = base_url.rstrip("/") + "/"
    candidates = [primary]

    # Users often paste the Fluidd/Mainsail UI URL (http://printer/) instead
    # of the Moonraker API URL. Fluidd talks to Moonraker on 7125, so try that
    # as a second candidate when the supplied URL is not already explicit 7125.
    # Some Elegoo/Fluidd images do the inverse: port 7125 is not reachable from
    # the add-on/container network, but the UI host proxies Moonraker at :80.
    # Therefore an explicit :7125 URL also gets a no-port fallback.
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    if parsed.port != 7125:
        fallback = urlunparse((parsed.scheme or "http", f"{host}:7125", "", "", "", "")).rstrip("/") + "/"
        if fallback not in candidates:
            candidates.append(fallback)
    else:
        fallback = urlunparse((parsed.scheme or "http", host, "", "", "", "")).rstrip("/") + "/"
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


class MoonrakerPrinterClient:
    """Minimal Klipper/Mainsail provider backed by Moonraker.

    Mainsail is a UI; the printer control API is normally Moonraker. This first
    scaffold validates connectivity and exposes a state shape that can be mapped
    into the existing status pipeline in follow-up work. Bambu-specific commands
    intentionally return False instead of pretending to be supported.
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        timeout: float = 5.0,
        printer_model: str | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("Moonraker base URL is required for Klipper/Mainsail printers")
        self.base_url = base_url.rstrip("/") + "/"
        self.base_url_candidates = _moonraker_url_candidates(base_url)
        self.auth_token = auth_token
        self.timeout = timeout
        self.printer_model = printer_model or ""
        self._gcodes_path_prefixes: list[str] | None = None
        self.state = MoonrakerPrinterState()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}

    def _get(self, path: str, *, base_url: str | None = None) -> dict[str, Any]:
        response = httpx.get(
            urljoin(base_url or self.base_url, path.lstrip("/")), headers=self._headers, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            return data["result"]
        return data if isinstance(data, dict) else {"value": data}

    def _query_objects(self, object_names: list[str]) -> dict[str, Any]:
        query = "printer/objects/query?" + "&".join(quote(name, safe="") for name in object_names)
        objects = self._get(query)
        return objects.get("status", objects) if isinstance(objects, dict) else {}

    def _is_elegoo_printer(self) -> bool:
        return "elegoo" in self.printer_model.lower()

    def _configured_gcodes_path_prefixes(self) -> list[str]:
        """Return absolute Klipper gcode storage paths for Elegoo/Moonraker aliases.

        Elegoo firmware variants commonly use either ``~/gcode_files``
        (``/home/mks/gcode_files``) or the newer Moonraker default
        ``~/printer_data/gcodes``. Query Klipper's virtual_sdcard config when
        available, then fall back to both known MKS paths so paths captured by
        old jobs or UIs still resolve.
        """
        if self._gcodes_path_prefixes is not None:
            return self._gcodes_path_prefixes

        prefixes: list[str] = []
        try:
            config = self._query_objects(["configfile"]).get("configfile", {})
            settings = config.get("settings", {}) if isinstance(config, dict) else {}
            virtual_sdcard = settings.get("virtual_sdcard", {}) if isinstance(settings, dict) else {}
            raw_path = str(virtual_sdcard.get("path") or "").strip()
            if raw_path:
                if raw_path == "~":
                    raw_path = "/home/mks"
                elif raw_path.startswith("~/"):
                    raw_path = f"/home/mks/{raw_path[2:]}"
                prefixes.append(raw_path.rstrip("/"))
        except Exception:  # noqa: BLE001 - path aliasing must not break file operations
            pass

        for fallback in ("/home/mks/gcode_files", "/home/mks/printer_data/gcodes"):
            if fallback not in prefixes:
                prefixes.append(fallback)
        self._gcodes_path_prefixes = prefixes
        return prefixes

    def _normalize_gcodes_path(self, remote_path: str) -> str:
        """Normalize user/provider paths into Moonraker's gcodes root."""
        normalized = remote_path.strip()
        if self._is_elegoo_printer():
            # Bambu-style paths can leak into generic queue/file flows. On Elegoo
            # machines, /model means the Klipper virtual_sdcard gcode directory.
            if normalized == "/model" or normalized == "model":
                return ""
            if normalized.startswith("/model/"):
                normalized = normalized[len("/model/") :]
            elif normalized.startswith("model/"):
                normalized = normalized[len("model/") :]

            for prefix in self._configured_gcodes_path_prefixes():
                if normalized == prefix:
                    return ""
                if normalized.startswith(f"{prefix}/"):
                    normalized = normalized[len(prefix) + 1 :]
                    break

        normalized = normalized.strip("/")
        if normalized.startswith("gcodes/"):
            normalized = normalized[len("gcodes/") :]
        return normalized

    def _available_fan_objects(self) -> list[str]:
        objects = self._get("printer/objects/list")
        available = objects.get("objects", []) if isinstance(objects, dict) else []
        fan_objects = [
            str(name)
            for name in available
            if isinstance(name, str)
            and (name == "fan" or name.startswith("fan_generic ") or name.startswith("heater_fan "))
        ]
        return fan_objects

    def _query_fan_status(self) -> dict[str, Any]:
        try:
            fan_objects = self._available_fan_objects()
            if not fan_objects:
                return {}
            return self._query_objects(fan_objects)
        except Exception:  # noqa: BLE001 - fans are optional; keep core status healthy if discovery fails
            return {}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            urljoin(self.base_url, path.lstrip("/")), json=payload, headers=self._headers, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            return data["result"]
        return data if isinstance(data, dict) else {"value": data}

    def list_files(self, path: str = "/") -> list[dict[str, Any]]:
        root = "gcodes"
        normalized = self._normalize_gcodes_path(path)
        query = f"server/files/list?root={root}"
        if normalized:
            query += f"&path={normalized}"
        result = self._get(query)
        entries = result.get("result", result) if isinstance(result, dict) else result
        if isinstance(entries, dict):
            entries = entries.get("files") or entries.get("children") or []
        files: list[dict[str, Any]] = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            raw_path = str(entry.get("path") or entry.get("filename") or entry.get("name") or "").lstrip("/")
            if not raw_path:
                continue
            name = raw_path.rsplit("/", 1)[-1]
            modified_raw = entry.get("modified")
            modified = None
            if isinstance(modified_raw, int | float):
                modified = datetime.fromtimestamp(float(modified_raw), tz=timezone.utc).isoformat()
            elif modified_raw is not None:
                modified = str(modified_raw)
            file_type = "directory" if entry.get("type") == "directory" or entry.get("dirname") else "file"
            full_path = f"/{raw_path}" if not normalized else f"/{raw_path}"
            files.append(
                {"name": name, "type": file_type, "size": entry.get("size"), "modified": modified, "path": full_path}
            )
        return files

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        target = self._normalize_gcodes_path(remote_path) or local_path.name
        with open(local_path, "rb") as fh:
            response = httpx.post(
                urljoin(self.base_url, "server/files/upload"),
                data={"root": "gcodes", "path": target.rsplit("/", 1)[0] if "/" in target else ""},
                files={"file": (target.rsplit("/", 1)[-1], fh, "application/octet-stream")},
                headers=self._headers,
                timeout=max(self.timeout, 60.0),
            )
        response.raise_for_status()
        return True

    def connect(self) -> None:
        last_exc: Exception | None = None
        for candidate in self.base_url_candidates:
            try:
                info = self._get("server/info", base_url=candidate)
                self.base_url = candidate
                break
            except Exception as exc:  # noqa: BLE001 - retry with fallback candidate, then re-raise final cause
                last_exc = exc
        else:
            assert last_exc is not None
            raise last_exc
        self.state.connected = True
        self.state.state = _map_moonraker_state(info.get("klippy_state") or info.get("state") or "connected")
        self.state.raw_status = info
        self.state.raw_data = info
        try:
            self.request_status_update()
        except Exception:
            # ``server/info`` proved Moonraker is reachable. A transient object
            # query failure should not make the saved printer appear offline;
            # the next status poll will retry and update the details.
            self.state.connected = True

    def disconnect(self, timeout: float = 0) -> None:  # noqa: ARG002 - kept for Bambu client compatibility
        self.state.connected = False

    def check_staleness(self) -> bool:
        try:
            self.request_status_update()
        except Exception:
            self.state.connected = False
        return self.state.connected

    def request_status_update(self) -> bool:
        status = self._query_objects(
            ["webhooks", "print_stats", "virtual_sdcard", "display_status", "extruder", "heater_bed"]
        )
        fan_status = self._query_fan_status()
        if fan_status:
            status.update(fan_status)
        self.state.connected = True
        self.state.raw_status = status
        self.state.raw_data = status

        print_stats = status.get("print_stats", {}) if isinstance(status, dict) else {}
        virtual_sdcard = status.get("virtual_sdcard", {}) if isinstance(status, dict) else {}
        display_status = status.get("display_status", {}) if isinstance(status, dict) else {}

        raw_state = print_stats.get("state") or self.state.state
        self.state.state = _map_moonraker_state(raw_state)
        self.state.gcode_file = print_stats.get("filename") or virtual_sdcard.get("file_path") or None
        self.state.current_print = self.state.gcode_file
        self.state.subtask_name = self.state.gcode_file

        progress = virtual_sdcard.get("progress")
        if progress is None:
            progress = display_status.get("progress")
        self.state.progress = float(progress or 0.0) * 100
        self.state.remaining_time = _remaining_minutes(print_stats, self.state.progress)
        self.state.temperatures = _moonraker_temperatures(status)
        _apply_moonraker_fans(self.state, status)
        return True

    def download_file(self, remote_path: str) -> bytes | None:
        normalized = self._normalize_gcodes_path(remote_path)
        response = httpx.get(
            urljoin(self.base_url, f"server/files/gcodes/{normalized}"),
            headers=self._headers,
            timeout=max(self.timeout, 60.0),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    def delete_file(self, remote_path: str) -> bool:
        normalized = self._normalize_gcodes_path(remote_path)
        self._post("server/files/delete_file", {"path": f"gcodes/{normalized}"})
        return True

    def send_gcode(self, script: str) -> bool:
        if not script.strip():
            return False
        self._post("printer/gcode/script", {"script": script})
        return True

    def set_nozzle_temperature(self, target: int | float) -> bool:
        return self.send_gcode(f"M104 S{int(target)}")

    def set_bed_temperature(self, target: int | float) -> bool:
        return self.send_gcode(f"M140 S{int(target)}")

    def home_axes(self, axes: list[str] | None = None) -> bool:
        script = ("G28 " + " ".join(a.upper() for a in axes)) if axes else "G28"
        return self.send_gcode(script)

    def extrude(self, length: float, speed: int = 300) -> bool:
        return self.send_gcode(f"M83\nG1 E{length:.2f} F{speed}\nM82")

    def adjust_z_offset(self, amount: float) -> bool:
        return self.send_gcode(f"SET_GCODE_OFFSET Z_ADJUST={amount} MOVE=1")

    def save_config(self) -> bool:
        return self.send_gcode("SAVE_CONFIG")

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        normalized = self._normalize_gcodes_path(filename)
        try:
            self._post("printer/print/start", {"filename": normalized})
        except httpx.ReadTimeout:
            # Some Moonraker/Elegoo stacks accept the start command and begin
            # printing, but do not return headers before the short control
            # timeout expires. Verify printer state before surfacing a false
            # background-dispatch failure.
            try:
                self.request_status_update()
            except Exception:
                raise
            current = self.state.current_print or self.state.gcode_file or ""
            if self.state.state == "RUNNING" or current.endswith(normalized):
                return True
            raise
        return True

    def stop_print(self) -> bool:
        self._post("printer/print/cancel", {})
        return True


def create_moonraker_client(printer: Any, **callbacks: Any) -> MoonrakerPrinterClient:  # noqa: ARG001
    base_url = printer.api_url or f"http://{printer.ip_address}:7125"
    return MoonrakerPrinterClient(
        base_url=base_url,
        auth_token=getattr(printer, "auth_token", None),
        printer_model=getattr(printer, "model", None),
    )
