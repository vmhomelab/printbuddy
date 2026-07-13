from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.app.services.bambu_mqtt import FilaSwitchState, NozzleInfo, PrintOptions

logger = logging.getLogger(__name__)

SDCP_WS_PORT = 3030
SDCP_DISCOVERY_PORT = 3000
SDCP_DISCOVERY_MESSAGE = b"M99999"
SDCP_STATUS_COMMAND = 0


@dataclass
class ElegooSDCPPrinterState:
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


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _progress_percent(value: Any) -> float:
    progress = _as_float(value, 0.0)
    if 0.0 <= progress <= 1.0:
        progress *= 100.0
    return max(0.0, min(100.0, progress))


def _map_sdcp_status(status_code: Any, print_info: dict[str, Any]) -> str:
    """Map Elegoo SDCP status codes to Printbuddy states.

    Code 3 is deliberately not mapped to FINISH. Public SDCP examples disagree
    on whether it means stopped/cancelled/idle-like, and a false FINISH would
    trigger Printbuddy queue and plate-clear side effects.
    """
    code = _as_int(status_code, -1)
    if code in {1, 5, 6}:
        return "RUNNING"
    if code == 7:
        return "PAUSE"
    if code in {4, 9}:
        return "FINISH"
    if code in {2, 8}:
        return "FAILED"
    if code == 3:
        progress = _progress_percent(_first_present(print_info, "Progress", "progress", "PrintProgress", "printProgress"))
        return "FAILED" if 0 < progress < 99 else "IDLE"
    if code == 0:
        return "IDLE"
    return "unknown"


def _extract_status_payload(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {}
    if isinstance(message.get("Status"), dict):
        return message["Status"]
    data = message.get("Data") or message.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("Status"), dict):
            return data["Status"]
        return data
    return message


def _temp_from(data: Any, *keys: str) -> float:
    if isinstance(data, dict):
        return _as_float(_first_present(data, *keys))
    return 0.0


def _sdcp_temperatures(status: dict[str, Any]) -> dict[str, Any]:
    nozzle = status.get("TempOfNozzle") if isinstance(status.get("TempOfNozzle"), dict) else status
    bed = status.get("TempOfHotbed") if isinstance(status.get("TempOfHotbed"), dict) else status
    return {
        "nozzle": _temp_from(nozzle, "Temp", "ActualTemp", "NozzleTemp", "nozzle"),
        "nozzle_target": _temp_from(nozzle, "TargetTemp", "Target", "NozzleTargetTemp", "nozzle_target"),
        "bed": _temp_from(bed, "Temp", "ActualTemp", "BedTemp", "bed"),
        "bed_target": _temp_from(bed, "TargetTemp", "Target", "BedTargetTemp", "bed_target"),
    }


