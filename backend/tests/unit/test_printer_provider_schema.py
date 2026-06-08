import pytest
from pydantic import ValidationError

from backend.app.schemas.printer import PrinterCreate, normalize_external_camera_update


def _printer_payload(**overrides):
    payload = {
        "name": "Workshop P1S",
        "serial_number": " 01s00abc123 ",
        "ip_address": "192.168.1.20",
        "access_code": "12345678",
    }
    payload.update(overrides)
    return payload


def test_printer_create_defaults_to_bambu_provider():
    printer = PrinterCreate(**_printer_payload())

    assert printer.provider == "bambu"
    assert printer.serial_number == "01S00ABC123"


def test_printer_create_accepts_klipper_provider_metadata():
    printer = PrinterCreate(
        **_printer_payload(
            provider="klipper",
            api_url="http://voron.local:7125",
            auth_token="moonraker-token",
            provider_options='{"ui":"mainsail"}',
            external_camera_url="http://voron.local/webcam/?action=stream",
        )
    )

    assert printer.provider == "klipper"
    assert printer.api_url == "http://voron.local:7125"
    assert printer.external_camera_enabled is True
    assert printer.external_camera_type == "mjpeg"


def test_klipper_printer_can_be_created_without_bambu_serial_or_access_code():
    printer = PrinterCreate(
        name="Voron 2.4",
        provider="klipper",
        ip_address="voron.local",
        api_url="http://voron.local:7125",
        external_camera_url="rtsp://voron.local/stream",
    )

    assert printer.provider == "klipper"
    assert printer.serial_number == "KLIPPER-VORON-LOCAL"
    assert printer.access_code == "moonraker"
    assert printer.external_camera_type == "rtsp"


def test_fluidd_printer_can_be_created_without_bambu_serial_or_access_code():
    printer = PrinterCreate(
        name="Elegoo Neptune 4 Pro",
        provider="fluidd",
        ip_address="neptune.local",
        external_camera_url="http://neptune.local/webcam/snapshot.jpg",
    )

    assert printer.provider == "fluidd"
    assert printer.api_url == "http://neptune.local:7125"
    assert printer.serial_number == "KLIPPER-NEPTUNE-LOCAL"
    assert printer.access_code == "moonraker"
    assert printer.external_camera_type == "snapshot"


def test_prusalink_printer_can_be_created_without_bambu_serial_or_access_code():
    printer = PrinterCreate.model_validate(
        {
            "name": "Prusa MK4S",
            "provider": "prusalink",
            "ip_address": "prusa.local",
            "serial_number": "",
            "access_code": "",
            "auth_token": "dummy-prusalink-password",
            "external_camera_url": "http://prusa.local/camera/stream",
        }
    )

    assert printer.provider == "prusalink"
    assert printer.api_url == "http://prusa.local"
    assert printer.serial_number == "PRUSALINK-PRUSA-LOCAL"
    assert printer.access_code == "prusalink"
    assert printer.auth_token == "dummy-prusalink-password"


def test_prusa_connect_mobile_printer_can_be_created_with_uuid_and_token_only():
    printer = PrinterCreate.model_validate(
        {
            "name": "MK4S via Connect",
            "provider": "prusaconnect",
            "ip_address": "13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c",
            "auth_token": "dummy-connect-jwt",
        }
    )

    assert printer.provider == "prusaconnect"
    assert printer.serial_number == "PRUSACONNECT-13B5AF3D-7B44-42B1-9327-CF8A6FBF3F3C"[:50]
    assert printer.access_code == "prusaconnect"
    assert printer.api_url == "https://connect-mobile-api.prusa3d.com"
    assert printer.auth_token == "dummy-connect-jwt"


def test_non_bambu_printer_can_be_created_without_external_camera_url():
    printer = PrinterCreate(
        name="Voron 2.4",
        provider="klipper",
        ip_address="voron.local",
        api_url="http://voron.local:7125",
    )

    assert printer.provider == "klipper"
    assert printer.serial_number == "KLIPPER-VORON-LOCAL"
    assert printer.access_code == "moonraker"
    assert printer.external_camera_url is None
    assert printer.external_camera_type is None
    assert printer.external_camera_enabled is False


def test_external_camera_update_enables_and_infers_type_from_url_only_patch():
    update_data = normalize_external_camera_update(
        {
            "external_camera_url": "  http://neptune.local/webcam/?action=stream  ",
        }
    )

    assert update_data == {
        "external_camera_url": "http://neptune.local/webcam/?action=stream",
        "external_camera_enabled": True,
        "external_camera_type": "mjpeg",
    }


def test_external_camera_update_clears_disabled_state_when_url_is_blank():
    update_data = normalize_external_camera_update({"external_camera_url": "   "})

    assert update_data == {
        "external_camera_url": None,
        "external_camera_enabled": False,
        "external_camera_type": None,
    }


def test_printer_create_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        PrinterCreate(**_printer_payload(provider="octoprint"))
