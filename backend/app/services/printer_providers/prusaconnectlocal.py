"""Prusa Connect Local provider.

Prusa Connect Local is a self-hosted server that puts every Prusa printer on
the network behind one HTTP API (``/api/v1``). Printers dial into the server;
Printbuddy never talks to the machines directly. One Printbuddy printer row
maps to one Prusa Connect Local *device*:

* ``ip_address`` / ``api_url`` – the Prusa Connect Local server (default port 8080)
* ``auth_token`` – an API credential issued by the server (sent as bearer token)
* ``provider_options`` – JSON ``{"pcl_device_id": "<device id>"}``

Commands are sent through ``POST /api/v1/devices/{id}/commands`` using the
``core.command.*`` verbs the server resolved for the device.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from backend.app.services.printer_providers.prusalink import (
    PrusaLinkPrinterClient,
    _map_prusalink_state,
    _minutes_from_seconds,
)

logger = logging.getLogger(__name__)

PRUSA_CONNECT_LOCAL_DEFAULT_PORT = 8080
PRUSA_CONNECT_LOCAL_DEVICE_OPTION = "pcl_device_id"
CHAMBER_LED_VERB = "core.command.set_chamber_led_intensity"
CHAMBER_LED_ARGUMENT = "chamber.led_intensity"
_DEVICE_PAGE_SIZE = 100
_MAX_DEVICE_PAGES = 50


class PrusaConnectLocalError(Exception):
    """Raised when the Prusa Connect Local server refuses a request."""

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def build_prusa_connect_local_base_url(host: str | None, api_url: str | None = None) -> str:
    """Return the server base URL (``http://host:8080/``) from an api_url or host."""
    raw = (api_url or "").strip()
    if not raw:
        raw = (host or "").strip()
        if not raw:
            raise ValueError("Prusa Connect Local host is required")
        if not raw.startswith(("http://", "https://")):
            host_part = raw.split("/", 1)[0]
            # Append the default port unless one is already given (IPv4 / hostname form).
            if ":" not in host_part:
                raw = f"http://{host_part}:{PRUSA_CONNECT_LOCAL_DEFAULT_PORT}"
            else:
                raw = f"http://{host_part}"
    elif not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    return raw.rstrip("/") + "/"


def _auth_headers(api_key: str | None) -> dict[str, str]:
    token = (api_key or "").strip()
    if not token:
        return {}
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {"Authorization": token, "Accept": "application/json"}


def _raise_for_problem(response: httpx.Response) -> None:
    """Raise a PrusaConnectLocalError carrying the RFC 9457 ``code`` on failure."""
    if response.status_code < 400:
        return
    code = None
    detail = None
    try:
        problem = response.json()
        if isinstance(problem, dict):
            code = problem.get("code")
            detail = problem.get("detail") or problem.get("title")
    except ValueError:
        pass
    message = f"Prusa Connect Local answered HTTP {response.status_code}"
    if code:
        message += f" ({code})"
    if detail:
        message += f": {detail}"
    raise PrusaConnectLocalError(message, status_code=response.status_code, code=code)


def summarize_prusa_connect_local_device(device: dict[str, Any]) -> dict[str, Any]:
    """Reduce a Prusa Connect Local device record to what the add-printer UI needs."""
    state_tree = device.get("state") if isinstance(device.get("state"), dict) else {}
    raw_state = state_tree.get("/state")
    job = device.get("job") if isinstance(device.get("job"), dict) else {}
    if not raw_state and job.get("running"):
        raw_state = job.get("state")
    serial = str(device.get("serial") or device.get("unit_uid") or "").strip()
    return {
        "id": str(device.get("id") or ""),
        "name": str(device.get("name") or "").strip() or None,
        "vendor": str(device.get("vendor") or "").strip() or None,
        "model": str(device.get("model") or "").strip() or None,
        "serial": serial or None,
        "firmware": str(device.get("firmware") or "").strip() or None,
        "driver": device.get("driver"),
        "connected": bool(device.get("connected")),
        "state": str(raw_state) if raw_state else None,
        "retired": bool(device.get("retired")),
        "can_operate": "operate" in (device.get("actions") or []),
    }


def prusa_connect_local_serial(device_id: str, serial: str | None = None) -> str:
    """Printbuddy serial_number for a Prusa Connect Local device (unique per device)."""
    raw = (serial or device_id or "device").strip().upper()
    normalized = "".join(ch if ch.isalnum() else "-" for ch in raw).strip("-") or "DEVICE"
    return f"PCL-{normalized}"[:50]


def list_prusa_connect_local_devices(
    base_url: str,
    api_key: str | None,
    *,
    timeout: float = 10.0,
    include_retired: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    """Walk every page of ``GET /api/v1/devices`` and return the raw device records."""
    headers = _auth_headers(api_key)
    devices: list[dict[str, Any]] = []
    offset = 0
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport) as client:
        for _ in range(_MAX_DEVICE_PAGES):
            response = client.get("api/v1/devices", params={"limit": _DEVICE_PAGE_SIZE, "offset": offset})
            _raise_for_problem(response)
            page = response.json()
            items = page.get("items") if isinstance(page, dict) else None
            if not isinstance(items, list) or not items:
                break
            devices.extend(item for item in items if isinstance(item, dict))
            offset += len(items)
            total = page.get("total")
            if not isinstance(total, int) or offset >= total:
                break
    if not include_retired:
        devices = [device for device in devices if not device.get("retired")]
    return devices


def list_prusa_connect_local_cameras(
    base_url: str,
    api_key: str | None,
    *,
    device_id: str | None = None,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    """``GET /api/v1/cameras``, optionally narrowed to one device, reduced to what Printbuddy uses."""
    params = {"device": device_id} if device_id else None
    with httpx.Client(
        base_url=base_url, headers=_auth_headers(api_key), timeout=timeout, transport=transport
    ) as client:
        response = client.get("api/v1/cameras", params=params)
        _raise_for_problem(response)
        payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    return [
        {
            "name": str(item.get("name") or ""),
            "device_id": str(item.get("device_id") or ""),
            "serving": bool(item.get("serving")),
            "stream": bool(item.get("stream")),
            "snapshot": bool(item.get("snapshot")),
            "watch": bool(item.get("watch")),
        }
        for item in items or []
        if isinstance(item, dict) and item.get("name")
    ]


def pick_prusa_connect_local_camera(cameras: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The camera Printbuddy should show: one it can read (MJPEG stream or JPEG stills).

    WebRTC-only (H.264) cameras are skipped because Printbuddy's camera pipeline
    consumes MJPEG and JPEG. Serving cameras and ones with a stream win.
    """
    usable = [camera for camera in cameras if camera.get("stream") or camera.get("snapshot")]
    if not usable:
        return None
    return sorted(usable, key=lambda camera: (not camera.get("serving"), not camera.get("stream"), camera["name"]))[0]


def prusa_connect_local_camera_options(camera: dict[str, Any] | None) -> dict[str, Any]:
    """provider_options entries describing the picked camera (all None when there is none)."""
    if not camera:
        return {"pcl_camera": None, "pcl_camera_stream": None, "pcl_camera_snapshot": None}
    return {
        "pcl_camera": camera["name"],
        "pcl_camera_stream": bool(camera.get("stream")),
        "pcl_camera_snapshot": bool(camera.get("snapshot")),
    }


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _progress_percent(value: Any) -> float:
    # Prusa Connect Local always reports progress as 0..100.
    return max(0.0, min(_as_float(value), 100.0))


def _format_arg(value: int | float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _command_arg(value: Any) -> str:
    """Render one command argument the way Prusa Connect Local parses it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_arg(value)
    return str(value)


# Verbs the manual-controls panel may send. Print, file and transfer verbs have
# their own routes; firmware, token and raw G-code verbs stay out of the panel.
PRUSA_CONNECT_LOCAL_CONTROL_VERBS = frozenset(
    {
        "move",
        "move_z",
        "move_e",
        "home",
        "disable_steppers",
        "reset_printer",
        "set_printer_ready",
        "cancel_printer_ready",
        "set_idle",
        "mesh_bed_leveling",
        "beep",
        "set_hostname",
        "set_nozzle_temperature",
        "set_bed_temperature",
        "set_speed",
        "set_flow",
        "set_chamber_fan_target",
        "set_chamber_led_intensity",
        "set_chamber_target_temp",
        "set_tool_nozzle_diameter",
        "set_tool_high_flow",
        "set_tool_hardened",
        "set_addon_power",
        "load_filament",
        "unload_filament",
    }
)


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def summarize_prusa_connect_local_controls(device: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    """Shape a device record plus its capability set for the manual-controls panel."""
    state_tree = device.get("state") if isinstance(device.get("state"), dict) else {}
    verbs: dict[str, list[dict[str, Any]]] = {}
    for capability in capabilities.get("capabilities") or []:
        key = str(capability.get("key") or "") if isinstance(capability, dict) else ""
        if not key.startswith("core.command."):
            continue
        short = key.removeprefix("core.command.")
        if short in PRUSA_CONNECT_LOCAL_CONTROL_VERBS:
            verbs[short] = [
                {
                    field: argument[field]
                    for field in ("name", "type", "required", "minimum", "maximum", "enum", "unit", "max_length")
                    if field in argument
                }
                for argument in capability.get("arguments") or []
                if isinstance(argument, dict)
            ]

    tools_block = device.get("tools") if isinstance(device.get("tools"), dict) else {}
    tool_map = tools_block.get("tools") if isinstance(tools_block.get("tools"), dict) else {}
    tools = []
    for index, tool in sorted(tool_map.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 0):
        if not isinstance(tool, dict):
            continue
        features = tool.get("features") if isinstance(tool.get("features"), dict) else {}
        package = tool.get("material_package_instance") or {}
        material = (
            ((package.get("package") or {}).get("material") or {}).get("abbreviation")
            if isinstance(package, dict)
            else None
        )
        tools.append(
            {
                "index": int(index) if str(index).isdigit() else len(tools),
                "active": bool(tool.get("active")),
                "nozzle_diameter": _optional_float(features.get("nozzle_diameter")),
                "high_flow": features.get("nozzle_high_flow"),
                "hardened": features.get("nozzle_hardened"),
                "material": material,
                "nozzle_temp": _optional_float(state_tree.get(f"/tools/{index}/nozzle_temp", tool.get("nozzle_temp"))),
                "nozzle_target_temp": _optional_float(
                    state_tree.get(f"/tools/{index}/nozzle_target_temp", tool.get("nozzle_target_temp"))
                ),
            }
        )

    active_tool = next((tool for tool in tools if tool["active"]), tools[0] if tools else {})
    return {
        "device_id": device.get("id"),
        "connected": bool(device.get("connected")),
        "can_operate": "operate" in (device.get("actions") or []),
        "state": state_tree.get("/state"),
        "verbs": verbs,
        "position": {axis: _optional_float(state_tree.get(f"/axis/{axis}")) for axis in ("x", "y", "z")},
        "speed": _optional_float(state_tree.get("/speed")),
        "flow": _optional_float(state_tree.get("/flow")),
        "temperatures": {
            "nozzle": active_tool.get("nozzle_temp"),
            "nozzle_target": active_tool.get("nozzle_target_temp"),
            "bed": _optional_float(state_tree.get("/temperature/bed")),
            "bed_target": _optional_float(state_tree.get("/temperature/bed_target")),
            "chamber": _optional_float(state_tree.get("/temperature/chamber")),
            "chamber_target": _optional_float(state_tree.get("/temperature/chamber_target")),
        },
        "hostname": state_tree.get("/network/hostname"),
        "tools": tools,
    }


class PrusaConnectLocalPrinterClient(PrusaLinkPrinterClient):
    """One Prusa Connect Local device, exposed through Printbuddy's provider contract.

    Inherits the PrusaLink state object and lifecycle callback handling (print
    start/complete detection) and replaces every network call with the Prusa
    Connect Local API.
    """

    def __init__(
        self,
        base_url: str,
        *,
        device_id: str | None,
        api_key: str | None,
        timeout: float = 10.0,
        **callbacks: Any,
    ) -> None:
        super().__init__(base_url, username=None, password=api_key, timeout=timeout, **callbacks)
        self.api_key = (api_key or "").strip() or None
        self.device_id = (device_id or "").strip() or None
        self._capabilities: set[str] = set()

    # ------------------------------------------------------------------ HTTP

    @property
    def _headers(self) -> dict[str, str]:  # type: ignore[override]
        return _auth_headers(self.api_key)

    def _device_path(self, suffix: str = "") -> str:
        if not self.device_id:
            raise PrusaConnectLocalError("No Prusa Connect Local device selected for this printer")
        return f"api/v1/devices/{quote(self.device_id, safe='')}{suffix}"

    def _http(self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        response = httpx.request(
            method.upper(),
            self.base_url + path.lstrip("/"),
            headers=headers,
            timeout=timeout or self.timeout,
            **kwargs,
        )
        _raise_for_problem(response)
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self._http(method, path, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {}

    def send_command(self, verb: str, args: dict[str, Any] | None = None) -> bool:
        """Send one ``core.command.*`` verb; returns whether the printer accepted it."""
        full_verb = verb if "." in verb else f"core.command.{verb}"
        payload: dict[str, Any] = {"verb": full_verb, "key": uuid.uuid4().hex}
        if args:
            payload["args"] = {key: _command_arg(value) for key, value in args.items()}
        result = self._json("post", self._device_path("/commands"), json=payload, timeout=max(self.timeout, 30.0))
        ok = bool(result.get("ok", True))
        if not ok:
            logger.info("Prusa Connect Local refused %s for device %s: %s", full_verb, self.device_id, result)
        elif full_verb == CHAMBER_LED_VERB and args:
            # The device does not report the LED level back, so the last accepted
            # value is the best state Printbuddy has.
            self.state.chamber_light = _as_float(args.get(CHAMBER_LED_ARGUMENT)) > 0
        return ok

    def get_control_snapshot(self) -> dict[str, Any]:
        """Current device values plus the control verbs this device resolved to."""
        device = self._json("get", self._device_path())
        capabilities = self._json("get", self._device_path("/capabilities"))
        return summarize_prusa_connect_local_controls(device, capabilities)

    # ------------------------------------------------------------ lifecycle

    def detect_api_auth_mode(self) -> dict[str, str]:  # pragma: no cover - not used for this provider
        return {}

    def connect(self) -> None:
        if not self.device_id:
            # Probe-only mode (credential check without a selected device).
            self._json("get", "api/v1/devices", params={"limit": 1})
            self.state.connected = True
            return
        self.request_status_update()

    def request_status_update(self) -> bool:
        previous_state = self._last_state if self._has_status_sample else None
        device = self._json("get", self._device_path())
        self._apply_device(device)
        self._emit_status_callbacks(previous_state)
        self._last_state = self.state.state
        self._has_status_sample = True
        return True

    def _apply_device(self, device: dict[str, Any]) -> None:
        state_tree: dict[str, Any] = device.get("state") if isinstance(device.get("state"), dict) else {}
        job: dict[str, Any] = device.get("job") if isinstance(device.get("job"), dict) else {}
        connected = bool(device.get("connected"))

        self.state.connected = connected
        self.state.raw_status = device
        self.state.raw_data = {**self.state.raw_data, "prusa_connect_local_device": device}
        self.state.firmware_version = str(device.get("firmware") or "") or None
        self._capabilities = {str(cap) for cap in device.get("capabilities") or []}
        self.state.raw_data["chamber_light_supported"] = CHAMBER_LED_VERB in self._capabilities

        if not connected:
            self.state.state = "OFFLINE"
        else:
            raw_state = state_tree.get("/state") or (job.get("state") if job.get("running") else None) or "IDLE"
            self.state.state = _map_prusalink_state(raw_state)

        # Temperatures: bed lives at /temperature/*, nozzles under the tool tree.
        tools = device.get("tools") if isinstance(device.get("tools"), dict) else {}
        tool_map = tools.get("tools") if isinstance(tools.get("tools"), dict) else {}
        active_tool = next(
            (tool for tool in tool_map.values() if isinstance(tool, dict) and tool.get("active")),
            next((tool for tool in tool_map.values() if isinstance(tool, dict)), {}),
        )
        nozzle = _as_float(state_tree.get("/tools/0/nozzle_temp", active_tool.get("nozzle_temp")))
        nozzle_target = _as_float(state_tree.get("/tools/0/nozzle_target_temp", active_tool.get("nozzle_target_temp")))
        bed = _as_float(state_tree.get("/temperature/bed"))
        bed_target = _as_float(state_tree.get("/temperature/bed_target"))
        self.state.temperatures = {
            "nozzle": nozzle,
            "nozzle_target": nozzle_target,
            "nozzle_heating": nozzle_target - nozzle > 1.0,
            "bed": bed,
            "bed_target": bed_target,
            "bed_heating": bed_target - bed > 1.0,
        }
        chamber = state_tree.get("/temperature/chamber")
        if chamber is not None:
            self.state.temperatures["chamber"] = _as_float(chamber)

        speed = state_tree.get("/speed")
        if isinstance(speed, (int, float)):
            self.state.raw_data["speed_percent"] = speed

        # Job
        device_job_id = job.get("device_job_id") or state_tree.get("/job/id")
        try:
            self._job_id = int(device_job_id) if device_job_id is not None else None
        except (TypeError, ValueError):
            self._job_id = None
        filename = job.get("display_name") or job.get("path") or state_tree.get("/job/path")
        if filename:
            name = str(filename).rsplit("/", 1)[-1] if not job.get("display_name") else str(filename)
            self.state.gcode_file = str(job.get("path") or filename)
            self.state.current_print = name
            self.state.subtask_name = name
        progress = job.get("progress", state_tree.get("/job/progress"))
        if progress is not None and (job.get("running") or self.state.state in {"RUNNING", "PAUSE", "PREPARE"}):
            self.state.progress = _progress_percent(progress)
        elif self.state.state == "FINISH":
            self.state.progress = 100.0
        remaining_ms = job.get("time_remaining_ms")
        if isinstance(remaining_ms, (int, float)):
            self.state.remaining_time = _minutes_from_seconds(remaining_ms / 1000)
        elif state_tree.get("/job/time_remaining") is not None:
            self.state.remaining_time = _minutes_from_seconds(state_tree.get("/job/time_remaining"))

    # --------------------------------------------------------------- control

    def stop_print(self) -> bool:
        return self.send_command("stop_print")

    def pause_print(self) -> bool:
        return self.send_command("pause_print")

    def resume_print(self) -> bool:
        return self.send_command("resume_print")

    def set_nozzle_temperature(self, target: int | float) -> bool:
        return self.send_command("set_nozzle_temperature", {"nozzle_temperature": _format_arg(target)})

    def set_bed_temperature(self, target: int | float) -> bool:
        return self.send_command("set_bed_temperature", {"bed_temperature": _format_arg(target)})

    def set_chamber_light(self, on: bool) -> bool:
        """Chamber LED fully on (100 %) or off (0 %)."""
        return self.send_command(CHAMBER_LED_VERB, {CHAMBER_LED_ARGUMENT: 100 if on else 0})

    def send_gcode(self, script: str) -> bool:
        lines = [line.strip() for line in script.splitlines() if line.strip() and not line.strip().startswith(";")]
        if not lines:
            return False
        try:
            result = self._json(
                "post", self._device_path("/gcode"), json={"lines": lines}, timeout=max(self.timeout, 60.0)
            )
        except PrusaConnectLocalError as exc:
            if exc.status_code != 403:
                raise
            # Raw gcode needs the send_gcode grant; operators only hold the
            # capability-checked core.command.send_gcode verb.
            return all(self.send_command("send_gcode", {"gcode": line}) for line in lines)
        if result.get("stopped"):
            return False
        steps = result.get("steps") if isinstance(result.get("steps"), list) else []
        return all(isinstance(step, dict) and step.get("status") == "accepted" for step in steps)

    # ----------------------------------------------------------------- files

    def list_storages(self) -> list[dict[str, Any]]:
        data = self._json("get", self._device_path("/storages"))
        normalized: list[dict[str, Any]] = []
        for item in data.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("name") or item.get("mountpoint") or "").strip().strip("/").lower()
            if not key:
                continue
            storage_type = str(item.get("type") or key).upper()
            normalized.append(
                {
                    "id": key,
                    "type": storage_type,
                    "name": storage_type,
                    "path": item.get("mountpoint") or f"/{key}",
                    "available": True,
                    "read_only": bool(item.get("read_only", False)),
                    "used_bytes": None,
                    "free_bytes": item.get("free_space"),
                }
            )
        return normalized

    def _device_file_path(self, remote_path: str, storage: str | None = None) -> str:
        normalized = remote_path.strip().strip("/")
        storage_key = (storage or self.file_storage).strip("/").lower()
        if normalized == storage_key or normalized.startswith(f"{storage_key}/"):
            return normalized
        return f"{storage_key}/{normalized}" if normalized else storage_key

    def list_files(self, path: str = "/", *, storage: str | None = None) -> list[dict[str, Any]]:
        device_path = self._device_file_path(path, storage)
        storage_key = (storage or self.file_storage).strip("/").lower()
        data = self._json("get", self._device_path("/files"), params={"path": device_path})
        files: list[dict[str, Any]] = []
        for item in data.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_path = str(item.get("path") or "").strip("/")
            name = str(item.get("display_name") or item.get("name") or item_path.rsplit("/", 1)[-1]).strip()
            if not name:
                continue
            # Printbuddy file paths are relative to the storage, like PrusaLink's.
            relative = item_path[len(storage_key) + 1 :] if item_path.startswith(f"{storage_key}/") else item_path
            files.append(
                {
                    "name": name,
                    "type": "directory" if item.get("folder") else "file",
                    "size": item.get("size"),
                    "modified": item.get("modified"),
                    "path": f"/{relative}",
                }
            )
        return files

    def delete_file(self, remote_path: str, *, storage: str | None = None) -> bool:
        self._http("delete", self._device_path("/files"), params={"path": self._device_file_path(remote_path, storage)})
        return True

    def download_file(self, remote_path: str, *, storage: str | None = None) -> bytes | None:  # noqa: ARG002
        # Prusa Connect Local exposes no route that reads a file back off a printer.
        return None

    def _writable_server_storage(self, filename: str) -> str:
        data = self._json("get", "api/v1/storages")
        suffix = Path(filename).suffix.lower()
        for item in data.get("items") or []:
            if not isinstance(item, dict) or not item.get("write"):
                continue
            allowed = [str(ext).lower() for ext in item.get("allowed_extensions") or []]
            if not allowed or suffix in allowed:
                return str(item.get("name"))
        raise PrusaConnectLocalError(
            "Prusa Connect Local has no writable storage that accepts this file type; "
            "declare a storage resource on the server to upload files"
        )

    def upload_file(
        self, local_path: Path, remote_path: str, *, overwrite: bool = False, storage: str | None = None
    ) -> bool:
        """Relay a file through one of the server's storages onto the printer."""
        normalized = remote_path.strip("/") or local_path.name
        filename = normalized.rsplit("/", 1)[-1]
        server_storage = self._writable_server_storage(filename)
        with open(local_path, "rb") as fh:
            stored = self._json(
                "put",
                f"api/v1/storages/{quote(server_storage, safe='')}/content",
                params={"path": filename, "temporary": "true"},
                content=fh,
                headers={"Content-Type": "application/octet-stream"},
                timeout=max(self.timeout, 300.0),
            )
        source = str(stored.get("path") or filename)
        self._json(
            "post",
            self._device_path("/files"),
            json={
                "storage": server_storage,
                "source": source,
                "path": self._device_file_path(normalized, storage),
                "replace": bool(overwrite),
            },
            timeout=max(self.timeout, 600.0),
        )
        return True

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        device_path = self._device_file_path(filename, kwargs.get("storage"))
        result = self._json("post", self._device_path("/print"), json={"path": device_path}, timeout=60.0)
        command = result.get("command") if isinstance(result.get("command"), dict) else {}
        return bool(command.get("ok", True))

    # ------------------------------------------------------------- extras

    def has_capability(self, verb: str) -> bool:
        full_verb = verb if "." in verb else f"core.command.{verb}"
        return not self._capabilities or full_verb in self._capabilities

    def home_axes(self, axes: str = "") -> bool:
        axis = re.sub(r"[^XYZ]", "", axes.upper())
        return self.send_command("home", {"axis": axis} if axis else None)


def _device_id_from_options(options_raw: Any) -> str | None:
    if not options_raw:
        return None
    try:
        options = json.loads(options_raw) if isinstance(options_raw, str) else options_raw
    except (TypeError, ValueError):
        return None
    if isinstance(options, dict):
        value = str(options.get(PRUSA_CONNECT_LOCAL_DEVICE_OPTION) or "").strip()
        return value or None
    return None


def create_prusa_connect_local_client(printer: Any, **callbacks: Any) -> PrusaConnectLocalPrinterClient:
    base_url = build_prusa_connect_local_base_url(
        getattr(printer, "ip_address", None), getattr(printer, "api_url", None)
    )
    return PrusaConnectLocalPrinterClient(
        base_url,
        device_id=_device_id_from_options(getattr(printer, "provider_options", None)),
        api_key=getattr(printer, "auth_token", None),
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
