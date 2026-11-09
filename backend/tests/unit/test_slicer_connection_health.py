"""Unit tests for the safe slicer-sidecar health response."""

import pytest

from backend.app.api.routes.settings import detect_sidecar_slicer, sanitize_slicer_health_payload


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


@pytest.mark.unit
def test_sanitize_reads_the_version_from_the_wrapper_checks():
    """The slicer-API wrapper nests the CLI version under checks.orcaslicer."""
    payload = {
        "status": "healthy",
        "timestamp": "2026-11-07T19:37:00Z",
        "checks": {
            "orcaslicer": {"available": True, "version": "02.08.02.61"},
            "dataPath": {"accessible": True},
        },
    }

    assert sanitize_slicer_health_payload(payload) == {"status": "healthy", "version": "02.08.02.61"}


@pytest.mark.unit
def test_sanitize_ignores_unknown_versions():
    payload = {"status": "healthy", "checks": {"orcaslicer": {"available": True, "version": "unknown"}}}

    assert sanitize_slicer_health_payload(payload) == {"status": "healthy"}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("02.08.02.61", "bambu_studio"),
        ("02.06.00.51", "bambu_studio"),
        ("2.3.2", "orcaslicer"),
        ("2.5.0-beta", "orcaslicer"),
        ("2.4.1", "orcaslicer"),
        ("unknown", None),
        (None, None),
        ("", None),
    ],
)
def test_detect_sidecar_slicer(version, expected):
    assert detect_sidecar_slicer(version) == expected
