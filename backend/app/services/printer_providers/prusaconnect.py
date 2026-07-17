from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from backend.app.services.bambu_mqtt import FilaSwitchState, NozzleInfo, PrintOptions

PRUSA_CONNECT_MOBILE_BASE_URL = "https://connect-mobile-api.prusa3d.com"


@dataclass
class PrusaConnectMobilePrinterState:
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
    position: dict[str, float] = field(default_factory=dict)


def _normalize_base_url(base_url: str | None) -> str:
    raw = (base_url or PRUSA_CONNECT_MOBILE_BASE_URL).strip() or PRUSA_CONNECT_MOBILE_BASE_URL
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return raw.rstrip("/") + "/"


def _map_prusa_connect_state(raw_state: Any) -> str:
    state = str(raw_state or "").upper()
    return {
        "PRINTING": "RUNNING",
        "PAUSED": "PAUSE",
        "FINISHED": "FINISH",
        "STOPPED": "FAILED",
        "ERROR": "FAILED",
        "ATTENTION": "FAILED",
        "READY": "IDLE",
        "IDLE": "IDLE",
        "BUSY": "PREPARE",
        "MANIPULATING": "PREPARE",
        "OFFLINE": "OFFLINE",
        "UNKNOWN": "unknown",
    }.get(state, state or "unknown")


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _minutes_from_seconds(value: Any) -> int:
    try:
        return max(0, int(float(value) // 60))
    except (TypeError, ValueError):
        return 0


def _progress_percent(value: Any) -> float:
    progress = _float_or_zero(value)
    if 0 <= progress <= 1:
        progress *= 100
    return max(0.0, min(progress, 100.0))


def _first_present(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values and values[key] is not None:
            return values[key]
    return None


class PrusaConnectMobilePrinterClient:
    """Client for the Prusa Connect mobile API.

    The mobile API is cloud-scoped: the configured printer address field stores
    the Prusa Connect printer UUID, and auth_token stores the mobile API JWT / Authorization token.
    """

    def __init__(self, printer_uuid: str, auth_token: str | None = None, base_url: str | None = None):
        self.printer_uuid = printer_uuid.strip()
        self.auth_token = (auth_token or "").strip()
        self.base_url = _normalize_base_url(base_url)
        self.state = PrusaConnectMobilePrinterState()

    def _headers(self) -> dict[str, str]:
        if not self.auth_token:
            return {}
        token = self.auth_token
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        return {"Authorization": token}

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = getattr(httpx, method)(self._url(path), headers=self._headers(), timeout=20, **kwargs)
        response.raise_for_status()
        return response

    def _get(self, path: str) -> dict[str, Any]:
        response = self._request("get", path)
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _put(self, path: str, payload: dict[str, Any] | None = None) -> bool:
        kwargs = {"json": payload} if payload is not None else {}
        response = self._request("put", path, **kwargs)
        return response.status_code < 300

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> bool:
        kwargs = {"json": payload} if payload is not None else {}
        response = self._request("post", path, **kwargs)
        return response.status_code < 300

    def connect(self) -> None:
        self.request_status_update()

    def disconnect(self, timeout: float = 0) -> None:  # noqa: ARG002 - provider compatibility
        self.state.connected = False

    def check_staleness(self) -> bool:
        try:
            self.request_status_update()
        except Exception:
            self.state.connected = False
        return self.state.connected

    def request_status_update(self) -> bool:
        data = self._get(f"api/v1/printers/{quote(self.printer_uuid, safe='')}")
        self.state.connected = _map_prusa_connect_state(data.get("state")) != "OFFLINE"
        self.state.raw_status = data
        self.state.raw_data = {**self.state.raw_data, **data}
        self.state.state = _map_prusa_connect_state(data.get("state"))
        self.state.firmware_version = str(data.get("firmware") or "") or None
        self.state.ipcam = bool(data.get("defaultSnapshot") or data.get("snapshots"))

        raw_telemetry = data.get("telemetry")
        telemetry: dict[str, Any] = raw_telemetry if isinstance(raw_telemetry, dict) else {}
        self.state.temperatures = {
            "nozzle": _float_or_zero(_first_present(telemetry, "temperatureNozzleCurrent", "temp_nozzle", "nozzle")),
            "nozzle_target": _float_or_zero(
                _first_present(telemetry, "temperatureNozzleTarget", "target_nozzle", "nozzle_target")
            ),
            "bed": _float_or_zero(_first_present(telemetry, "temperatureHeatbedCurrent", "temp_bed", "bed")),
            "bed_target": _float_or_zero(
                _first_present(telemetry, "temperatureHeatbedTarget", "target_bed", "bed_target")
            ),
        }
        self.state.temperatures["nozzle_heating"] = (
            self.state.temperatures["nozzle_target"] - self.state.temperatures["nozzle"] > 1.0
        )
        self.state.temperatures["bed_heating"] = (
            self.state.temperatures["bed_target"] - self.state.temperatures["bed"] > 1.0
        )

        axis_z = _first_present(telemetry, "axisZ", "axis_z", "z")
        if axis_z is not None:
            self.state.position = {"z": _float_or_zero(axis_z)}

        raw_job = data.get("job")
        job: dict[str, Any] = raw_job if isinstance(raw_job, dict) else {}
        self._apply_job(job)
        return True

    def _apply_job(self, job: dict[str, Any]) -> None:
        if not job:
            self.state.progress = 0.0 if self.state.state in {"IDLE", "FINISH", "OFFLINE"} else self.state.progress
            return
        filename = _first_present(job, "fileName", "display_name", "filename", "name")
        if filename:
            self.state.gcode_file = str(filename)
            self.state.current_print = str(filename)
            self.state.subtask_name = str(filename)
        if "progress" in job:
            self.state.progress = _progress_percent(job.get("progress"))
        remaining = _first_present(job, "timeRemaining", "time_remaining", "remainingTime")
        if remaining is not None:
            self.state.remaining_time = _minutes_from_seconds(remaining)

    def stop_print(self) -> bool:
        return self._put(f"api/v1/printers/{quote(self.printer_uuid, safe='')}/command/stop")

    def pause_print(self) -> bool:
        return self._put(f"api/v1/printers/{quote(self.printer_uuid, safe='')}/command/pause")

    def resume_print(self) -> bool:
        return self._put(f"api/v1/printers/{quote(self.printer_uuid, safe='')}/command/resume")

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        # The mobile API can queue cloud/file/printables starts, but those require
        # cloud-specific identifiers rather than local filesystem paths. Keep this
        # explicit until Printbuddy has a cloud-file picker.
        return False

    def send_gcode(self, script: str) -> bool:  # noqa: ARG002
        return False

    def set_nozzle_temperature(self, target: int | float) -> bool:  # noqa: ARG002
        return False

    def set_bed_temperature(self, target: int | float) -> bool:  # noqa: ARG002
        return False

    def list_files(self, path: str = "/") -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def upload_file(self, local_path: Path, remote_path: str, *, overwrite: bool = False) -> bool:  # noqa: ARG002
        return False

    def download_file(self, remote_path: str) -> bytes | None:  # noqa: ARG002
        return None

    def delete_file(self, remote_path: str) -> bool:  # noqa: ARG002
        return False

    def get_filaments(self) -> list[dict[str, Any]]:
        return []

    def get_print_history(self, start_time: datetime | None = None, end_time: datetime | None = None) -> list[dict]:
        now = datetime.now(timezone.utc)
        return [
            {
                "print_id": f"prusaconnect-{self.printer_uuid}-{int(now.timestamp())}",
                "filename": self.state.gcode_file or self.state.current_print or "unknown",
                "status": self.state.state,
                "start_time": now.isoformat(),
                "end_time": None,
                "duration": 0,
                "filament_used": 0,
                "success": self.state.state in {"FINISH", "IDLE"},
            }
        ]


def create_prusa_connect_mobile_client(printer: Any, **callbacks: Any) -> PrusaConnectMobilePrinterClient:  # noqa: ARG001
    return PrusaConnectMobilePrinterClient(
        printer_uuid=str(getattr(printer, "ip_address", "") or "").strip(),
        auth_token=getattr(printer, "auth_token", None),
        base_url=getattr(printer, "api_url", None) or PRUSA_CONNECT_MOBILE_BASE_URL,
    )
