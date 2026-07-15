from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.schemas.printer import PrinterCreate, PrinterResponse
from backend.app.services.elegoo_camera import (
    ElegooCameraActivationInfo,
    build_elegoo_sdcp_camera_url,
    build_elegoo_sdcp_status_command,
    capture_elegoo_sdcp_activated_frame,
    get_effective_camera_source,
)


def test_elegoo_sdcp_camera_url_uses_verified_mjpeg_endpoint():
    assert build_elegoo_sdcp_camera_url("192.168.1.181") == "http://192.168.1.181:3031/video"


def test_elegoo_sdcp_create_defaults_to_native_mjpeg_camera():
    printer = PrinterCreate(
        name="Centauri Carbon",
        provider="elegoo_sdcp",
        ip_address="192.168.1.181",
        serial_number="",
        access_code="",
    )

    assert printer.external_camera_enabled is True
    assert printer.external_camera_type == "mjpeg"
    assert printer.external_camera_url == "http://192.168.1.181:3031/video"


def test_elegoo_sdcp_existing_row_gets_effective_camera_source():
    row = SimpleNamespace(
        provider="elegoo_sdcp",
        ip_address="192.168.1.181",
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    assert camera.enabled is True
    assert camera.derived is True
    assert camera.camera_type == "mjpeg"
    assert camera.url == "http://192.168.1.181:3031/video"


def test_printer_response_exposes_effective_elegoo_camera_for_existing_rows():
    row = SimpleNamespace(
        id=7,
        name="CC1",
        serial_number="ELEGOO-SDCP-192-168-1-181",
        ip_address="192.168.1.181",
        access_code="elegoo-sdcp",
        provider="elegoo_sdcp",
        api_url=None,
        auth_token=None,
        provider_options=None,
        model="Centauri Carbon",
        location=None,
        auto_archive=True,
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
        camera_rotation=0,
        is_active=True,
        nozzle_count=1,
        print_hours_offset=0.0,
        plate_detection_enabled=False,
        plate_detection_roi_x=None,
        plate_detection_roi_y=None,
        plate_detection_roi_w=None,
        plate_detection_roi_h=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )

    response = PrinterResponse.from_orm_with_roi(row)

    assert response.external_camera_enabled is True
    assert response.external_camera_type == "mjpeg"
    assert response.external_camera_url == "http://192.168.1.181:3031/video"


def test_elegoo_sdcp_camera_activation_status_command_includes_mainboard_topic():
    command = build_elegoo_sdcp_status_command(
        ElegooCameraActivationInfo(printer_id="printer-123", mainboard_id="board-456")
    )

    assert command["Id"] == "printer-123"
    assert command["Topic"] == "sdcp/request/board-456"
    assert command["Data"]["Cmd"] == 0
    assert command["Data"]["Data"] == {}
    assert command["Data"]["From"] == 0
    assert command["Data"]["MainboardID"] == "board-456"
    assert command["Data"]["RequestID"]
    assert command["Data"]["Timestamp"]


def test_elegoo_sdcp_camera_activation_status_command_allows_unknown_ids():
    command = build_elegoo_sdcp_status_command()

    assert command["Id"] == ""
    assert "Topic" not in command
    assert command["Data"]["Cmd"] == 0
    assert command["Data"]["MainboardID"] == ""


@pytest.mark.asyncio
async def test_activated_elegoo_frame_capture_wraps_capture_with_sdcp_session():
    session_events = []

    async def fake_activation(host, disconnect_event, **_kwargs):
        session_events.append((host, disconnect_event.is_set()))
        await disconnect_event.wait()
        session_events.append((host, disconnect_event.is_set()))

    with (
        patch(
            "backend.app.services.elegoo_camera.keep_elegoo_sdcp_camera_session",
            new=AsyncMock(side_effect=fake_activation),
        ) as mocked_activation,
        patch(
            "backend.app.services.external_camera.capture_frame",
            new=AsyncMock(return_value=b"jpeg-frame"),
        ) as mocked_capture,
    ):
        frame = await capture_elegoo_sdcp_activated_frame(
            "192.168.1.234",
            "http://192.168.1.234:3031/video",
            "mjpeg",
            timeout=12,
            activation_warmup=0.01,
        )

    assert frame == b"jpeg-frame"
    mocked_activation.assert_awaited_once()
    mocked_capture.assert_awaited_once_with(
        "http://192.168.1.234:3031/video",
        "mjpeg",
        timeout=12,
        snapshot_url=None,
    )
    assert session_events == [("192.168.1.234", False), ("192.168.1.234", True)]
