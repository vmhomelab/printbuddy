"""Sidecar revision check behind the slicer connection test."""

import pytest

from backend.app.api.routes.settings import sidecar_revision_status
from backend.app.services.slicer_api import EXPECTED_SIDECAR_REVISION


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        # Current sidecar, full or short commit id, any case.
        ({"revision": EXPECTED_SIDECAR_REVISION}, (EXPECTED_SIDECAR_REVISION, True)),
        ({"revision": EXPECTED_SIDECAR_REVISION[:7].upper()}, (EXPECTED_SIDECAR_REVISION[:7], True)),
        # Another revision.
        ({"revision": "9ff0c6e3ea02771b028ba29680d3f29e05e181fd"}, ("9ff0c6e3ea02771b028ba29680d3f29e05e181fd", False)),
        # Older sidecars report no revision at all.
        ({"status": "healthy"}, (None, False)),
        # Self-built image without the build arg, or junk: cannot be judged.
        ({"revision": "unknown"}, (None, None)),
        ({"revision": "<script>"}, (None, None)),
        ({"revision": 42}, (None, None)),
    ],
)
def test_sidecar_revision_status(payload, expected):
    assert sidecar_revision_status(payload) == expected
