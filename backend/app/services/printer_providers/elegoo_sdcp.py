from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.services.bambu_mqtt import FilaSwitchState, NozzleInfo, PrintOptions

logger = logging.getLogger(__name__)

SDCP_WS_PORT = 3030
SDCP_DISCOVERY_PORT = 3000
SDCP_DISCOVERY_MESSAGE = b"M99999"
SDCP_STATUS_COMMAND = 0
SDCP_START_PRINT_COMMAND = 128
SDCP_PAUSE_PRINT_COMMAND = 129
SDCP_STOP_PRINT_COMMAND = 130
SDCP_RESUME_PRINT_COMMAND = 131
SDCP_EDIT_STATUS_DATA_COMMAND = 403
SDCP_UPLOAD_CHUNK_SIZE = 1024 * 1024
SDCP_START_SETTLE_SECONDS = 1.0
SDCP_START_VERIFY_TIMEOUT = 12.0
SDCP_START_VERIFY_INTERVAL = 1.0


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
    sdcp_connection: dict[str, Any] = field(default_factory=dict)


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, list | tuple):
        value = value[0] if value else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, list | tuple):
        value = value[0] if value else default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _progress_percent(value: Any) -> float:
    progress = _as_float(value, 0.0)
    if 0.0 <= progress <= 1.0:
        progress *= 100.0
    return max(0.0, min(100.0, progress))


def _progress_from_print_info(print_info: dict[str, Any]) -> float:
    explicit = _first_present(print_info, "Progress", "PrintProgress", "progress", "printProgress")
    if explicit is not None:
        return _progress_percent(explicit)
    current_ticks = _as_float(_first_present(print_info, "CurrentTicks", "currentTicks"), 0.0)
    total_ticks = _as_float(_first_present(print_info, "TotalTicks", "totalTicks"), 0.0)
    if total_ticks > 0:
        return max(0.0, min(100.0, (current_ticks / total_ticks) * 100.0))
    return 0.0


def _map_sdcp_status(status_code: Any, print_info: dict[str, Any]) -> str:
    """Map Elegoo SDCP status codes to Printbuddy states.

    Code 3 is deliberately not mapped to FINISH. Public SDCP examples disagree
    on whether it means stopped/cancelled/idle-like, and a false FINISH would
    trigger Printbuddy queue and plate-clear side effects.
    """
    code = _as_int(status_code, -1)
    if code in {1, 13, 16, 18, 21}:
        return "RUNNING"
    if code == 2:
        return "PAUSE"
    if code in {4, 9}:
        return "FINISH"
    if code == 8:
        return "FAILED"
    if code == 3:
        progress = _progress_from_print_info(print_info)
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
    if isinstance(data, int | float):
        return float(data)
    return 0.0


def _sdcp_temperatures(status: dict[str, Any]) -> dict[str, Any]:
    nozzle = status.get("TempOfNozzle") if "TempOfNozzle" in status else status
    bed = status.get("TempOfHotbed") if "TempOfHotbed" in status else status
    chamber = status.get("TempOfBox") if "TempOfBox" in status else status.get("TempOfChamber")
    chamber_target_value = _first_present(status, "TempTargetBox", "TempTargetChamber", "chamber_target")
    nozzle_target_source = nozzle if isinstance(nozzle, dict) else status
    bed_target_source = bed if isinstance(bed, dict) else status
    temperatures = {
        "nozzle": _temp_from(nozzle, "Temp", "ActualTemp", "NozzleTemp", "nozzle", "TempOfNozzle"),
        "nozzle_target": _temp_from(
            nozzle_target_source, "TargetTemp", "Target", "NozzleTargetTemp", "TempTargetNozzle", "nozzle_target"
        ),
        "bed": _temp_from(bed, "Temp", "ActualTemp", "BedTemp", "bed", "TempOfHotbed"),
        "bed_target": _temp_from(
            bed_target_source, "TargetTemp", "Target", "BedTargetTemp", "TempTargetHotbed", "bed_target"
        ),
    }
    if chamber is not None or chamber_target_value is not None:
        chamber_target_source = chamber if isinstance(chamber, dict) else status
        chamber_target = _temp_from(
            chamber_target_source,
            "TargetTemp",
            "Target",
            "BoxTargetTemp",
            "ChamberTargetTemp",
            "TempTargetBox",
            "TempTargetChamber",
            "chamber_target",
        )
        chamber_actual = _temp_from(
            chamber, "Temp", "ActualTemp", "BoxTemp", "ChamberTemp", "TempOfBox", "TempOfChamber", "chamber"
        )
        temperatures["chamber"] = chamber_actual if chamber is not None else chamber_target
        temperatures["chamber_target"] = chamber_target
    return temperatures


