"""Regression coverage for camera frames reused by snapshot consumers."""

import time
from unittest.mock import patch

from backend.app.api.routes import camera


def test_active_buffered_frame_rejects_stale_image():
    """Notification consumers must not attach a stalled stream's old frame."""

    printer_id = 8181
    with (
        patch.object(camera, "is_stream_active", return_value=True),
        patch.dict(camera._last_frames, {printer_id: b"stale-jpeg"}, clear=True),
        patch.dict(camera._last_frame_times, {printer_id: time.time() - 120}, clear=True),
    ):
        assert camera.try_get_active_buffered_frame(printer_id) is None
