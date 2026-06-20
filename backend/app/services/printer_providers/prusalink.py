from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from backend.app.services.bambu_mqtt import FilaSwitchState, NozzleInfo, PrintOptions

logger = logging.getLogger(__name__)


@dataclass
class PrusaLinkPrinterState:
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


def _map_prusalink_state(raw_state: Any) -> str:
    state = str(raw_state or "").upper()
    return {
        "PRINTING": "RUNNING",
        "BUSY": "RUNNING",
        "PAUSED": "PAUSE",
        "FINISHED": "FINISH",
        "STOPPED": "FAILED",
        "ERROR": "FAILED",
        "ATTENTION": "FAILED",
        "IDLE": "IDLE",
        "READY": "IDLE",
    }.get(state, state or "unknown")


def _minutes_from_seconds(value: Any) -> int:
    try:
        return int(max(float(value or 0), 0) // 60)
    except (TypeError, ValueError):
        return 0


def _progress_percent(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _prusalink_basic_auth(username: str | None, password: str | None) -> httpx.BasicAuth | None:
    if not password:
        return None
    return httpx.BasicAuth(username or "maker", password)


def _prusalink_digest_auth(username: str | None, password: str | None) -> httpx.DigestAuth | None:
    if not password:
        return None
    return httpx.DigestAuth(username or "maker", password)


class PrusaLinkPrinterClient:
    """Prusa printer provider backed by the PrusaLink HTTP API.

    Printbuddy stores the PrusaLink password / API key in ``auth_token`` and an
    optional username in ``provider_options`` as JSON, defaulting to the common
    PrusaLink username ``maker``. Requests use Basic auth plus ``X-Api-Key`` for
    mock/API-key compatible endpoints, and retry with Digest auth if the device
    explicitly asks for it.
    """

    def __init__(
        self,
        base_url: str,
        *,
        username: str | None = "maker",
        password: str | None = None,
        timeout: float = 5.0,
        on_state_change: Any | None = None,
        on_print_start: Any | None = None,
        on_print_complete: Any | None = None,
        on_bed_temp_update: Any | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("PrusaLink base URL is required")
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username or "maker"
        self.password = password
        self.timeout = timeout
        self.state = PrusaLinkPrinterState()
        self._job_id: int | None = None
        self.on_state_change = on_state_change
        self.on_print_start = on_print_start
        self.on_print_complete = on_print_complete
        self.on_bed_temp_update = on_bed_temp_update
        self._last_state: str | None = None
        self._has_status_sample = False
        self._last_bed_temp: float | None = None

    @property
    def _basic_auth(self) -> httpx.BasicAuth | None:
        return _prusalink_basic_auth(self.username, self.password)

    @property
    def _digest_auth(self) -> httpx.DigestAuth | None:
        return _prusalink_digest_auth(self.username, self.password)

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.password} if self.password else {}

    def _request(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> httpx.Response:
        url = urljoin(self.base_url, path.lstrip("/"))
        request_fn = getattr(httpx, method.lower())
        kwargs: dict[str, Any] = {"auth": self._basic_auth, "headers": self._headers, "timeout": self.timeout}
        if json_payload is not None:
            kwargs["json"] = json_payload
        response = request_fn(url, **kwargs)
        authenticate = response.headers.get("www-authenticate", "").lower()
        if response.status_code == 401 and "digest" in authenticate and self._digest_auth is not None:
            kwargs["auth"] = self._digest_auth
            response = request_fn(url, **kwargs)
        return response

    def _get(self, path: str) -> dict[str, Any]:
        response = self._request("get", path)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"value": data}

    def _put(self, path: str) -> bool:
        response = self._request("put", path)
        response.raise_for_status()
        return True

    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        response = self._request("post", path, json_payload=payload)
        if response.status_code == 404:
            logger.warning("PrusaLink endpoint not found for POST %s; command unsupported by this firmware", path)
            return False
        response.raise_for_status()
        return True

    def _delete(self, path: str) -> bool:
        response = self._request("delete", path)
        response.raise_for_status()
        return True

    def list_files(self, path: str = "/") -> list[dict[str, Any]]:
        api_path = "api/v1/files/local"
        normalized = path.strip("/")
        if normalized:
            api_path += "/" + quote(normalized, safe="/")
        data = self._get(api_path)
        children = data.get("children") or data.get("files") or []
        files: list[dict[str, Any]] = []
        for child in children if isinstance(children, list) else []:
            if not isinstance(child, dict):
                continue
            name = str(child.get("display_name") or child.get("name") or "").strip()
            if not name:
                continue
            child_type = str(child.get("type") or "file").lower()
            full_path = f"/{normalized}/{name}" if normalized else f"/{name}"
            files.append(
                {
                    "name": name,
                    "type": "directory" if child_type in {"folder", "directory", "dir"} else "file",
                    "size": child.get("size"),
                    "modified": child.get("m_timestamp") or child.get("modified"),
                    "path": full_path,
                }
            )
        return files

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        normalized = remote_path.strip("/") or local_path.name
        url = urljoin(self.base_url, f"api/v1/files/local/{quote(normalized, safe='/')}")
        with open(local_path, "rb") as fh:
            kwargs: dict[str, Any] = {
                "auth": self._basic_auth,
                "headers": {**self._headers, "Content-Type": "application/octet-stream"},
                "timeout": max(self.timeout, 60.0),
                "content": fh.read(),
            }
            response = httpx.put(url, **kwargs)
        authenticate = response.headers.get("www-authenticate", "").lower()
        if response.status_code == 401 and "digest" in authenticate and self._digest_auth is not None:
            with open(local_path, "rb") as fh:
                kwargs["auth"] = self._digest_auth
                kwargs["content"] = fh.read()
                response = httpx.put(url, **kwargs)
        response.raise_for_status()
        return True

    def download_file(self, remote_path: str) -> bytes | None:
        normalized = remote_path.strip("/")
        url = urljoin(self.base_url, f"api/v1/files/local/{quote(normalized, safe='/')}/raw")
        response = httpx.get(url, auth=self._basic_auth, headers=self._headers, timeout=max(self.timeout, 60.0))
        authenticate = response.headers.get("www-authenticate", "").lower()
        if response.status_code == 401 and "digest" in authenticate and self._digest_auth is not None:
            response = httpx.get(url, auth=self._digest_auth, headers=self._headers, timeout=max(self.timeout, 60.0))
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    def delete_file(self, remote_path: str) -> bool:
        normalized = remote_path.strip("/")
        return self._delete(f"api/v1/files/local/{quote(normalized, safe='/')}")

    def connect(self) -> None:
        info = self._get("api/v1/info")
        self.state.connected = True
        self.state.raw_data = info
        self.state.raw_status = info
        self.state.sdcard = bool(info.get("sd_ready"))
        self.state.ipcam = bool(info.get("active_camera"))
        self.state.firmware_version = str(info.get("firmware") or "") or None
        self.request_status_update()

    def disconnect(self, timeout: float = 0) -> None:  # noqa: ARG002 - kept for provider compatibility
        self.state.connected = False

    def check_staleness(self) -> bool:
        try:
            self.request_status_update()
        except Exception:
            self.state.connected = False
        return self.state.connected

    def _build_lifecycle_payload(self) -> dict[str, Any]:
        filename = self.state.subtask_name or self.state.current_print or self.state.gcode_file or "Unknown"
        return {
            "filename": filename,
            "subtask_name": filename,
            "progress": self.state.progress,
            "remaining_time": self.state.remaining_time * 60 if self.state.remaining_time else None,
            "status": self.state.state,
        }

    def _emit_status_callbacks(self, previous_state: str | None) -> None:
        if self.on_state_change:
            self.on_state_change(self.state)

        bed_temp = self.state.temperatures.get("bed") if self.state.temperatures else None
        if isinstance(bed_temp, (int, float)) and bed_temp != self._last_bed_temp:
            self._last_bed_temp = float(bed_temp)
            if self.on_bed_temp_update:
                self.on_bed_temp_update(float(bed_temp))

        current_state = self.state.state
        previous_running = previous_state in {"RUNNING", "PRINTING"}
        current_running = current_state in {"RUNNING", "PRINTING"}

        if previous_state is not None and not previous_running and current_running:
            if self.on_print_start:
                self.on_print_start(self._build_lifecycle_payload())
        elif previous_running and not current_running:
            payload = self._build_lifecycle_payload()
            if current_state == "FAILED":
                payload["status"] = "failed"
            elif current_state in {"FINISH", "IDLE"}:
                payload["status"] = "completed" if self.state.progress >= 99 else "stopped"
            else:
                payload["status"] = "stopped"
            if self.on_print_complete:
                self.on_print_complete(payload)

    def request_status_update(self) -> bool:
        previous_state = self._last_state if self._has_status_sample else None
        status = self._get("api/v1/status")
        self.state.connected = True
        self.state.raw_status = status
        self.state.raw_data = {**self.state.raw_data, **status}

        printer = status.get("printer", {}) if isinstance(status, dict) else {}
        job = status.get("job", {}) if isinstance(status, dict) else {}
        if not isinstance(printer, dict):
            printer = {}
        if not isinstance(job, dict):
            job = {}

        self._job_id = job.get("id") if isinstance(job.get("id"), int) else self._job_id
        self.state.state = _map_prusalink_state(printer.get("state"))
        self.state.progress = _progress_percent(job.get("progress"))
        self.state.remaining_time = _minutes_from_seconds(job.get("time_remaining"))
        self.state.temperatures = {
            "nozzle": float(printer.get("temp_nozzle") or 0.0),
            "nozzle_target": float(printer.get("target_nozzle") or 0.0),
            "nozzle_heating": float(printer.get("target_nozzle") or 0.0) - float(printer.get("temp_nozzle") or 0.0)
            > 1.0,
            "bed": float(printer.get("temp_bed") or 0.0),
            "bed_target": float(printer.get("target_bed") or 0.0),
            "bed_heating": float(printer.get("target_bed") or 0.0) - float(printer.get("temp_bed") or 0.0) > 1.0,
        }

        try:
            job_detail = self._get("api/v1/job")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 204:
                raise
            job_detail = {}
        if job_detail:
            self._apply_job_detail(job_detail)

        self._emit_status_callbacks(previous_state)
        self._last_state = self.state.state
        self._has_status_sample = True
        return True

    def _apply_job_detail(self, job_detail: dict[str, Any]) -> None:
        self._job_id = job_detail.get("id") if isinstance(job_detail.get("id"), int) else self._job_id
        if job_detail.get("state"):
            self.state.state = _map_prusalink_state(job_detail.get("state"))
        if "progress" in job_detail:
            self.state.progress = _progress_percent(job_detail.get("progress"))
        if "time_remaining" in job_detail:
            self.state.remaining_time = _minutes_from_seconds(job_detail.get("time_remaining"))
        file_info = job_detail.get("file") if isinstance(job_detail.get("file"), dict) else {}
        filename = file_info.get("display_name") or file_info.get("name") or file_info.get("path")
        if filename:
            self.state.gcode_file = str(filename)
            self.state.current_print = str(filename)
            self.state.subtask_name = str(filename)

    def send_gcode(self, script: str) -> bool:
        """Map Printbuddy's limited control G-code scripts to PrusaLink control endpoints.

        PrusaLink does not expose a raw arbitrary-G-code endpoint, but it does
        provide OctoPrint-compatible control endpoints under ``/api/printer/*``.
        Only the safe/simple commands generated by Printbuddy controls are
        translated here; anything else returns ``False`` instead of pretending
        arbitrary G-code is supported.
        """
        lines = [line.strip() for line in script.splitlines() if line.strip()]
        normalized = [line.upper() for line in lines]

        if normalized == ["M84"]:
            return self._post("api/printer/printhead", {"command": "disable_steppers"})

        if normalized and normalized[0].startswith("G28"):
            parts = normalized[0].split()[1:]
            payload: dict[str, Any] = {"command": "home"}
            if parts:
                payload["axes"] = [part[0] for part in parts if part and part[0] in "XYZ"]
            return self._post("api/printer/printhead", payload)

        if len(normalized) == 3 and normalized[0] == "G91" and normalized[2] == "G90":
            match = re.fullmatch(r"G1\s+([XYZ])(-?\d+(?:\.\d+)?)\s+F(\d+)", normalized[1])
            if match:
                axis, distance, feedrate = match.groups()
                return self._post(
                    "api/printer/printhead",
                    {"command": "jog", axis.lower(): float(distance), "feedrate": int(feedrate)},
                )

        if len(normalized) == 3 and normalized[0] == "M83" and normalized[2] == "M82":
            match = re.fullmatch(r"G1\s+E(-?\d+(?:\.\d+)?)\s+F(\d+)", normalized[1])
            if match:
                amount, feedrate = match.groups()
                return self._post(
                    "api/printer/tool", {"command": "extrude", "amount": float(amount), "feedrate": int(feedrate)}
                )

        return False

    def set_nozzle_temperature(self, target: int | float) -> bool:
        return self._post("api/printer/tool", {"command": "target", "targets": {"tool0": int(target)}})

    def set_bed_temperature(self, target: int | float) -> bool:
        return self._post("api/printer/bed", {"command": "target", "target": int(target)})

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        normalized = filename.strip("/")
        response = self._request("post", f"api/v1/files/local/{quote(normalized, safe='/')}/print")
        response.raise_for_status()
        return True

    def stop_print(self) -> bool:
        if self._job_id is None:
            self.request_status_update()
        return self._delete(f"api/v1/job/{self._job_id}") if self._job_id is not None else False

    def pause_print(self) -> bool:
        if self._job_id is None:
            self.request_status_update()
        return self._put(f"api/v1/job/{self._job_id}/pause") if self._job_id is not None else False

    def resume_print(self) -> bool:
        if self._job_id is None:
            self.request_status_update()
        return self._put(f"api/v1/job/{self._job_id}/resume") if self._job_id is not None else False


def create_prusalink_client(printer: Any, **callbacks: Any) -> PrusaLinkPrinterClient:  # noqa: ARG001
    base_url = printer.api_url or f"http://{printer.ip_address}"
    username = "maker"
    options_raw = getattr(printer, "provider_options", None)
    if options_raw:
        try:
            options = json.loads(options_raw) if isinstance(options_raw, str) else options_raw
            if isinstance(options, dict) and str(options.get("username") or "").strip():
                username = str(options["username"]).strip()
        except (TypeError, ValueError):
            pass
    return PrusaLinkPrinterClient(
        base_url=base_url,
        username=username,
        password=getattr(printer, "auth_token", None),
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
