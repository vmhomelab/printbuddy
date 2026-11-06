"""Unit tests for the safe slicer-sidecar health response."""

import pytest

from backend.app.api.routes.settings import sanitize_slicer_health_payload


@pytest.mark.unit
def test_sanitize_slicer_health_payload_keeps_only_documented_safe_fields():
    """The test endpoint must not reflect sidecar URLs, tokens, or arbitrary data."""
    payload = {
        "status": "ok",
        "version": "2.4.1",
        "capabilities": ["slice", "profiles"],
        "url": "http://sidecar.internal:3003/health?token=secret",
        "token": "secret",
        "debug": {"anything": "else"},
    }

    assert sanitize_slicer_health_payload(payload) == {
        "status": "ok",
        "version": "2.4.1",
        "capabilities": ["slice", "profiles"],
    }