def _fan_speed(value: Any) -> int | None:
    if value is None:
        return None
    return max(0, min(100, _as_int(value)))


def _sdcp_light_enabled(value: Any) -> bool:
    if isinstance(value, dict):
        second_light = value.get("SecondLight")
        if second_light is not None:
            return bool(_as_int(second_light))
        rgb = value.get("RgbLight")
        if isinstance(rgb, list | tuple):
            return any(_as_int(channel) > 0 for channel in rgb)
    return bool(_as_int(value))


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
            self.state.firmware_version = (
                str(_first_present(data, "FirmwareVersion", "Firmware", "firmware_version") or "") or None
            )
            self.state.sdcp_connection = self.connection_details
            return data
        return {"value": data}

    @property
    def connection_details(self) -> dict[str, Any]:
        return {
            "printer_id": self.printer_id,
            "mainboard_id": self.mainboard_id,
            "protocol_version": _first_present(self.discovery_info, "ProtocolVersion", "protocol_version"),
            "firmware_version": _first_present(self.discovery_info, "FirmwareVersion", "Firmware", "firmware_version"),
            "machine_name": _first_present(self.discovery_info, "MachineName", "Name", "machine_name"),
            "brand_name": _first_present(self.discovery_info, "BrandName", "brand_name"),
        }

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

    async def _send_command_async(self, command: dict[str, Any]) -> dict[str, Any]:
        import websockets

        request_id = str(command.get("Data", {}).get("RequestID") or int(time.time() * 1000))
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
                if not isinstance(message, dict):
                    continue
                last_message = message
                data = message.get("Data") if isinstance(message.get("Data"), dict) else {}
                if data.get("RequestID") == request_id:
                    return message
            return last_message

    def _send_command(self, command: dict[str, Any]) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._send_command_async(command))

        result: dict[str, Any] = {}
        error: BaseException | None = None

        def runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(self._send_command_async(command))
            except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
                error = exc

        thread = threading.Thread(target=runner, name="elegoo-sdcp-command", daemon=True)
        thread.start()
        thread.join(timeout=self.timeout + 2)
        if thread.is_alive():
            raise TimeoutError("Elegoo SDCP command timed out")
        if error is not None:
            raise error
        return result

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
        self.state.raw_data = {
            "sdcp": message,
            "discovery": self.discovery_info,
            "sdcp_connection": self.connection_details,
        }
        self.state.sdcp_connection = self.connection_details
        self.state.firmware_version = (
            self.state.firmware_version
            or str(_first_present(self.discovery_info, "FirmwareVersion", "Firmware", "firmware_version") or "")
            or None
        )
        status_code = _first_present(status, "Status", "CurrentStatus", "PrintStatus", "MachineStatus", "status")
        if status_code is None and isinstance(print_info, dict):
            status_code = _first_present(
                print_info, "Status", "CurrentStatus", "PrintStatus", "MachineStatus", "status"
            )
        self.state.state = _map_sdcp_status(
            status_code,
            print_info if isinstance(print_info, dict) else {},
        )
        filename = _first_present(
            print_info if isinstance(print_info, dict) else status, "Filename", "FileName", "filename", "Name"
        )
        if filename:
            self.state.gcode_file = str(filename)
            self.state.current_print = self.state.gcode_file
            self.state.subtask_name = self.state.gcode_file
        self.state.progress = _progress_from_print_info(print_info if isinstance(print_info, dict) else status)
        self.state.remaining_time = _as_int(
            _first_present(
                print_info if isinstance(print_info, dict) else status,
                "RemainingTime",
                "LeftTime",
                "RemainTime",
                "remainTime",
                "remaining_time",
            ),
            0,
        )
        self.state.layer_num = _as_int(
            _first_present(
                print_info if isinstance(print_info, dict) else status, "CurrentLayer", "Layer", "layer_num"
            ),
            0,
        )
        self.state.total_layers = _as_int(
            _first_present(
                print_info if isinstance(print_info, dict) else status, "TotalLayer", "TotalLayers", "total_layers"
            ),
            0,
        )
        self.state.temperatures = _sdcp_temperatures(status)
        fan_speed_raw = status.get("CurrentFanSpeed")
        fan_speed: dict[str, Any] = fan_speed_raw if isinstance(fan_speed_raw, dict) else {}
        self.state.cooling_fan_speed = _fan_speed(
            _first_present(fan_speed, "ModelFan", "modelFan", "PartFan", "part_fan")
        )
        self.state.big_fan1_speed = _fan_speed(
            _first_present(fan_speed, "AuxiliaryFan", "auxiliaryFan", "AuxFan", "aux_fan")
        )
        self.state.big_fan2_speed = _fan_speed(
            _first_present(fan_speed, "BoxFan", "boxFan", "ChamberFan", "chamber_fan")
        )
        light_status = status.get("LightStatus")
        if light_status is not None:
            self.state.chamber_light = _sdcp_light_enabled(light_status)
        self._emit_status_callbacks(previous_state)
        self._last_state = self.state.state
        self._has_status_sample = True
        return True

    def _is_expected_print_active(self, filename: str) -> bool:
        if self.state.state not in {"RUNNING", "PAUSE"}:
            return False
        expected = Path(filename).name.lower()
        observed_names = [self.state.gcode_file, self.state.current_print, self.state.subtask_name]
        normalized = [Path(str(value)).name.lower() for value in observed_names if value]
        if not normalized:
            return True
        return any(expected == value or expected in value or value in expected for value in normalized)

    def _confirm_print_started(self, filename: str) -> bool:
        deadline = time.monotonic() + SDCP_START_VERIFY_TIMEOUT
        while time.monotonic() < deadline:
            if self.request_status_update() and self._is_expected_print_active(filename):
                return True
            time.sleep(SDCP_START_VERIFY_INTERVAL)
        return False

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        if not self.mainboard_id:
            self.discover()
        bed_levelling = bool(kwargs.get("bed_levelling", True))
        print_platform_type = int(kwargs.get("print_platform_type", 0))
        if print_platform_type not in (0, 1):
            logger.warning(
                "Invalid Elegoo SDCP PrintPlatformType %s; falling back to textured plate", print_platform_type
            )
            print_platform_type = 0
        request_id = secrets.token_hex(16)
        # Match the CC1 WebUI's hardware-captured start command shape. The
        # firmware accepts the older/minimal SDCP command, but can skip the
        # start-time calibration path unless these fields match the WebUI form.
        command = {
            "Id": "",
            "Data": {
                "Cmd": SDCP_START_PRINT_COMMAND,
                "Data": {
                    "Filename": filename,
                    "StartLayer": 0,
                    "Calibration_switch": 1 if bed_levelling else 0,
                    "PrintPlatformType": print_platform_type,
                    "Tlp_Switch": 0,
                },
                "From": 1,
                "MainboardID": "",
                "RequestID": request_id,
                "TimeStamp": int(time.time() * 1000),
            },
        }
        time.sleep(SDCP_START_SETTLE_SECONDS)
        try:
            response = self._send_command(command)
        except TimeoutError:
            logger.warning("Elegoo SDCP start_print ACK timed out for %s; polling status for reconciliation", filename)
            return self._confirm_print_started(filename)
        data = response.get("Data") if isinstance(response.get("Data"), dict) else {}
        response_data = data.get("Data") if isinstance(data.get("Data"), dict) else {}
        ack = response_data.get("Ack")
        if ack != 0:
            logger.warning("Elegoo SDCP start_print rejected for %s: Ack=%s", filename, ack)
            return False
        if not self._confirm_print_started(filename):
            logger.warning("Elegoo SDCP start_print ACKed for %s but printer did not report active print", filename)
            return False
        return True

    def _send_job_control_command(self, command_id: int, action: str) -> bool:
        if not self.mainboard_id:
            self.discover()
        request_id = str(int(time.time() * 1000))
        command = {
            "Id": self.printer_id or "",
            "Topic": f"sdcp/request/{self.mainboard_id}",
            "Data": {
                "Cmd": command_id,
                "Data": {},
                "From": 1,
                "MainboardID": self.mainboard_id,
                "RequestID": request_id,
                "Timestamp": int(time.time()),
            },
        }
        response = self._send_command(command)
        data = response.get("Data") if isinstance(response.get("Data"), dict) else {}
        response_data = data.get("Data") if isinstance(data.get("Data"), dict) else {}
        ack = response_data.get("Ack")
        if ack != 0:
            logger.warning("Elegoo SDCP %s rejected: Ack=%s", action, ack)
            return False
        return True

    def pause_print(self) -> bool:
        return self._send_job_control_command(SDCP_PAUSE_PRINT_COMMAND, "pause_print")

    def resume_print(self) -> bool:
        return self._send_job_control_command(SDCP_RESUME_PRINT_COMMAND, "resume_print")

    def stop_print(self) -> bool:
        return self._send_job_control_command(SDCP_STOP_PRINT_COMMAND, "stop_print")

    def _send_edit_status_data_command(self, payload: dict[str, Any], action: str) -> bool:
        if not self.mainboard_id:
            self.discover()
        request_id = str(int(time.time() * 1000))
        command = {
            "Id": self.printer_id or "",
            "Topic": f"sdcp/request/{self.mainboard_id}",
            "Data": {
                "Cmd": SDCP_EDIT_STATUS_DATA_COMMAND,
                "Data": payload,
                "From": 1,
                "MainboardID": self.mainboard_id,
                "RequestID": request_id,
                "TimeStamp": int(time.time() * 1000),
            },
        }
        response = self._send_command(command)
        data = response.get("Data") if isinstance(response.get("Data"), dict) else {}
        response_data = data.get("Data") if isinstance(data.get("Data"), dict) else {}
        ack = response_data.get("Ack")
        if ack not in (0, None):
            logger.warning("Elegoo SDCP %s rejected: Ack=%s", action, ack)
            return False
        return True

    def set_chamber_light(self, on: bool) -> bool:
        """Turn the Centauri Carbon chamber light on/off via SDCP Cmd 403."""
        success = self._send_edit_status_data_command(
            {
                "LightStatus": {
                    "SecondLight": bool(on),
                    "RgbLight": [0, 0, 0],
                }
            },
            "set_chamber_light",
        )
        if success:
            self.state.chamber_light = bool(on)
        return success

    def set_fan_speed(self, fan: str, speed: int) -> bool:
        """Set Centauri Carbon fan speed via SDCP Cmd 403 TargetFanSpeed."""
        normalized_fan = fan.strip().lower().replace("-", "_")
        fan_field = {
            "part": "ModelFan",
            "model": "ModelFan",
            "model_fan": "ModelFan",
            "cooling": "ModelFan",
            "aux": "AuxiliaryFan",
            "auxiliary": "AuxiliaryFan",
            "auxiliary_fan": "AuxiliaryFan",
            "chamber": "BoxFan",
            "box": "BoxFan",
            "box_fan": "BoxFan",
        }.get(normalized_fan)
        if fan_field is None:
            raise ValueError("Fan must be one of: part, aux, chamber")
        target_speed = max(0, min(100, int(speed)))
        if fan_field == "BoxFan":
            # The CC1 chamber/box fan is exposed by the printer UI as an on/off
            # control. Normalize any non-zero direct API value to fully on.
            target_speed = 100 if target_speed > 0 else 0
        payload = {
            "TargetFanSpeed": {
                "ModelFan": self.state.cooling_fan_speed or 0,
                "AuxiliaryFan": self.state.big_fan1_speed or 0,
                "BoxFan": self.state.big_fan2_speed or 0,
            }
        }
        payload["TargetFanSpeed"][fan_field] = target_speed
        success = self._send_edit_status_data_command(payload, "set_fan_speed")
        if success:
            if fan_field == "ModelFan":
                self.state.cooling_fan_speed = target_speed
            elif fan_field == "AuxiliaryFan":
                self.state.big_fan1_speed = target_speed
            else:
                self.state.big_fan2_speed = target_speed
        return success

    def list_files(self, path: str = "/") -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def upload_file(self, local_path: Path, remote_path: str, *, overwrite: bool = False) -> bool:  # noqa: ARG002
        path = Path(local_path)
        payload = path.read_bytes()
        total_size = len(payload)
        file_md5 = hashlib.md5(payload).hexdigest()
        upload_uuid = secrets.token_hex(32)
        filename = Path(remote_path).name or path.name
        url = f"http://{self.host}:3030/uploadFile/upload"
        result: dict[str, Any] | None = None
        with httpx.Client(timeout=self.timeout) as client:
            for offset in range(0, total_size, SDCP_UPLOAD_CHUNK_SIZE):
                chunk = payload[offset : offset + SDCP_UPLOAD_CHUNK_SIZE]
                response = client.post(
                    url,
                    data={
                        "Uuid": upload_uuid,
                        "Offset": str(offset),
                        "TotalSize": str(total_size),
                        "Check": "1",
                        "S-File-MD5": file_md5,
                    },
                    files={"File": (filename, chunk, "application/octet-stream")},
                )
                response.raise_for_status()
                try:
                    result = response.json()
                except ValueError:
                    result = None
        return bool(result and result.get("success"))

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
