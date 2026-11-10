"""Single-frame camera capture for AI failure-detection providers.

Mirrors the source resolution of ``GET /printers/{id}/camera/snapshot`` so a
detection provider sees the same camera as the user does: a manually
configured external camera, a provider-derived camera (PrusaLink, Creality
WebRTC, Elegoo SDCP) or, for Bambu printers, the built-in camera.

Camera ownership is preserved: when a live viewer is attached we reuse the
fan-out broadcaster's buffered frame and never open a competing socket on a
camera that only allows one connection (#1271, #1348).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

SNAPSHOT_CAPTURE_TIMEOUT = 20  # seconds

# Reasons returned alongside a missing frame
NO_CAMERA = "no_camera"
VIEWER_BUSY = "viewer_busy"
CAPTURE_FAILED = "capture_failed"

_BAMBU_PROVIDERS = {None, "", "bambu"}


async def capture_detection_frame(printer: Any) -> tuple[bytes | None, str | None]:
    """Capture one JPEG for ``printer``.

    Returns ``(frame, None)`` on success, or ``(None, reason)`` where reason is
    one of ``NO_CAMERA``, ``VIEWER_BUSY`` or ``CAPTURE_FAILED``.
    """
    # Late imports: the camera route module imports half the app.
    from backend.app.api.routes.camera import is_stream_active, try_get_active_buffered_frame
    from backend.app.services.elegoo_camera import get_effective_camera_source, is_elegoo_sdcp_camera_source

    printer_id = printer.id
    provider = getattr(printer, "provider", None)
    effective = get_effective_camera_source(printer)
    has_external = bool(effective.enabled and effective.url)

    if not has_external and provider not in _BAMBU_PROVIDERS:
        return None, NO_CAMERA

    buffered = try_get_active_buffered_frame(printer_id)
    if buffered:
        return buffered, None
    # A viewer is attached but the broadcaster has no frame yet. Opening a
    # second socket would compete with it (built-in Bambu cameras and derived
    # provider cameras typically allow only one); skip this cycle instead.
    if (not has_external or effective.derived) and is_stream_active(printer_id):
        return None, VIEWER_BUSY

    try:
        if has_external:
            if is_elegoo_sdcp_camera_source(provider, effective.url):
                from backend.app.services.elegoo_camera import capture_elegoo_sdcp_activated_frame

                frame = await capture_elegoo_sdcp_activated_frame(
                    printer.ip_address,
                    effective.url,
                    effective.camera_type or "mjpeg",
                    timeout=SNAPSHOT_CAPTURE_TIMEOUT,
                    snapshot_url=effective.snapshot_url,
                )
            else:
                from backend.app.services.external_camera import capture_frame

                frame = await capture_frame(
                    effective.url,
                    effective.camera_type or "mjpeg",
                    timeout=SNAPSHOT_CAPTURE_TIMEOUT,
                    snapshot_url=effective.snapshot_url,
                )
        else:
            from backend.app.services.camera import capture_camera_frame_bytes

            frame = await capture_camera_frame_bytes(
                ip_address=printer.ip_address,
                access_code=printer.access_code,
                model=printer.model,
                timeout=SNAPSHOT_CAPTURE_TIMEOUT,
            )
    except Exception as e:  # capture helpers should not raise, but never kill the loop
        logger.warning("Failure detection: camera capture raised for printer %s: %s", printer_id, e)
        return None, CAPTURE_FAILED

    if not frame:
        return None, CAPTURE_FAILED
    return frame, None
