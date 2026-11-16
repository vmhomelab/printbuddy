"""Shared camera capture for AI failure detection providers."""

import logging

from backend.app.core.database import async_session
from backend.app.models.printer import Printer

logger = logging.getLogger(__name__)


async def capture_detection_frame(printer_id: int, *, session_factory=async_session, timeout: int = 20) -> bytes | None:
    """Capture a JPEG, sharing live camera buffers to avoid competing readers."""
    # Late import to avoid cycles at module load time
    from backend.app.services.camera import capture_camera_frame_bytes
    from backend.app.services.external_camera import capture_frame as capture_external_frame

    async with session_factory() as db:
        printer = await db.get(Printer, printer_id)
    if printer is None:
        raise ValueError(f"Printer {printer_id} not found")

    # The camera the user sees in the snapshot route: a manual external
    # camera, or one the provider derives (Moonraker webcam, PrusaLink,
    # Creality WebRTC, Elegoo SDCP). A non-Bambu printer without one has no
    # camera at all; its IP is not a Bambu camera to try.
    from backend.app.services.elegoo_camera import get_effective_camera_source, is_elegoo_sdcp_camera_source

    effective = get_effective_camera_source(printer)
    has_external = bool(effective.enabled and effective.url)
    if not has_external and (printer.provider or "bambu") != "bambu":
        logger.info("AI failure detection: printer %s has no camera configured", printer_id)
        return None

    if has_external:
        # Same rule as the built-in branch below, which this used to skip:
        # an external camera is single-reader too, so polling while a viewer
        # is attached just fails (#2707).
        from backend.app.api.routes.camera import live_frame_for_capture

        defer, buffered = live_frame_for_capture(printer_id)
        if defer:
            if buffered:
                return buffered
            logger.info(
                "AI failure detection: viewer attached for printer %s but buffer empty; "
                "skipping this poll to avoid competing camera handle (#2707)",
                printer_id,
            )
            return None
        if is_elegoo_sdcp_camera_source(printer.provider, effective.url):
            from backend.app.services.elegoo_camera import capture_elegoo_sdcp_activated_frame

            return await capture_elegoo_sdcp_activated_frame(
                printer.ip_address,
                effective.url,
                effective.camera_type or "mjpeg",
                timeout=timeout,
                snapshot_url=effective.snapshot_url,
            )
        return await capture_external_frame(
            effective.url,
            effective.camera_type or "",
            timeout=timeout,
            snapshot_url=effective.snapshot_url,
        )

    # Reuse the fan-out broadcaster's buffered frame when a viewer is
    # already watching — avoids opening a second concurrent RTSP socket
    # on printers that allow only one camera connection (e.g. X2D
    # firmware 01.01.00.00; see #1271). Buffered frame is <1s old while
    # a viewer is connected.
    #
    # When a viewer is attached but no frame is buffered yet (startup
    # race, mid-reconnect), we DELIBERATELY skip this poll cycle instead
    # of falling through to capture_camera_frame_bytes. Opening a fresh
    # RTSP/chamber socket would compete with the live viewer and kick
    # the fan-out connection on most firmwares — exactly the freeze
    # reported in #1348. The poll loop retries in ~10s.
    from backend.app.api.routes.camera import is_stream_active, try_get_active_buffered_frame

    if is_stream_active(printer_id):
        buffered = try_get_active_buffered_frame(printer_id)
        if buffered:
            return buffered
        logger.info(
            "AI failure detection: viewer attached for printer %s but buffer empty; skipping this poll to avoid competing camera socket (#1348)",
            printer_id,
        )
        return None

    return await capture_camera_frame_bytes(
        ip_address=printer.ip_address,
        access_code=printer.access_code,
        model=printer.model,
        timeout=timeout,
    )
