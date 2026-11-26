"""Serial-number normalization on the printer schema (#1465).

Bambu serial numbers are uppercase alphanumeric and the MQTT report topic
``device/<serial>/report`` is case-sensitive. A serial entered in the wrong
case connects and subscribes without error but never receives a message, so
the schema normalizes it on input.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.printer import PrinterCreate


def _make(serial: str) -> PrinterCreate:
    return PrinterCreate(
        name="Test Printer",
        serial_number=serial,
        ip_address="192.168.1.50",
        access_code="12345678",
    )


def test_serial_number_uppercased():
    assert _make("01p00a3b1234567").serial_number == "01P00A3B1234567"


def test_serial_number_whitespace_stripped():
    assert _make("  01P00A3B1234567  ").serial_number == "01P00A3B1234567"


def test_serial_number_stripped_and_uppercased():
    assert _make(" 31b8c0ca1234567 ").serial_number == "31B8C0CA1234567"


def test_already_normalized_serial_unchanged():
    assert _make("31B8C0CA1234567").serial_number == "31B8C0CA1234567"


def test_blank_serial_number_rejected():
    with pytest.raises(ValidationError):
        _make("   ")


class TestRetargetApiUrlHost:
    def test_swaps_host_and_keeps_port(self):
        from backend.app.schemas.printer import retarget_api_url_host

        assert (
            retarget_api_url_host("http://192.168.1.20:7125", "192.168.1.20", "192.168.14.20")
            == "http://192.168.14.20:7125"
        )

    def test_keeps_scheme_path_and_credentials(self):
        from backend.app.schemas.printer import retarget_api_url_host

        assert (
            retarget_api_url_host("https://u:p@Printer.local:8443/api/", "printer.local", "u1.lan")
            == "https://u:p@u1.lan:8443/api/"
        )

    def test_url_without_port(self):
        from backend.app.schemas.printer import retarget_api_url_host

        assert retarget_api_url_host("http://10.0.0.5", "10.0.0.5", "10.0.1.5") == "http://10.0.1.5"

    def test_custom_host_is_left_alone(self):
        from backend.app.schemas.printer import retarget_api_url_host

        assert retarget_api_url_host("https://proxy.lan/moonraker", "10.0.0.5", "10.0.1.5") is None

    def test_empty_inputs(self):
        from backend.app.schemas.printer import retarget_api_url_host

        assert retarget_api_url_host(None, "10.0.0.5", "10.0.1.5") is None
        assert retarget_api_url_host("http://10.0.0.5:7125", "", "10.0.1.5") is None
