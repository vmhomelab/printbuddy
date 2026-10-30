from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from backend.app.services.bambu_mqtt import FilaSwitchState, NozzleInfo, PrintOptions
from backend.app.services.printer_providers._http_common import (
    PolledLifecycleMixin,
    float_or_none,
    minutes_from_seconds,
)

logger = logging.getLogger(__name__)

OCTOPRINT_STORAGES = ("local", "sdcard")
# Permissions Printbuddy needs for status, job control and the File Manager.
OCTOPRINT_REQUIRED_PERMISSIONS = (
    "STATUS",
    "CONTROL",
    "PRINT",
    "FILES_LIST",
    "FILES_UPLOAD",
    "FILES_DOWNLOAD",
    "FILES_DELETE",
    "FILES_SELECT",
)


class OctoPrintAuthError(RuntimeError):
    """The API key is invalid or lacks permissions Printbuddy depends on."""

    def __init__(self, message: str, *, missing_permissions: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing_permissions = missing_permissions or []


@dataclass
class OctoPrintPrinterState:
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
    error_message: str | None = None


def _map_octoprint_flags(flags: dict[str, Any] | None) -> str:
    """Map OctoPrint ``state.flags`` to Printbuddy states.

    The flags are checked in priority order because OctoPrint sets several at
    once: while pausing ``printing`` and ``pausing`` are both true, and while
    cancelling ``printing`` and ``cancelling`` are both true. The textual
    ``state.text`` is not used because plugins and versions vary it.
    """
    if not isinstance(flags, dict):
        return "unknown"
    if flags.get("error") or (flags.get("closedOrError") and not flags.get("operational")):
        return "FAILED" if flags.get("error") else "OFFLINE"
    if flags.get("cancelling"):
        return "RUNNING"
    if flags.get("paused") or flags.get("pausing"):
        return "PAUSE"
    if flags.get("printing") or flags.get("resuming") or flags.get("finishing"):
        return "RUNNING"
    if flags.get("operational"):
        return "IDLE"
    return "OFFLINE"


def _octoprint_progress(value: Any) -> float:
    """OctoPrint reports ``progress.completion`` as 0-100 already (or null)."""
    progress = float_or_none(value)
    if progress is None:
        return 0.0
    return max(0.0, min(progress, 100.0))


def _temperature(entry: Any, key: str) -> float:
    if not isinstance(entry, dict):
        return 0.0
    return float_or_none(entry.get(key)) or 0.0


def _job_file_metadata(job: dict[str, Any]) -> dict[str, Any]:
    """Normalize OctoPrint's G-code analysis to Printbuddy's file metadata keys."""
    metadata: dict[str, Any] = {}
    estimated = float_or_none(job.get("estimatedPrintTime"))
    if estimated is not None:
        metadata["print_time_seconds"] = int(estimated)

    filament = job.get("filament") if isinstance(job.get("filament"), dict) else {}
    total_mm = 0.0
    total_cm3 = 0.0
    for tool, usage in filament.items():
        if not str(tool).startswith("tool") or not isinstance(usage, dict):
            continue
        total_mm += float_or_none(usage.get("length")) or 0.0
        total_cm3 += float_or_none(usage.get("volume")) or 0.0
    if total_mm > 0:
        metadata["filament_used_mm"] = round(total_mm, 2)
    if total_cm3 > 0:
        metadata["filament_used_cm3"] = round(total_cm3, 3)

    if metadata:
        metadata["source"] = "octoprint_gcode_analysis"
    return metadata


def _flatten_files(entries: Any) -> list[dict[str, Any]]:
    """Map one level of an OctoPrint files listing to Printbuddy's entry shape."""
    files: list[dict[str, Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("display") or entry.get("name") or "").strip()
        path = str(entry.get("path") or entry.get("name") or "").strip("/")
        if not name or not path:
            continue
        is_directory = entry.get("type") == "folder"
        item: dict[str, Any] = {
            "name": name,
            "type": "directory" if is_directory else "file",
            "size": entry.get("size"),
            "modified": entry.get("date"),
            "path": f"/{path}",
        }
        analysis = entry.get("gcodeAnalysis")
        if not is_directory and isinstance(analysis, dict):
            estimated = float_or_none(analysis.get("estimatedPrintTime"))
            if estimated is not None:
                item["print_time_seconds"] = int(estimated)
        files.append(item)
    return files


class OctoPrintPrinterClient(PolledLifecycleMixin):
    """Printer provider backed by the OctoPrint REST API.

    Printbuddy stores the OctoPrint API key in ``auth_token``. OctoPrint itself
    talks to a Marlin/RepRap printer over serial, so "OctoPrint reachable" and
    "printer connected" are separate: when OctoPrint has no serial connection
    ``/api/printer`` answers 409 and the printer is reported as OFFLINE.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 5.0,
        on_state_change: Any | None = None,
        on_print_start: Any | None = None,
        on_print_complete: Any | None = None,
        on_bed_temp_update: Any | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("OctoPrint base URL is required")
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout = timeout
        self.state = OctoPrintPrinterState()
        self.on_state_change = on_state_change
        self.on_print_start = on_print_start
        self.on_print_complete = on_print_complete
        self.on_bed_temp_update = on_bed_temp_update
        self._last_state: str | None = None
        self._has_status_sample = False
        self._last_bed_temp: float | None = None
        self._current_print_started_at: float | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        kwargs.setdefault("timeout", self.timeout)
        return httpx.request(method.upper(), self._url(path), headers=self._headers, **kwargs)

    def _get(self, path: str) -> dict[str, Any]:
        response = self._request("get", path)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"value": data}

    def _command(self, path: str, payload: dict[str, Any]) -> bool:
        response = self._request("post", path, json=payload)
        if response.status_code == 409:
            # OctoPrint answers 409 when the printer state does not allow the
            # command (not operational, no active job, already printing ...).
            logger.warning("OctoPrint rejected %s %s: %s", path, payload.get("command"), response.text[:200])
            return False
        response.raise_for_status()
        return True

    @staticmethod
    def _storage(storage: str | None) -> str:
        value = (storage or "local").strip("/").lower()
        return value if value in OCTOPRINT_STORAGES else "local"

    def _file_api_path(self, remote_path: str, *, storage: str | None = None) -> str:
        normalized = remote_path.strip("/")
        storage_key = self._storage(storage)
        if normalized.startswith(f"{storage_key}/"):
            normalized = normalized[len(storage_key) + 1 :]
        base = f"api/files/{storage_key}"
        return f"{base}/{quote(normalized, safe='/')}" if normalized else base

    # -- authentication ---------------------------------------------------

    def verify_api_key(self) -> dict[str, Any]:
        """Check the API key belongs to a user with the permissions we need.

        An invalid key is not rejected outright by OctoPrint: requests are
        treated as anonymous, ``/api/currentuser`` answers 200 with
        ``name: null`` and most other endpoints answer 403.
        """
        user = self._get("api/currentuser")
        if not user.get("name"):
            raise OctoPrintAuthError("OctoPrint did not accept the API key")
        granted = {str(p) for p in user.get("permissions") or [] if isinstance(p, str)}
        if "ADMIN" in granted:
            return user
        missing = [p for p in OCTOPRINT_REQUIRED_PERMISSIONS if p not in granted]
        if missing:
            raise OctoPrintAuthError(
                f"OctoPrint user {user['name']!r} is missing permissions: {', '.join(missing)}",
                missing_permissions=missing,
            )
        return user

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        version = self._get("api/version")
        if not str(version.get("text") or "").startswith("OctoPrint"):
            raise RuntimeError("Endpoint did not identify as OctoPrint")
        self.state.firmware_version = str(version.get("server") or "") or None
        self.state.raw_data = {"version": version}
        self.state.connected = True
        self.request_status_update()

    def disconnect(self, timeout: float = 0) -> None:  # noqa: ARG002 - kept for provider compatibility
        self.state.connected = False

    def check_staleness(self) -> bool:
        try:
            self.request_status_update()
        except Exception:
            self.state.connected = False
        return self.state.connected

    def _completion_status(self, current_state: str) -> str:
        # OctoPrint has no FINISH state: a finished job drops back to
        # operational with completion 100, a cancelled one with completion
        # null (mapped to 0).
        if current_state == "OFFLINE":
            return "failed"
        return super()._completion_status(current_state)

    def request_status_update(self) -> bool:
        previous_state = self._last_state if self._has_status_sample else None

        response = self._request("get", "api/printer", params={"exclude": "sd"})
        if response.status_code == 409:
            printer: dict[str, Any] = {}
            self.state.state = "OFFLINE"
            self.state.temperatures = {}
        else:
            response.raise_for_status()
            printer = response.json() if response.content else {}
            state = printer.get("state") if isinstance(printer.get("state"), dict) else {}
            self.state.state = _map_octoprint_flags(state.get("flags"))
            self.state.error_message = str(state.get("error") or "") or None
            self._apply_temperatures(printer.get("temperature"))

        job = self._get("api/job")
        self._apply_job(job)

        # OctoPrint itself answered, so the provider connection is healthy even
        # when OctoPrint has no serial connection to the printer.
        self.state.connected = self.state.state != "OFFLINE"
        self.state.raw_status = {"printer": printer, "job": job}
        self.state.raw_data = {**self.state.raw_data, "printer": printer, "job": job}

        self._emit_status_callbacks(previous_state)
        self._last_state = self.state.state
        self._has_status_sample = True
        return True

    def _apply_temperatures(self, temperature: Any) -> None:
        temperature = temperature if isinstance(temperature, dict) else {}
        tool0 = temperature.get("tool0")
        bed = temperature.get("bed")
        temps: dict[str, Any] = {
            "nozzle": _temperature(tool0, "actual"),
            "nozzle_target": _temperature(tool0, "target"),
            "bed": _temperature(bed, "actual"),
            "bed_target": _temperature(bed, "target"),
        }
        temps["nozzle_heating"] = temps["nozzle_target"] - temps["nozzle"] > 1.0
        temps["bed_heating"] = temps["bed_target"] - temps["bed"] > 1.0
        chamber = temperature.get("chamber")
        if isinstance(chamber, dict) and chamber.get("actual") is not None:
            temps["chamber"] = _temperature(chamber, "actual")
            temps["chamber_target"] = _temperature(chamber, "target")
        self.state.temperatures = temps

    def _apply_job(self, data: dict[str, Any]) -> None:
        job = data.get("job") if isinstance(data.get("job"), dict) else {}
        progress = data.get("progress") if isinstance(data.get("progress"), dict) else {}
        file_info = job.get("file") if isinstance(job.get("file"), dict) else {}

        filename = file_info.get("display") or file_info.get("name")
        self.state.gcode_file = str(file_info.get("path") or filename) if filename else None
        self.state.subtask_name = str(filename) if filename else None
        self.state.current_print = self.state.subtask_name

        self.state.progress = _octoprint_progress(progress.get("completion"))
        time_left = float_or_none(progress.get("printTimeLeft"))
        if time_left is None and self.state.state in {"RUNNING", "PAUSE"}:
            # printTimeLeft is null until OctoPrint has a stable estimate.
            estimated = float_or_none(job.get("estimatedPrintTime"))
            elapsed = float_or_none(progress.get("printTime")) or 0.0
            if estimated is not None:
                time_left = max(estimated - elapsed, 0.0)
        self.state.remaining_time = minutes_from_seconds(time_left)

        file_metadata = _job_file_metadata(job)
        if file_metadata:
            self.state.raw_data = {**self.state.raw_data, "file_metadata": file_metadata}
        elif isinstance(self.state.raw_data, dict):
            self.state.raw_data.pop("file_metadata", None)

    # -- job control ------------------------------------------------------

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        return self._command(
            self._file_api_path(filename, storage=kwargs.get("storage")), {"command": "select", "print": True}
        )

    def stop_print(self) -> bool:
        return self._command("api/job", {"command": "cancel"})

    def pause_print(self) -> bool:
        return self._command("api/job", {"command": "pause", "action": "pause"})

    def resume_print(self) -> bool:
        return self._command("api/job", {"command": "pause", "action": "resume"})

    def send_gcode(self, script: str) -> bool:
        commands = [line.strip() for line in script.splitlines() if line.strip()]
        if not commands:
            return False
        return self._command("api/printer/command", {"commands": commands})

    def home_axes(self, axes: list[str] | None = None) -> bool:
        return self._command("api/printer/printhead", {"command": "home", "axes": axes or ["x", "y", "z"]})

    def set_fan_speed(self, fan: str, speed: int) -> bool:
        # Plain Marlin/RepRap firmware only exposes the part cooling fan via M106.
        if fan not in {"part", "model", "model_fan", "cooling"}:
            raise ValueError("OctoPrint printers only support the part cooling fan")
        pwm = round(max(0, min(int(speed), 100)) * 255 / 100)
        return self.send_gcode(f"M106 S{pwm}" if pwm else "M107")

    def set_nozzle_temperature(self, target: int | float) -> bool:
        return self._command("api/printer/tool", {"command": "target", "targets": {"tool0": int(target)}})

    def set_bed_temperature(self, target: int | float) -> bool:
        return self._command("api/printer/bed", {"command": "target", "target": int(target)})

    # -- files ------------------------------------------------------------

    def list_files(self, path: str = "/", *, storage: str | None = None) -> list[dict[str, Any]]:
        data = self._get(self._file_api_path(path, storage=storage))
        # The storage root returns {"files": [...]}, a folder returns its own
        # entry with "children".
        return _flatten_files(data.get("files") if "files" in data else data.get("children"))

    def upload_file(
        self, local_path: Path, remote_path: str, *, overwrite: bool = False, storage: str | None = None
    ) -> bool:  # noqa: ARG002 - OctoPrint overwrites existing files
        normalized = remote_path.strip("/") or local_path.name
        folder, _, filename = normalized.rpartition("/")
        data = {"path": folder} if folder else {}
        with open(local_path, "rb") as fh:
            response = self._request(
                "post",
                self._file_api_path("", storage=storage),
                files={"file": (filename or local_path.name, fh, "application/octet-stream")},
                data=data,
                timeout=max(self.timeout, 120.0),
            )
        response.raise_for_status()
        return True

    def download_file(self, remote_path: str, *, storage: str | None = None) -> bytes | None:
        normalized = remote_path.strip("/")
        response = self._request(
            "get",
            f"downloads/files/{self._storage(storage)}/{quote(normalized, safe='/')}",
            timeout=max(self.timeout, 60.0),
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    def delete_file(self, remote_path: str, *, storage: str | None = None) -> bool:
        response = self._request("delete", self._file_api_path(remote_path, storage=storage))
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True


def create_octoprint_client(printer: Any, **callbacks: Any) -> OctoPrintPrinterClient:
    base_url = getattr(printer, "api_url", None) or f"http://{printer.ip_address}:5000"
    return OctoPrintPrinterClient(
        base_url=base_url,
        api_key=getattr(printer, "auth_token", None),
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
