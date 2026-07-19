from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
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
        progress = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= progress <= 1.0:
        progress *= 100.0
    return max(0.0, min(progress, 100.0))


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_prusalink_file_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Map PrusaLink's G-code metadata keys to Printbuddy's canonical fields."""
    if not isinstance(meta, dict) or not meta:
        return {}

    normalized: dict[str, Any] = {"source": "prusalink_file_meta", "raw_prusalink_meta": meta}

    grams = _float_or_none(meta.get("filament used [g]"))
    if grams is not None:
        normalized["filament_used_grams"] = grams

    millimeters = _float_or_none(meta.get("filament used [mm]"))
    if millimeters is not None:
        normalized["filament_used_mm"] = millimeters

    cubic_cm = _float_or_none(meta.get("filament used [cm3]"))
    if cubic_cm is not None:
        normalized["filament_used_cm3"] = cubic_cm

    filament_cost = _float_or_none(meta.get("filament cost"))
    if filament_cost is not None:
        normalized["filament_cost"] = filament_cost

    filament_type = meta.get("filament_type") or meta.get("material_name")
    if filament_type:
        normalized["filament_type"] = str(filament_type)

    estimated_time = _float_or_none(meta.get("estimated_print_time") or meta.get("print_time"))
    if estimated_time is not None:
        normalized["print_time_seconds"] = int(estimated_time)

    per_tool_grams = meta.get("filament used [g] per tool")
    per_tool_types = meta.get("filament_type per tool")
    if isinstance(per_tool_grams, list):
        slots: list[dict[str, Any]] = []
        for idx, raw_grams in enumerate(per_tool_grams):
            tool_grams = _float_or_none(raw_grams)
            if tool_grams is None or tool_grams <= 0:
                continue
            slot: dict[str, Any] = {"slot_id": idx + 1, "used_g": round(tool_grams, 2)}
            if isinstance(per_tool_types, list) and idx < len(per_tool_types) and per_tool_types[idx]:
                slot["type"] = str(per_tool_types[idx])
            slots.append(slot)
        if slots:
            normalized["filament_slots"] = slots

    return normalized


def _job_file_storage_path(file_info: dict[str, Any]) -> tuple[str | None, str | None]:
    """Resolve PrusaLink job file info to a files API storage/path pair."""
    refs = file_info.get("refs") if isinstance(file_info.get("refs"), dict) else {}
    download_ref = refs.get("download")
    if isinstance(download_ref, str) and download_ref.strip("/"):
        parts = download_ref.strip("/").split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]

    path = str(file_info.get("path") or "").strip("/")
    name = str(file_info.get("name") or file_info.get("display_name") or "").strip("/")
    if not name:
        return None, None
    if path:
        parts = path.split("/", 1)
        storage = parts[0]
        directory = parts[1] if len(parts) == 2 else ""
        return storage, f"{directory}/{name}".strip("/")
    return None, name


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
        api_mode: Literal["auto", "modern", "legacy"] = "auto",
        auth_mode: Literal["auto", "digest", "basic_x_api_key", "x_api_key"] = "auto",
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
        self.api_mode = api_mode if api_mode in {"auto", "modern", "legacy"} else "auto"
        self.auth_mode = auth_mode if auth_mode in {"auto", "digest", "basic_x_api_key", "x_api_key"} else "auto"
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
        self._current_print_started_at: float | None = None
        self._file_storage: str | None = None

    @property
    def _basic_auth(self) -> httpx.BasicAuth | None:
        return _prusalink_basic_auth(self.username, self.password)

    @property
    def _digest_auth(self) -> httpx.DigestAuth | None:
        return _prusalink_digest_auth(self.username, self.password)

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.password} if self.password else {}

    def _request_with_auth(
        self,
        request_fn: Any,
        url: str,
        *,
        auth_mode: str | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        mode = auth_mode or self.auth_mode
        if mode == "digest":
            return request_fn(url, auth=self._digest_auth, headers={}, **kwargs)
        if mode == "x_api_key":
            return request_fn(url, auth=None, headers=self._headers, **kwargs)
        if mode == "basic_x_api_key":
            return request_fn(url, auth=self._basic_auth, headers=self._headers, **kwargs)

        response = request_fn(url, auth=self._basic_auth, headers=self._headers, **kwargs)
        authenticate = response.headers.get("www-authenticate", "").lower()
        if response.status_code == 401 and "digest" in authenticate and self._digest_auth is not None:
            response = request_fn(url, auth=self._digest_auth, headers={}, **kwargs)
        return response

    def detect_api_auth_mode(self) -> dict[str, str]:
        """Detect or verify the PrusaLink API/auth mode using safe read-only probes."""
        modern_info = urljoin(self.base_url, "api/v1/info")
        legacy_version = urljoin(self.base_url, "api/version")

        probes: list[tuple[str, str, str]] = []
        if self.api_mode == "modern" and self.auth_mode in {"digest", "basic_x_api_key"}:
            probes = [(modern_info, "modern", self.auth_mode)]
        elif self.api_mode == "legacy" and self.auth_mode == "x_api_key":
            probes = [(legacy_version, "legacy", "x_api_key")]
        else:
            probes = [
                (modern_info, "modern", "digest"),
                (modern_info, "modern", "basic_x_api_key"),
                (legacy_version, "legacy", "x_api_key"),
            ]

        response: httpx.Response | None = None
        for url, api_mode, auth_mode in probes:
            response = self._request_with_auth(httpx.get, url, auth_mode=auth_mode, timeout=self.timeout)
            if response.is_success:
                self.api_mode = api_mode  # type: ignore[assignment]
                self.auth_mode = auth_mode  # type: ignore[assignment]
                return {"prusalink_api_mode": api_mode, "prusalink_auth_mode": auth_mode}

        if response is not None:
            response.raise_for_status()
            raise httpx.HTTPStatusError(
                "PrusaLink authentication auto-detection failed", request=response.request, response=response
            )
        raise httpx.HTTPError("PrusaLink authentication auto-detection failed")

    def _request(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> httpx.Response:
        url = urljoin(self.base_url, path.lstrip("/"))
        request_fn = getattr(httpx, method.lower())
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if json_payload is not None:
            kwargs["json"] = json_payload
        return self._request_with_auth(request_fn, url, **kwargs)

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

    def _storage_key(self, storage: dict[str, Any]) -> str | None:
        raw_key = str(storage.get("path") or storage.get("name") or storage.get("type") or "").strip().strip("/")
        if not raw_key:
            return None
        return raw_key.split("/", 1)[0].lower()

    def _available_storage_key(self, storage: dict[str, Any]) -> str | None:
        if storage.get("available") is False or storage.get("read_only") is True:
            return None
        return self._storage_key(storage)

    def list_storages(self) -> list[dict[str, Any]]:
        """Return PrusaLink storage devices normalized for Printbuddy's File Manager."""
        data = self._get("api/v1/storage")
        storages = data.get("storage_list") or data.get("storages") or data.get("storage") or []
        if isinstance(storages, dict):
            storages = [storages]

        normalized: list[dict[str, Any]] = []
        for item in storages if isinstance(storages, list) else []:
            if not isinstance(item, dict):
                continue
            key = self._storage_key(item)
            if not key:
                continue
            storage_type = str(item.get("type") or key).upper()
            normalized.append(
                {
                    "id": key,
                    "type": storage_type,
                    "name": item.get("name") or storage_type,
                    "path": item.get("path") or f"/{key}",
                    "available": item.get("available") is not False,
                    "read_only": bool(item.get("read_only", False)),
                    "used_bytes": item.get("used_space") or item.get("used_bytes"),
                    "free_bytes": item.get("free_space") or item.get("free_bytes"),
                }
            )
        return normalized

    @property
    def file_storage(self) -> str:
        """Return the PrusaLink storage key used for default file operations.

        Older PrusaLink examples used ``local``, but CORE One exposes printable
        files on a USB storage namespace. Discover storage first and prefer the
        available USB namespace.
        """
        if self._file_storage:
            return self._file_storage
        try:
            storages = self.list_storages()
        except Exception as exc:  # noqa: BLE001 - storage discovery is optional on older firmware/mock servers
            logger.debug("PrusaLink storage discovery failed; falling back to USB storage: %s", type(exc).__name__)
            self._file_storage = "usb"
            return self._file_storage

        candidates = [item["id"] for item in storages if item.get("available") and not item.get("read_only")]
        preferred = next((candidate for candidate in candidates if candidate.lower() == "usb"), None)
        self._file_storage = preferred or (candidates[0] if candidates else "usb")
        return self._file_storage

    def _file_api_path(self, remote_path: str, *, suffix: str = "", storage: str | None = None) -> str:
        normalized = remote_path.strip("/")
        storage_key = (storage or self.file_storage).strip("/").lower()
        if normalized == storage_key:
            normalized = ""
        elif normalized.startswith(f"{storage_key}/"):
            normalized = normalized[len(storage_key) + 1 :]
        quoted_path = quote(normalized, safe="/")
        base = f"api/v1/files/{quote(storage_key, safe='')}"
        if quoted_path:
            base += f"/{quoted_path}"
        return base + suffix

    def list_files(self, path: str = "/", *, storage: str | None = None) -> list[dict[str, Any]]:
        api_path = self._file_api_path(path, storage=storage)
        normalized = path.strip("/")
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

    def upload_file(
        self, local_path: Path, remote_path: str, *, overwrite: bool = False, storage: str | None = None
    ) -> bool:  # noqa: ARG002
        normalized = remote_path.strip("/") or local_path.name
        url = urljoin(self.base_url, self._file_api_path(normalized, storage=storage))
        with open(local_path, "rb") as fh:
            kwargs: dict[str, Any] = {
                "timeout": max(self.timeout, 60.0),
                "content": fh.read(),
            }
            mode = self.auth_mode if self.auth_mode != "auto" else "basic_x_api_key"
            headers = {} if mode == "digest" else self._headers
            auth = self._digest_auth if mode == "digest" else None if mode == "x_api_key" else self._basic_auth
            response = httpx.put(
                url,
                auth=auth,
                headers={**headers, "Content-Type": "application/octet-stream"},
                **kwargs,
            )
        authenticate = response.headers.get("www-authenticate", "").lower()
        if (
            self.auth_mode == "auto"
            and response.status_code == 401
            and "digest" in authenticate
            and self._digest_auth is not None
        ):
            with open(local_path, "rb") as fh:
                kwargs["content"] = fh.read()
                response = httpx.put(
                    url,
                    auth=self._digest_auth,
                    headers={"Content-Type": "application/octet-stream"},
                    **kwargs,
                )
        response.raise_for_status()
        return True

    def download_file(self, remote_path: str, *, storage: str | None = None) -> bytes | None:
        normalized = remote_path.strip("/")
        url = urljoin(self.base_url, self._file_api_path(normalized, suffix="/raw", storage=storage))
        response = httpx.get(url, auth=self._basic_auth, headers=self._headers, timeout=max(self.timeout, 60.0))
        authenticate = response.headers.get("www-authenticate", "").lower()
        if response.status_code == 401 and "digest" in authenticate and self._digest_auth is not None:
            response = httpx.get(url, auth=self._digest_auth, headers=self._headers, timeout=max(self.timeout, 60.0))
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    def delete_file(self, remote_path: str, *, storage: str | None = None) -> bool:
        normalized = remote_path.strip("/")
        return self._delete(self._file_api_path(normalized, storage=storage))

    def connect(self) -> None:
        if self.api_mode == "legacy":
            info = self._get("api/version")
            self.state.connected = True
            self.state.raw_data = info
            self.state.raw_status = info
            self.request_status_update()
            return

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
        payload = {
            "filename": filename,
            "subtask_name": filename,
            "progress": self.state.progress,
            "remaining_time": self.state.remaining_time * 60 if self.state.remaining_time else None,
            "status": self.state.state,
        }
        file_metadata = self.state.raw_data.get("file_metadata") if isinstance(self.state.raw_data, dict) else None
        if file_metadata:
            payload["file_metadata"] = file_metadata
        return payload

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
            self._current_print_started_at = time.monotonic()
            if self.on_print_start:
                self.on_print_start(self._build_lifecycle_payload())
        elif previous_running and not current_running:
            payload = self._build_lifecycle_payload()
            if self._current_print_started_at is not None:
                payload["actual_time_seconds"] = max(1, int(time.monotonic() - self._current_print_started_at))
                self._current_print_started_at = None
            if current_state == "FAILED":
                payload["status"] = "failed"
            elif current_state == "FINISH":
                payload["status"] = "completed"
            elif current_state == "IDLE":
                payload["status"] = "completed" if self.state.progress >= 99 else "stopped"
            else:
                payload["status"] = "stopped"
            if self.on_print_complete:
                self.on_print_complete(payload)

    def request_status_update(self) -> bool:
        previous_state = self._last_state if self._has_status_sample else None
        if self.api_mode == "legacy":
            job_detail = self._get("api/job")
            self.state.connected = True
            self.state.raw_status = job_detail
            self.state.raw_data = {**self.state.raw_data, **job_detail}
            state = job_detail.get("state") or job_detail.get("status") or "IDLE"
            self.state.state = _map_prusalink_state(state)
            if job_detail:
                self._apply_job_detail(job_detail)
            self._emit_status_callbacks(previous_state)
            self._last_state = self.state.state
            self._has_status_sample = True
            return True

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
        normalized_meta = _normalize_prusalink_file_meta(file_info.get("meta"))
        if normalized_meta:
            self._store_file_metadata(normalized_meta)

    def _store_file_metadata(self, metadata: dict[str, Any]) -> None:
        self.state.raw_data["file_metadata"] = metadata
        self.state.raw_data["prusalink_file_meta"] = metadata.get("raw_prusalink_meta")

    def _refresh_metadata_from_job_file(self, file_info: dict[str, Any]) -> dict[str, Any]:
        storage, remote_path = _job_file_storage_path(file_info)
        if not remote_path:
            return {}
        try:
            file_detail = self._get(self._file_api_path(remote_path, storage=storage))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            return {}
        if not isinstance(file_detail, dict):
            return {}
        metadata = _normalize_prusalink_file_meta(file_detail.get("meta"))
        if metadata:
            self._store_file_metadata(metadata)
            logger.info("PrusaLink file metadata loaded from file endpoint: storage=%s path=%s", storage, remote_path)
        return metadata

    def refresh_current_file_metadata(self) -> dict[str, Any]:
        """Fetch current job metadata without emitting lifecycle callbacks.

        PrusaLink sometimes exposes ``job.file.meta`` a little later than the
        RUNNING transition that triggers Printbuddy's archive creation. This
        method lets archive/usage code ask for one fresh job-detail sample
        without calling ``request_status_update()``, which would risk duplicate
        print-start/complete callbacks.
        """
        if self.api_mode == "legacy":
            return {}
        try:
            job_detail = self._get("api/v1/job")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 204:
                raise
            return {}
        if not isinstance(job_detail, dict) or not job_detail:
            return {}
        self._apply_job_detail(job_detail)
        metadata = self.state.raw_data.get("file_metadata") if isinstance(self.state.raw_data, dict) else None
        if isinstance(metadata, dict) and metadata:
            return metadata
        file_info = job_detail.get("file") if isinstance(job_detail.get("file"), dict) else {}
        return self._refresh_metadata_from_job_file(file_info)

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
        response = self._request("post", self._file_api_path(normalized, storage=kwargs.get("storage")))
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
    api_mode = "auto"
    auth_mode = "auto"
    options_raw = getattr(printer, "provider_options", None)
    if options_raw:
        try:
            options = json.loads(options_raw) if isinstance(options_raw, str) else options_raw
            if isinstance(options, dict):
                if str(options.get("username") or "").strip():
                    username = str(options["username"]).strip()
                if str(options.get("prusalink_api_mode") or "").strip():
                    api_mode = str(options["prusalink_api_mode"]).strip()
                if str(options.get("prusalink_auth_mode") or "").strip():
                    auth_mode = str(options["prusalink_auth_mode"]).strip()
        except (TypeError, ValueError):
            pass
    return PrusaLinkPrinterClient(
        base_url=base_url,
        username=username,
        password=getattr(printer, "auth_token", None),
        api_mode=api_mode,  # type: ignore[arg-type]
        auth_mode=auth_mode,  # type: ignore[arg-type]
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