class ElegooSDCPPrinterClient:
    """Minimal Elegoo SDCP provider client for status/test integration.

    Original Elegoo Centauri Carbon SDCP exposes a LAN WebSocket at
    ``ws://<host>:3030/websocket`` and a UDP ``M99999`` discovery probe on port
    3000. This first provider is intentionally conservative: it connects, reads
    status, normalizes progress/temperatures, and leaves upload/start for a
    later hardware-validated pass.
    """

    def __init__(
        self,
        host: str,
        *,
        timeout: float = 5.0,
        on_state_change: Any | None = None,
        on_print_start: Any | None = None,
        on_print_complete: Any | None = None,
        on_bed_temp_update: Any | None = None,
    ) -> None:
        if not host:
            raise ValueError("Elegoo SDCP host/IP is required")
        self.host = self._normalize_host(host)
        self.timeout = timeout
        self.state = ElegooSDCPPrinterState()
        self.on_state_change = on_state_change
        self.on_print_start = on_print_start
        self.on_print_complete = on_print_complete
        self.on_bed_temp_update = on_bed_temp_update
        self.printer_id: str | None = None
        self.mainboard_id: str | None = None
        self.discovery_info: dict[str, Any] = {}
        self._last_state: str | None = None
        self._has_status_sample = False
        self._last_bed_temp: float | None = None
        self._current_print_started_at: float | None = None

    @staticmethod
    def _normalize_host(value: str) -> str:
        raw = value.strip()
        parsed = urlparse(raw if "://" in raw else f"sdcp://{raw}")
        return (parsed.hostname or raw).strip("[]")

    @property
    def websocket_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"ws://{host}:{SDCP_WS_PORT}/websocket"

    def discover(self) -> dict[str, Any]:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            sock.sendto(SDCP_DISCOVERY_MESSAGE, (self.host, SDCP_DISCOVERY_PORT))
            payload, _addr = sock.recvfrom(65535)
        text = payload.decode("utf-8", errors="replace").strip("\x00\r\n ")
        data = json.loads(text)
        if isinstance(data, dict):
            self.discovery_info = data
            self.printer_id = str(_first_present(data, "Id", "id") or "") or None
            self.mainboard_id = str(_first_present(data, "MainboardID", "MainboardId", "Id", "id") or "") or None
            return data
        return {"value": data}

    async def _query_status_async(self) -> dict[str, Any]:
        import websockets

        request_id = str(int(time.time() * 1000))
        command: dict[str, Any] = {
            "Id": self.printer_id or "",
            "Data": {
                "Cmd": SDCP_STATUS_COMMAND,
                "Data": {},
                "From": 0,
                "MainboardID": self.mainboard_id or "",
                "RequestID": request_id,
                "Timestamp": int(time.time()),
            },
        }
        if self.mainboard_id:
            command["Topic"] = f"sdcp/request/{self.mainboard_id}"

        async with websockets.connect(self.websocket_url, open_timeout=self.timeout, close_timeout=1) as websocket:
            await websocket.send(json.dumps(command, separators=(",", ":")))
            deadline = time.monotonic() + self.timeout
            last_message: dict[str, Any] = {}
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(websocket.recv(), timeout=max(0.1, deadline - time.monotonic()))
                try:
                    message = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(message, dict):
                    last_message = message
                    topic = str(message.get("Topic") or "").lower()
                    if "/response/" in topic:
                        continue
                    if _extract_status_payload(message):
                        return message
            return last_message

    def _query_status(self) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._query_status_async())

        result: dict[str, Any] = {}
        error: BaseException | None = None

        def runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(self._query_status_async())
            except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
                error = exc

        thread = threading.Thread(target=runner, name="elegoo-sdcp-status", daemon=True)
        thread.start()
        thread.join(timeout=self.timeout + 2)
        if thread.is_alive():
            raise TimeoutError("Elegoo SDCP status query timed out")
        if error is not None:
            raise error
        return result

    def connect(self) -> None:
        try:
            self.discover()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Elegoo SDCP UDP discovery failed for %s: %s", self.host, type(exc).__name__)
        self.request_status_update()

    def disconnect(self, timeout: float = 0) -> None:  # noqa: ARG002
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
            "raw_data": self.state.raw_data,
        }

    def _emit_status_callbacks(self, previous_state: str | None) -> None:
        if self.on_state_change:
            self.on_state_change(self.state)
        bed_temp = self.state.temperatures.get("bed") if self.state.temperatures else None
        if isinstance(bed_temp, int | float) and bed_temp != self._last_bed_temp:
            self._last_bed_temp = float(bed_temp)
            if self.on_bed_temp_update:
                self.on_bed_temp_update(float(bed_temp))
        current_state = self.state.state
        previous_running = previous_state in {"RUNNING", "PAUSE"}
        current_running = current_state in {"RUNNING", "PAUSE"}
        if previous_state is not None and not previous_running and current_running:
            self._current_print_started_at = time.monotonic()
            if self.on_print_start:
                self.on_print_start(self._build_lifecycle_payload())
        elif previous_running and not current_running:
            payload = self._build_lifecycle_payload()
            if self._current_print_started_at is not None:
                payload["actual_time_seconds"] = max(1, int(time.monotonic() - self._current_print_started_at))
                self._current_print_started_at = None
            payload["status"] = "completed" if current_state == "FINISH" else "stopped"
            if current_state == "FAILED":
                payload["status"] = "failed"
            if self.on_print_complete:
                self.on_print_complete(payload)

    def request_status_update(self) -> bool:
        previous_state = self._last_state if self._has_status_sample else None
        message = self._query_status()
        status = _extract_status_payload(message)
        print_info = status.get("PrintInfo") if isinstance(status.get("PrintInfo"), dict) else status
        self.state.connected = True
        self.state.raw_status = status
        self.state.raw_data = {"sdcp": message, "discovery": self.discovery_info}
        self.state.state = _map_sdcp_status(
            _first_present(status, "Status", "CurrentStatus", "PrintStatus", "MachineStatus", "status"),
            print_info if isinstance(print_info, dict) else {},
        )
        filename = _first_present(print_info if isinstance(print_info, dict) else status, "Filename", "FileName", "filename", "Name")
        if filename:
            self.state.gcode_file = str(filename)
            self.state.current_print = self.state.gcode_file
            self.state.subtask_name = self.state.gcode_file
        self.state.progress = _progress_percent(
            _first_present(print_info if isinstance(print_info, dict) else status, "Progress", "PrintProgress", "progress")
        )
        self.state.remaining_time = _as_int(
            _first_present(print_info if isinstance(print_info, dict) else status, "RemainingTime", "LeftTime", "RemainTime", "remaining_time"),
            0,
        )
        self.state.layer_num = _as_int(
            _first_present(print_info if isinstance(print_info, dict) else status, "CurrentLayer", "Layer", "layer_num"),
            0,
        )
        self.state.total_layers = _as_int(
            _first_present(print_info if isinstance(print_info, dict) else status, "TotalLayer", "TotalLayers", "total_layers"),
            0,
        )
        self.state.temperatures = _sdcp_temperatures(status)
        self._emit_status_callbacks(previous_state)
        self._last_state = self.state.state
        self._has_status_sample = True
        return True

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        logger.warning("Elegoo SDCP start_print is not implemented yet; status/test integration only")
        return False

    def stop_print(self) -> bool:
        logger.warning("Elegoo SDCP stop_print is not implemented yet; status/test integration only")
        return False

    def list_files(self, path: str = "/") -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def upload_file(self, local_path: Path, remote_path: str, *, overwrite: bool = False) -> bool:  # noqa: ARG002
        return False

    def download_file(self, remote_path: str) -> bytes | None:  # noqa: ARG002
        return None

    def delete_file(self, remote_path: str) -> bool:  # noqa: ARG002
        return False


def create_elegoo_sdcp_client(printer: Any, **callbacks: Any) -> ElegooSDCPPrinterClient:
    return ElegooSDCPPrinterClient(
        host=getattr(printer, "ip_address", ""),
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
