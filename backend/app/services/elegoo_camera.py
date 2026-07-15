"""Elegoo SDCP camera helpers.

Centauri Carbon exposes its LAN camera as an MJPEG stream on port 3031.
Keep this separate from the SDCP WebSocket/status client: camera streaming is
HTTP/MJPEG and should reuse Printbuddy's existing external-camera pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ELEGOO_SDCP_PROVIDER = "elegoo_sdcp"
ELEGOO_SDCP_CAMERA_PORT = 3031
ELEGOO_SDCP_CAMERA_PATH = "/video"
ELEGOO_SDCP_CAMERA_TYPE = "mjpeg"
ELEGOO_SDCP_WS_PORT = 3030
ELEGOO_SDCP_DISCOVERY_PORT = 3000
ELEGOO_SDCP_DISCOVERY_MESSAGE = b"M99999"
ELEGOO_SDCP_STATUS_COMMAND = 0


@dataclass(frozen=True)
class ElegooCameraActivationInfo:
    printer_id: str | None = None
    mainboard_id: str | None = None


@dataclass(frozen=True)
class EffectiveCameraSource:
    enabled: bool
    url: str | None
    camera_type: str | None
    snapshot_url: str | None = None
    derived: bool = False


def is_elegoo_sdcp_provider(provider: object) -> bool:
    return str(provider or "").strip().lower() == ELEGOO_SDCP_PROVIDER


def is_elegoo_sdcp_camera_source(provider: object, camera_url: object) -> bool:
    """Return True when a camera URL should use CC1 SDCP activation.

    Existing printers may have the validated ``http://<ip>:3031/video`` URL
    persisted as a manual external camera. Manual config is not marked as
    ``derived``, but the Centauri Carbon endpoint still requires the SDCP
    WebSocket activation session before JPEG frames are produced.
    """
    if not is_elegoo_sdcp_provider(provider):
        return False
    raw = str(camera_url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.port == ELEGOO_SDCP_CAMERA_PORT
        and parsed.path.rstrip("/") == ELEGOO_SDCP_CAMERA_PATH
    )


def build_elegoo_sdcp_camera_url(ip_address: object) -> str | None:
    host = str(ip_address or "").strip()
    if not host:
        return None
    return f"http://{host}:{ELEGOO_SDCP_CAMERA_PORT}{ELEGOO_SDCP_CAMERA_PATH}"


def get_effective_camera_source(printer: Any) -> EffectiveCameraSource:
    """Return the camera source Printbuddy should use for a printer.

    Manual external-camera configuration wins. Existing Elegoo SDCP printer rows
    normally predate camera support and have no external camera URL persisted;
    for those, derive the validated CC1 MJPEG endpoint from the printer IP.
    """

    configured_enabled = bool(getattr(printer, "external_camera_enabled", False))
    configured_url = str(getattr(printer, "external_camera_url", None) or "").strip()
    configured_type = str(getattr(printer, "external_camera_type", None) or "").strip() or None
    configured_snapshot_url = getattr(printer, "external_camera_snapshot_url", None)

    if configured_enabled and configured_url:
        return EffectiveCameraSource(
            enabled=True,
            url=configured_url,
            camera_type=configured_type or ELEGOO_SDCP_CAMERA_TYPE,
            snapshot_url=configured_snapshot_url,
            derived=False,
        )

    if is_elegoo_sdcp_provider(getattr(printer, "provider", None)):
        derived_url = build_elegoo_sdcp_camera_url(getattr(printer, "ip_address", None))
        if derived_url:
            return EffectiveCameraSource(
                enabled=True,
                url=derived_url,
                camera_type=ELEGOO_SDCP_CAMERA_TYPE,
                snapshot_url=None,
                derived=True,
            )

    return EffectiveCameraSource(
        enabled=False,
        url=None,
        camera_type=configured_type,
        snapshot_url=configured_snapshot_url,
        derived=False,
    )


def _normalize_host(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        return (parsed.hostname or raw).strip("[]")
    return raw.strip("[]")


def _discover_elegoo_camera_activation_info(host: str, timeout: float = 2.0) -> ElegooCameraActivationInfo:
    """Best-effort UDP discovery for IDs used by SDCP WebSocket commands."""
    host = _normalize_host(host)
    if not host:
        return ElegooCameraActivationInfo()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(ELEGOO_SDCP_DISCOVERY_MESSAGE, (host, ELEGOO_SDCP_DISCOVERY_PORT))
            payload, _addr = sock.recvfrom(65535)
        data = json.loads(payload.decode("utf-8", errors="replace").strip("\x00\r\n "))
        if not isinstance(data, dict):
            return ElegooCameraActivationInfo()
        printer_id = str(data.get("Id") or data.get("id") or "").strip() or None
        mainboard_id = (
            str(data.get("MainboardID") or data.get("MainboardId") or data.get("Id") or data.get("id") or "").strip()
            or None
        )
        return ElegooCameraActivationInfo(printer_id=printer_id, mainboard_id=mainboard_id)
    except Exception as exc:  # noqa: BLE001 - discovery is optional in Docker/HA networks
        logger.debug("Elegoo camera activation discovery failed for %s: %s", host, type(exc).__name__)
        return ElegooCameraActivationInfo()


def build_elegoo_sdcp_status_command(info: ElegooCameraActivationInfo | None = None) -> dict[str, Any]:
    """Build the lightweight SDCP status request used to activate camera output."""
    info = info or ElegooCameraActivationInfo()
    request_id = str(int(time.time() * 1000))
    command: dict[str, Any] = {
        "Id": info.printer_id or "",
        "Data": {
            "Cmd": ELEGOO_SDCP_STATUS_COMMAND,
            "Data": {},
            "From": 0,
            "MainboardID": info.mainboard_id or "",
            "RequestID": request_id,
            "Timestamp": int(time.time()),
        },
    }
    if info.mainboard_id:
        command["Topic"] = f"sdcp/request/{info.mainboard_id}"
    return command


async def capture_elegoo_sdcp_activated_frame(
    host: object,
    camera_url: str,
    camera_type: str = ELEGOO_SDCP_CAMERA_TYPE,
    *,
    timeout: float = 15.0,
    snapshot_url: str | None = None,
    activation_warmup: float = 0.75,
) -> bytes | None:
    """Capture one CC1 MJPEG frame while holding the SDCP activation session open.

    The Centauri Carbon may expose ``:3031/video`` headers but withhold JPEG
    frames until a WebSocket status session is active. Fresh snapshot callers do
    not have the route-level fan-out activation task, so wrap the one-shot
    capture with the same lightweight activation used by live view.
    """
    disconnect_event = asyncio.Event()
    activation_task = asyncio.create_task(keep_elegoo_sdcp_camera_session(host, disconnect_event))
    try:
        if activation_warmup > 0:
            await asyncio.sleep(activation_warmup)
        from backend.app.services.external_camera import capture_frame

        return await capture_frame(
            camera_url,
            camera_type or ELEGOO_SDCP_CAMERA_TYPE,
            timeout=timeout,
            snapshot_url=snapshot_url,
        )
    finally:
        disconnect_event.set()
        try:
            await asyncio.wait_for(activation_task, timeout=2.0)
        except TimeoutError:
            activation_task.cancel()
            try:
                await activation_task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass


async def keep_elegoo_sdcp_camera_session(
    host: object,
    disconnect_event: asyncio.Event,
    *,
    discovery_timeout: float = 2.0,
    heartbeat_interval: float = 20.0,
) -> None:
    """Keep a WebSocket session open while reading the CC1 MJPEG endpoint.

    The Centauri Carbon's ``:3031/video`` endpoint returns MJPEG headers even
    when no camera frames are being produced. Opening the printer web UI starts
    a persistent ``ws://<host>:3030/websocket`` session and then frames appear.
    Mirror that behaviour for Printbuddy: hold a lightweight SDCP status session
    open for the lifetime of the MJPEG upstream and periodically refresh it.
    """
    normalized_host = _normalize_host(host)
    if not normalized_host:
        return

    info = await asyncio.to_thread(_discover_elegoo_camera_activation_info, normalized_host, discovery_timeout)
    ws_host = (
        f"[{normalized_host}]" if ":" in normalized_host and not normalized_host.startswith("[") else normalized_host
    )
    websocket_url = f"ws://{ws_host}:{ELEGOO_SDCP_WS_PORT}/websocket"

    try:
        import websockets

        async with websockets.connect(websocket_url, open_timeout=5, close_timeout=1) as websocket:
            logger.info("Elegoo SDCP camera activation session opened for %s", normalized_host)
            while not disconnect_event.is_set():
                command = build_elegoo_sdcp_status_command(info)
                await websocket.send(json.dumps(command, separators=(",", ":")))
                try:
                    await asyncio.wait_for(disconnect_event.wait(), timeout=heartbeat_interval)
                except TimeoutError:
                    # Keep session warm and refresh status command.
                    continue
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - camera stream can still try without activation
        logger.warning("Elegoo SDCP camera activation session failed for %s: %s", normalized_host, exc)
    finally:
        logger.info("Elegoo SDCP camera activation session closed for %s", normalized_host)
