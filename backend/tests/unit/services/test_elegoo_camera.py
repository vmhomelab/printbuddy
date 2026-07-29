import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from backend.app.schemas.printer import PrinterCreate, PrinterResponse
from backend.app.services.elegoo_camera import (
    ElegooCameraActivationInfo,
    _discover_elegoo_camera_activation_info,
    build_elegoo_sdcp_camera_url,
    build_elegoo_sdcp_status_command,
    capture_elegoo_sdcp_activated_frame,
    get_effective_camera_source,
    is_elegoo_sdcp_camera_source,
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


def test_elegoo_sdcp_camera_source_detects_manual_cc1_mjpeg_url():
    assert is_elegoo_sdcp_camera_source("elegoo_sdcp", "http://192.168.1.234:3031/video") is True
    assert is_elegoo_sdcp_camera_source("elegoo_sdcp", "http://192.168.1.234:3031/video/") is True
    assert is_elegoo_sdcp_camera_source("elegoo_sdcp", "http://192.168.1.234:3031/stream") is False
    assert is_elegoo_sdcp_camera_source("elegoo_sdcp", "http://192.168.1.234:8080/video") is False
    assert is_elegoo_sdcp_camera_source("bambu", "http://192.168.1.234:3031/video") is False


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


def test_printer_response_exposes_effective_creality_go2rtc_camera():
    row = SimpleNamespace(
        id=8,
        name="K2 Plus",
        serial_number="KLIPPER-10-17-10-212",
        ip_address="10.17.10.212",
        access_code="moonraker",
        provider="fluidd",
        api_url="http://10.17.10.212:7125",
        auth_token=None,
        provider_options=json.dumps({"modelVersion": "F008", "go2rtc_url": "http://go2rtc.local:1984"}),
        model="Creality K2 Plus",
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
    assert response.external_camera_url is not None
    assert response.external_camera_snapshot_url is not None
    assert (
        "webrtc%3Ahttp%3A%2F%2F10.17.10.212%3A8000%2Fcall%2Fwebrtc_local%23format%3Dcreality"
        in response.external_camera_url
    )


def test_prusalink_provider_options_can_supply_effective_camera_source():
    row = SimpleNamespace(
        provider="prusalink",
        provider_options=json.dumps(
            {
                "prusalink_api_mode": "modern",
                "prusalink_auth_mode": "digest",
                "camera_url": "http://192.168.1.50:8080/?action=stream",
                "camera_snapshot_url": "http://192.168.1.50:8080/?action=snapshot",
            }
        ),
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    assert camera.enabled is True
    assert camera.derived is True
    assert camera.camera_type == "mjpeg"
    assert camera.url == "http://192.168.1.50:8080/?action=stream"
    assert camera.snapshot_url == "http://192.168.1.50:8080/?action=snapshot"


def test_prusalink_provider_options_snapshot_url_infers_snapshot_camera_type():
    row = SimpleNamespace(
        provider="prusalink",
        provider_options={"prusalink_snapshot_url": "http://192.168.1.50/camera/snapshot.jpg"},
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    assert camera.enabled is True
    assert camera.derived is True
    assert camera.camera_type == "snapshot"
    assert camera.url == "http://192.168.1.50/camera/snapshot.jpg"


def test_manual_external_camera_still_wins_over_prusalink_provider_options():
    row = SimpleNamespace(
        provider="prusalink",
        provider_options=json.dumps({"camera_url": "http://192.168.1.50/provider-stream"}),
        external_camera_enabled=True,
        external_camera_url="rtsp://camera.local/stream1",
        external_camera_type="rtsp",
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    assert camera.derived is False
    assert camera.camera_type == "rtsp"
    assert camera.url == "rtsp://camera.local/stream1"


def test_creality_k2_plus_derives_go2rtc_camera_from_model():
    row = SimpleNamespace(
        provider="fluidd",
        ip_address="10.17.10.212",
        model="Creality K2 Plus",
        provider_options=json.dumps({"go2rtc_url": "http://go2rtc.local:1984"}),
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    expected_src = "webrtc%3Ahttp%3A%2F%2F10.17.10.212%3A8000%2Fcall%2Fwebrtc_local%23format%3Dcreality"
    assert camera.enabled is True
    assert camera.derived is True
    assert camera.camera_type == "mjpeg"
    assert camera.url == f"http://go2rtc.local:1984/api/stream.mjpeg?src={expected_src}"
    assert camera.snapshot_url == f"http://go2rtc.local:1984/api/frame.jpeg?src={expected_src}"


def test_creality_k2_plus_derives_go2rtc_camera_from_model_version_code():
    row = SimpleNamespace(
        provider="klipper",
        ip_address="10.17.10.212",
        model="",
        provider_options={"modelVersion": "F008", "go2rtc_base_url": "http://go2rtc.local:1984/"},
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    assert camera.enabled is True
    assert camera.derived is True
    assert "%2Fcall%2Fwebrtc_local" in (camera.url or "")
    assert (camera.url or "").startswith("http://go2rtc.local:1984/api/stream.mjpeg?src=")


def test_creality_webrtc_support_flag_derives_call_root_endpoint():
    row = SimpleNamespace(
        provider="mainsail",
        ip_address="10.17.10.213",
        model="K1C",
        provider_options={"webrtcSupport": 1, "go2rtc_url": "http://go2rtc.local:1984"},
        external_camera_enabled=False,
        external_camera_url=None,
        external_camera_type=None,
        external_camera_snapshot_url=None,
    )

    camera = get_effective_camera_source(row)

    assert camera.enabled is True
    assert camera.derived is True
    assert "%2Fcall%2Fwebrtc_local" not in (camera.url or "")
    assert "%2Fcall%23format%3Dcreality" in (camera.url or "")


def test_manual_external_camera_still_wins_over_creality_go2rtc_detection():
    row = SimpleNamespace(
        provider="fluidd",
        ip_address="10.17.10.212",
        model="Creality K2 Plus",
        provider_options=json.dumps({"go2rtc_url": "http://go2rtc.local:1984"}),
        external_camera_enabled=True,
        external_camera_url="http://camera.local/manual-stream",
        external_camera_type="mjpeg",
        external_camera_snapshot_url="http://camera.local/snapshot.jpg",
    )

    camera = get_effective_camera_source(row)

    assert camera.derived is False
    assert camera.camera_type == "mjpeg"
    assert camera.url == "http://camera.local/manual-stream"
    assert camera.snapshot_url == "http://camera.local/snapshot.jpg"


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


def test_elegoo_camera_discovery_reads_nested_mainboard_id_from_real_probe_shape():
    payload = {
        "Id": "979d4C788A4a78bC777A870F1A02867A",
        "Data": {
            "Name": "Centauri Carbon",
            "MainboardIP": "192.168.1.181",
            "MainboardID": "4c8918d80103d46c00004c0000000000",
            "ProtocolVersion": "V3.0.0",
            "FirmwareVersion": "V0.3.0-o",
        },
    }
    sock = Mock()
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    sock.recvfrom.return_value = (json.dumps(payload).encode(), ("192.168.1.181", 3000))

    with patch("backend.app.services.elegoo_camera.socket.socket", return_value=sock):
        info = _discover_elegoo_camera_activation_info("192.168.1.181")

    assert info.printer_id == "979d4C788A4a78bC777A870F1A02867A"
    assert info.mainboard_id == "4c8918d80103d46c00004c0000000000"
    command = build_elegoo_sdcp_status_command(info)
    assert command["Topic"] == "sdcp/request/4c8918d80103d46c00004c0000000000"
    assert command["Data"]["MainboardID"] == "4c8918d80103d46c00004c0000000000"


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
