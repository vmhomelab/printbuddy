"""Elegoo SDCP camera helpers.

Centauri Carbon exposes its LAN camera as an MJPEG stream on port 3031.
Keep this separate from the SDCP WebSocket/status client: camera streaming is
HTTP/MJPEG and should reuse Printbuddy's existing external-camera pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ELEGOO_SDCP_PROVIDER = "elegoo_sdcp"
ELEGOO_SDCP_CAMERA_PORT = 3031
ELEGOO_SDCP_CAMERA_PATH = "/video"
ELEGOO_SDCP_CAMERA_TYPE = "mjpeg"


@dataclass(frozen=True)
class EffectiveCameraSource:
    enabled: bool
    url: str | None
    camera_type: str | None
    snapshot_url: str | None = None
    derived: bool = False


def is_elegoo_sdcp_provider(provider: object) -> bool:
    return str(provider or "").strip().lower() == ELEGOO_SDCP_PROVIDER


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
