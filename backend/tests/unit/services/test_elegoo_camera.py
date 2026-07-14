from types import SimpleNamespace

from backend.app.schemas.printer import PrinterCreate, PrinterResponse
from backend.app.services.elegoo_camera import build_elegoo_sdcp_camera_url, get_effective_camera_source


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
