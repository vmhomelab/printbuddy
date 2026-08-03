"""Tests for URL credential redaction in log lines."""

import logging
import time

from backend.app.core.logging_filters import CredentialRedactionFilter, redact_url_credentials


def test_redacts_password_but_keeps_diagnostic_url_parts():
    line = "ffmpeg input rtsp://camera-user:sup3r-secret@10.17.10.50:8554/live"

    redacted = redact_url_credentials(line)

    assert redacted == "ffmpeg input rtsp://camera-user:[REDACTED]@10.17.10.50:8554/live"
    assert "sup3r-secret" not in redacted


def test_redacts_password_with_at_symbol_by_using_last_at_before_path():
    line = "Input #0, rtsp://user:pa@ss@camera.local/stream"

    redacted = redact_url_credentials(line)

    assert redacted == "Input #0, rtsp://user:[REDACTED]@camera.local/stream"
    assert "pa@ss" not in redacted


def test_long_scheme_like_noise_does_not_trigger_polynomial_runtime():
    """A long scheme-character run without :// must stay bounded.

    This pins the CodeQL py/polynomial-redos fix: an unbounded scheme repetition
    restarts at every offset and consumes to line end before failing.
    """

    line = ("a" * 32768) + " user:secret@host"
    started = time.perf_counter()
    assert redact_url_credentials(line) == line
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1


def test_filter_redacts_record_message_and_args_before_formatting():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="ffmpeg stderr: %s",
        args=("rtsp://user:secret@camera.local/stream",),
        exc_info=None,
    )

    assert CredentialRedactionFilter().filter(record) is True

    rendered = record.getMessage()
    assert rendered == "ffmpeg stderr: rtsp://user:[REDACTED]@camera.local/stream"
    assert "secret" not in rendered
