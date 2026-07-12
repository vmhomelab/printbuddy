from types import SimpleNamespace

import httpx
import pytest

from backend.app.services.printer_manager import PrinterManager
from backend.app.services.printer_providers.factory import (
    SUPPORTED_PROVIDERS,
    create_printer_client,
    normalize_provider,
)
from backend.app.services.printer_providers.moonraker import MoonrakerPrinterClient
from backend.app.services.printer_providers.prusaconnect import PrusaConnectMobilePrinterClient
from backend.app.services.printer_providers.prusalink import PrusaLinkPrinterClient


def test_supported_printbuddy_providers_are_registered():
    assert {"bambu", "klipper", "mainsail", "fluidd", "prusalink", "prusaconnect"} == SUPPORTED_PROVIDERS


@pytest.mark.parametrize("provider", ["klipper", "mainsail", "fluidd"])
def test_moonraker_providers_create_moonraker_client(provider):
    printer = SimpleNamespace(
        provider=provider, api_url="http://printer.local:7125", auth_token=None, ip_address="printer.local"
    )

    client = create_printer_client(printer)

    assert isinstance(client, MoonrakerPrinterClient)
    assert client.base_url == "http://printer.local:7125/"


def test_moonraker_provider_falls_back_to_default_port():
    printer = SimpleNamespace(provider="klipper", api_url=None, auth_token="token", ip_address="192.168.1.50")

    client = create_printer_client(printer)

    assert isinstance(client, MoonrakerPrinterClient)
    assert client.base_url == "http://192.168.1.50:7125/"


def test_moonraker_stop_print_posts_cancel_endpoint(monkeypatch):
    posted: list[tuple[str, dict[str, object]]] = []

    def fake_post(url, *, json, headers, timeout):  # noqa: ARG001
        posted.append((str(url), json))
        return httpx.Response(200, json={"result": "ok"}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://elegoo.local:7125")

    assert client.stop_print() is True
    assert posted == [("http://elegoo.local:7125/printer/print/cancel", {})]


def test_moonraker_start_print_treats_verified_timeout_as_success(monkeypatch):
    posts: list[tuple[str, dict[str, object]]] = []

    def fake_post(url, *, json, headers, timeout):  # noqa: ARG001
        posts.append((str(url), json))
        raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://elegoo.local:7125")

    def fake_status_update():
        client.state.state = "RUNNING"
        client.state.current_print = "firstlayer60x60mm_PLA_2m25s.gcode"
        return True

    monkeypatch.setattr(client, "request_status_update", fake_status_update)

    assert client.start_print("/firstlayer60x60mm_PLA_2m25s.gcode") is True
    assert posts == [
        (
            "http://elegoo.local:7125/printer/print/start",
            {"filename": "firstlayer60x60mm_PLA_2m25s.gcode"},
        )
    ]


def test_moonraker_status_edges_emit_print_start_and_complete(monkeypatch):
    start_payloads: list[dict[str, object]] = []
    complete_payloads: list[dict[str, object]] = []
    state_payloads: list[object] = []
    client = MoonrakerPrinterClient(
        "http://elegoo.local:7125",
        on_state_change=state_payloads.append,
        on_print_start=start_payloads.append,
        on_print_complete=complete_payloads.append,
    )
    statuses = iter(
        [
            {
                "print_stats": {"state": "standby", "filename": ""},
                "virtual_sdcard": {"progress": 0.0},
                "display_status": {},
                "extruder": {},
                "heater_bed": {"temperature": 25},
            },
            {
                "print_stats": {"state": "printing", "filename": "benchy.gcode", "print_duration": 30},
                "virtual_sdcard": {"progress": 0.2},
                "display_status": {},
                "extruder": {},
                "heater_bed": {"temperature": 60},
            },
            {
                "print_stats": {"state": "complete", "filename": ""},
                "virtual_sdcard": {"progress": 1.0},
                "display_status": {},
                "extruder": {},
                "heater_bed": {"temperature": 55},
            },
        ]
    )

    monkeypatch.setattr(client, "_query_objects", lambda names: next(statuses))  # noqa: ARG005
    monkeypatch.setattr(client, "_query_fan_status", lambda: {})
    monkeypatch.setattr("backend.app.services.printer_providers.moonraker.time.monotonic", iter([100.0, 160.0]).__next__)

    assert client.request_status_update() is True
    assert start_payloads == []
    assert complete_payloads == []

    assert client.request_status_update() is True
    assert start_payloads == [
        {
            "filename": "benchy.gcode",
            "subtask_name": "benchy.gcode",
            "progress": 20.0,
            "remaining_time": 120,
            "status": "RUNNING",
            "raw_data": {
                "print_stats": {"state": "printing", "filename": "benchy.gcode", "print_duration": 30},
                "virtual_sdcard": {"progress": 0.2},
                "display_status": {},
                "extruder": {},
                "heater_bed": {"temperature": 60},
            },
        }
    ]

    assert client.request_status_update() is True
    assert complete_payloads == [
        {
            "filename": "benchy.gcode",
            "subtask_name": "benchy.gcode",
            "progress": 100.0,
            "remaining_time": None,
            "status": "completed",
            "raw_data": {
                "print_stats": {"state": "complete", "filename": ""},
                "virtual_sdcard": {"progress": 1.0},
                "display_status": {},
                "extruder": {},
                "heater_bed": {"temperature": 55},
            },
            "actual_time_seconds": 60,
        }
    ]
    assert len(state_payloads) == 3


def test_moonraker_factory_wires_lifecycle_callbacks():
    start_payloads: list[dict[str, object]] = []
    complete_payloads: list[dict[str, object]] = []
    printer = SimpleNamespace(
        provider="klipper", api_url="http://printer.local:7125", auth_token=None, ip_address="printer.local", model="Elegoo"
    )

    client = create_printer_client(
        printer,
        on_print_start=start_payloads.append,
        on_print_complete=complete_payloads.append,
    )

    assert isinstance(client, MoonrakerPrinterClient)
    assert client.on_print_start is not None
    assert client.on_print_complete is not None
    assert client.on_print_start.__self__ is start_payloads
    assert client.on_print_complete.__self__ is complete_payloads


def test_prusalink_provider_creates_prusalink_client_with_default_url_and_username():
    printer = SimpleNamespace(
        provider="prusalink",
        api_url=None,
        auth_token="dummy-prusalink-password",
        ip_address="prusa.local",
        provider_options=None,
    )

    client = create_printer_client(printer)

    assert isinstance(client, PrusaLinkPrinterClient)
    assert client.base_url == "http://prusa.local/"
    assert client.username == "maker"
    assert client.password == "dummy-prusalink-password"


def test_prusalink_provider_preserves_custom_port_url():
    printer = SimpleNamespace(
        provider="prusalink",
        api_url="http://10.17.1.96:8087",
        auth_token="dev-api-key",
        ip_address="10.17.1.96",
        provider_options=None,
    )

    client = create_printer_client(printer)

    assert isinstance(client, PrusaLinkPrinterClient)
    assert client.base_url == "http://10.17.1.96:8087/"


def test_prusalink_provider_reads_detected_api_and_auth_mode_from_options():
    printer = SimpleNamespace(
        provider="prusalink",
        api_url="http://prusa.local",
        auth_token="dummy-prusalink-password",
        ip_address="prusa.local",
        provider_options='{"username":"maker","prusalink_api_mode":"modern","prusalink_auth_mode":"digest"}',
    )

    client = create_printer_client(printer)

    assert isinstance(client, PrusaLinkPrinterClient)
    assert client.api_mode == "modern"
    assert client.auth_mode == "digest"


def test_prusalink_auto_detect_prefers_modern_digest(monkeypatch):
    attempts: list[tuple[str, type, dict[str, str]]] = []

    def fake_get(url, *, auth, headers, timeout):  # noqa: ARG001
        attempts.append((str(url), type(auth), headers))
        if str(url).endswith("/api/v1/info") and isinstance(auth, httpx.DigestAuth):
            return httpx.Response(200, json={"api": "modern"}, request=httpx.Request("GET", str(url)))
        return httpx.Response(401, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaLinkPrinterClient("http://prusa.local", password="dummy-prusalink-password")

    detected = client.detect_api_auth_mode()

    assert detected == {"prusalink_api_mode": "modern", "prusalink_auth_mode": "digest"}
    assert attempts == [("http://prusa.local/api/v1/info", httpx.DigestAuth, {})]


def test_prusalink_auto_detect_falls_back_to_legacy_x_api_key(monkeypatch):
    attempts: list[tuple[str, object, dict[str, str]]] = []

    def fake_get(url, *, auth=None, headers=None, timeout=None):  # noqa: ARG001
        headers = headers or {}
        attempts.append((str(url), type(auth) if auth is not None else None, headers))
        if str(url).endswith("/api/version") and headers == {"X-Api-Key": "legacy-key"}:
            return httpx.Response(200, json={"api": "legacy"}, request=httpx.Request("GET", str(url)))
        return httpx.Response(403, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaLinkPrinterClient("http://prusa.local", password="legacy-key")

    detected = client.detect_api_auth_mode()

    assert detected == {"prusalink_api_mode": "legacy", "prusalink_auth_mode": "x_api_key"}
    assert attempts == [
        ("http://prusa.local/api/v1/info", httpx.DigestAuth, {}),
        ("http://prusa.local/api/v1/info", httpx.BasicAuth, {"X-Api-Key": "legacy-key"}),
        ("http://prusa.local/api/version", None, {"X-Api-Key": "legacy-key"}),
    ]


def test_prusalink_legacy_connect_uses_x_api_key_endpoints(monkeypatch):
    requested: list[tuple[str, object, dict[str, str]]] = []

    def fake_get(url, *, auth=None, headers=None, timeout=None):  # noqa: ARG001
        headers = headers or {}
        requested.append((str(url), type(auth) if auth is not None else None, headers))
        if str(url).endswith("/api/version"):
            return httpx.Response(200, json={"api": "0.1"}, request=httpx.Request("GET", str(url)))
        return httpx.Response(204, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaLinkPrinterClient(
        "http://prusa.local", password="legacy-key", api_mode="legacy", auth_mode="x_api_key"
    )

    client.connect()

    assert client.state.connected is True
    assert client.state.state == "IDLE"
    assert requested == [
        ("http://prusa.local/api/version", None, {"X-Api-Key": "legacy-key"}),
        ("http://prusa.local/api/job", None, {"X-Api-Key": "legacy-key"}),
    ]


def test_prusa_connect_mobile_provider_creates_cloud_client_with_default_api_url():
    printer = SimpleNamespace(
        provider="prusaconnect",
        api_url=None,
        auth_token="dummy-connect-token",
        ip_address="13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c",
        provider_options=None,
    )

    client = create_printer_client(printer)

    assert isinstance(client, PrusaConnectMobilePrinterClient)
    assert client.base_url == "https://connect-mobile-api.prusa3d.com/"
    assert client.printer_uuid == "13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c"
    assert client.auth_token == "dummy-connect-token"


def test_prusa_connect_mobile_status_update_maps_prusa_connect_payload(monkeypatch):
    requested: list[tuple[str, dict[str, str]]] = []

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        requested.append((str(url), headers))
        assert headers == {"Authorization": "Bearer dummy-connect-token"}
        return httpx.Response(
            200,
            json={
                "uuid": "13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c",
                "name": "MK4S",
                "state": "PRINTING",
                "telemetry": {
                    "temp_nozzle": 214.2,
                    "target_nozzle": 215,
                    "temp_bed": 59.7,
                    "target_bed": 60,
                    "axis_z": 12.34,
                },
                "job": {
                    "display_name": "benchy_connect.gcode",
                    "progress": 42.5,
                    "time_remaining": 1200,
                },
            },
            request=httpx.Request("GET", str(url)),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaConnectMobilePrinterClient(
        "13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c",
        auth_token="dummy-connect-token",
    )

    assert client.request_status_update() is True
    assert requested == [
        (
            "https://connect-mobile-api.prusa3d.com/api/v1/printers/13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c",
            {"Authorization": "Bearer dummy-connect-token"},
        )
    ]
    assert client.state.connected is True
    assert client.state.state == "RUNNING"
    assert client.state.gcode_file == "benchy_connect.gcode"
    assert client.state.progress == 42.5
    assert client.state.remaining_time == 20
    assert client.state.temperatures["nozzle"] == 214.2
    assert client.state.temperatures["nozzle_target"] == 215.0
    assert client.state.temperatures["bed"] == 59.7
    assert client.state.temperatures["bed_target"] == 60.0
    assert client.state.position["z"] == 12.34


def test_prusalink_status_update_maps_openapi_status_payload(monkeypatch):
    requested_urls: list[str] = []

    def fake_get(url, *, auth, headers, timeout):  # noqa: ARG001
        requested_urls.append(str(url))
        assert isinstance(auth, httpx.BasicAuth)
        assert headers == {"X-Api-Key": "dummy-prusalink-password"}
        if str(url).endswith("/api/v1/status"):
            payload = {
                "printer": {
                    "state": "PRINTING",
                    "temp_nozzle": 213.5,
                    "target_nozzle": 215,
                    "temp_bed": 59.4,
                    "target_bed": 60,
                },
                "job": {"id": 42, "progress": 37.5, "time_remaining": 900},
            }
        else:
            payload = {
                "id": 42,
                "state": "PRINTING",
                "progress": 37.5,
                "time_remaining": 900,
                "file": {"display_name": "benchy_mk4s.gcode", "name": "BENCHY~1.GCO", "path": "/local"},
            }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaLinkPrinterClient("http://prusa.local", password="dummy-prusalink-password")

    assert client.request_status_update() is True
    assert requested_urls == ["http://prusa.local/api/v1/status", "http://prusa.local/api/v1/job"]
    assert client.state.connected is True
    assert client.state.state == "RUNNING"
    assert client.state.gcode_file == "benchy_mk4s.gcode"
    assert client.state.current_print == "benchy_mk4s.gcode"
    assert client.state.progress == 37.5
    assert client.state.remaining_time == 15
    assert client.state.temperatures["nozzle"] == 213.5
    assert client.state.temperatures["nozzle_target"] == 215.0
    assert client.state.temperatures["bed"] == 59.4
    assert client.state.temperatures["bed_target"] == 60.0


def test_prusalink_retries_digest_when_device_requests_digest_auth(monkeypatch):
    auth_types: list[type] = []

    def fake_get(url, *, auth, headers, timeout):  # noqa: ARG001
        auth_types.append(type(auth))
        if len(auth_types) == 1:
            return httpx.Response(
                401,
                headers={"www-authenticate": 'Digest realm="PrusaLink"'},
                request=httpx.Request("GET", str(url)),
            )
        return httpx.Response(200, json={"printer": {}, "job": {}}, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaLinkPrinterClient("http://prusa.local", password="dummy-prusalink-password")

    assert client._get("api/v1/status") == {"printer": {}, "job": {}}
    assert auth_types == [httpx.BasicAuth, httpx.DigestAuth]


def test_prusalink_axis_jog_posts_prusalink_printhead_command(monkeypatch):
    posted: list[tuple[str, dict]] = []

    def fake_post(url, *, auth, headers, timeout, json):  # noqa: ARG001
        posted.append((str(url), json))
        return httpx.Response(204, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = PrusaLinkPrinterClient("http://prusa.local", password="dummy-prusalink-password")

    assert client.send_gcode("G91\nG1 X1.00 F3000\nG90") is True
    assert posted == [("http://prusa.local/api/printer/printhead", {"command": "jog", "x": 1.0, "feedrate": 3000})]


def test_prusalink_extrude_posts_prusalink_tool_command(monkeypatch):
    posted: list[tuple[str, dict]] = []

    def fake_post(url, *, auth, headers, timeout, json):  # noqa: ARG001
        posted.append((str(url), json))
        return httpx.Response(204, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = PrusaLinkPrinterClient("http://prusa.local", password="dummy-prusalink-password")

    assert client.send_gcode("M83\nG1 E-10.00 F300\nM82") is True
    assert posted == [("http://prusa.local/api/printer/tool", {"command": "extrude", "amount": -10.0, "feedrate": 300})]


def test_prusalink_disable_steppers_posts_prusalink_printhead_command(monkeypatch):
    posted: list[tuple[str, dict]] = []

    def fake_post(url, *, auth, headers, timeout, json):  # noqa: ARG001
        posted.append((str(url), json))
        return httpx.Response(204, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = PrusaLinkPrinterClient("http://prusa.local", password="dummy-prusalink-password")

    assert client.send_gcode("M84") is True
    assert posted == [("http://prusa.local/api/printer/printhead", {"command": "disable_steppers"})]


def test_moonraker_client_keeps_7125_fallback_for_fluidd_ui_url():
    printer = SimpleNamespace(
        provider="fluidd", api_url="http://neptune.local", auth_token=None, ip_address="neptune.local"
    )

    client = create_printer_client(printer)

    assert isinstance(client, MoonrakerPrinterClient)
    assert client.base_url == "http://neptune.local/"
    assert client.base_url_candidates == ["http://neptune.local/", "http://neptune.local:7125/"]


def test_moonraker_client_keeps_no_port_fallback_for_explicit_7125_url():
    printer = SimpleNamespace(
        provider="fluidd", api_url="http://neptune.local:7125", auth_token=None, ip_address="neptune.local"
    )

    client = create_printer_client(printer)

    assert isinstance(client, MoonrakerPrinterClient)
    assert client.base_url == "http://neptune.local:7125/"
    assert client.base_url_candidates == ["http://neptune.local:7125/", "http://neptune.local/"]


def test_moonraker_connect_tries_7125_when_fluidd_ui_url_is_pasted(monkeypatch):
    requested_urls: list[str] = []

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        requested_urls.append(str(url))
        if str(url) == "http://neptune.local/server/info":
            raise httpx.ConnectError("Fluidd UI is not Moonraker")
        return httpx.Response(
            200,
            json={"result": {"klippy_state": "ready"}},
            request=httpx.Request("GET", str(url)),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = MoonrakerPrinterClient("http://neptune.local")

    client.connect()

    assert requested_urls == [
        "http://neptune.local/server/info",
        "http://neptune.local:7125/server/info",
        "http://neptune.local:7125/printer/objects/query?webhooks&print_stats&virtual_sdcard&display_status&extruder&heater_bed",
        "http://neptune.local:7125/printer/objects/list",
    ]
    assert client.base_url == "http://neptune.local:7125/"
    assert client.state.state == "IDLE"


def test_moonraker_connect_tries_no_port_proxy_when_7125_fails(monkeypatch):
    requested_urls: list[str] = []

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        requested_urls.append(str(url))
        if str(url) == "http://neptune.local:7125/server/info":
            raise httpx.ConnectError("Moonraker direct port is not reachable")
        return httpx.Response(
            200,
            json={"result": {"klippy_state": "ready"}},
            request=httpx.Request("GET", str(url)),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    client.connect()

    assert requested_urls == [
        "http://neptune.local:7125/server/info",
        "http://neptune.local/server/info",
        "http://neptune.local/printer/objects/query?webhooks&print_stats&virtual_sdcard&display_status&extruder&heater_bed",
        "http://neptune.local/printer/objects/list",
    ]
    assert client.base_url == "http://neptune.local/"
    assert client.state.state == "IDLE"


def test_moonraker_status_update_populates_printbuddy_status_fields(monkeypatch):
    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        requested_url = str(url)
        if requested_url == "http://neptune.local:7125/printer/objects/list":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "objects": ["fan", "heater_fan hotend_fan", "fan_generic chamber_fan", "fan_generic aux_fan"]
                    }
                },
                request=httpx.Request("GET", requested_url),
            )
        if requested_url == (
            "http://neptune.local:7125/printer/objects/query?"
            "fan&heater_fan%20hotend_fan&fan_generic%20chamber_fan&fan_generic%20aux_fan"
        ):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": {
                            "fan": {"speed": 0.35},
                            "heater_fan hotend_fan": {"speed": 0.0},
                            "fan_generic chamber_fan": {"speed": 0.70},
                            "fan_generic aux_fan": {"speed": 1.0},
                        }
                    }
                },
                request=httpx.Request("GET", requested_url),
            )
        assert requested_url == (
            "http://neptune.local:7125/printer/objects/query?"
            "webhooks&print_stats&virtual_sdcard&display_status&extruder&heater_bed"
        )
        return httpx.Response(
            200,
            json={
                "result": {
                    "status": {
                        "print_stats": {
                            "state": "printing",
                            "filename": "elegoo_test.gcode",
                            "print_duration": 1800,
                        },
                        "virtual_sdcard": {"progress": 0.5},
                        "extruder": {"temperature": 210.3, "target": 215.0},
                        "heater_bed": {"temperature": 59.8, "target": 60.0},
                    }
                }
            },
            request=httpx.Request("GET", str(url)),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    assert client.request_status_update() is True
    assert client.state.connected is True
    assert client.state.state == "RUNNING"
    assert client.state.gcode_file == "elegoo_test.gcode"
    assert client.state.current_print == "elegoo_test.gcode"
    assert client.state.progress == 50.0
    assert client.state.remaining_time == 30
    assert client.state.temperatures["nozzle"] == 210.3
    assert client.state.temperatures["nozzle_target"] == 215.0
    assert client.state.temperatures["bed"] == 59.8
    assert client.state.temperatures["bed_target"] == 60.0
    assert client.state.cooling_fan_speed == 35
    assert client.state.big_fan1_speed == 100
    assert client.state.big_fan2_speed == 70
    assert client.state.heatbreak_fan_speed == 0


def test_moonraker_status_keeps_missing_fans_as_none(monkeypatch):
    requested_urls: list[str] = []

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        requested_urls.append(str(url))
        if str(url).endswith("/printer/objects/list"):
            return httpx.Response(
                200,
                json={"result": {"objects": ["fan", "temperature_sensor chamber"]}},
                request=httpx.Request("GET", str(url)),
            )
        if str(url).endswith("/printer/objects/query?fan"):
            return httpx.Response(
                200,
                json={"result": {"status": {"fan": {"speed": 0.0}}}},
                request=httpx.Request("GET", str(url)),
            )
        return httpx.Response(
            200,
            json={
                "result": {
                    "status": {
                        "print_stats": {"state": "standby", "filename": ""},
                        "virtual_sdcard": {"progress": 0.0},
                        "extruder": {"temperature": 25.0, "target": 0.0},
                        "heater_bed": {"temperature": 25.0, "target": 0.0},
                    }
                }
            },
            request=httpx.Request("GET", str(url)),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    assert client.request_status_update() is True
    assert client.state.cooling_fan_speed == 0
    assert client.state.big_fan1_speed is None
    assert client.state.big_fan2_speed is None
    assert client.state.heatbreak_fan_speed is None


def test_moonraker_send_gcode_posts_script_to_moonraker(monkeypatch):
    posted: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def fake_post(url, *, json, headers, timeout):  # noqa: A002, ARG001
        posted.append((str(url), json, headers))
        return httpx.Response(200, json={"result": "ok"}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://neptune.local:7125", auth_token="secret-token")

    assert client.send_gcode("G91\nG1 X10.00 F3000\nG90") is True
    assert posted == [
        (
            "http://neptune.local:7125/printer/gcode/script",
            {"script": "G91\nG1 X10.00 F3000\nG90"},
            {"Authorization": "Bearer secret-token"},
        )
    ]


def test_moonraker_temperature_helpers_emit_standard_gcode(monkeypatch):
    scripts: list[str] = []

    def fake_post(url, *, json, headers, timeout):  # noqa: A002, ARG001
        scripts.append(json["script"])
        return httpx.Response(200, json={"result": "ok"}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    assert client.set_nozzle_temperature(215) is True
    assert client.set_bed_temperature(60) is True
    assert scripts == ["M104 S215", "M140 S60"]


def test_moonraker_connect_fetches_status_and_check_staleness_keeps_connected(monkeypatch):
    requested_urls: list[str] = []

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        requested_urls.append(str(url))
        if str(url).endswith("/server/info"):
            payload = {"result": {"klippy_state": "ready"}}
        else:
            payload = {
                "result": {
                    "status": {
                        "print_stats": {"state": "standby", "filename": ""},
                        "virtual_sdcard": {"progress": 0.0},
                        "extruder": {"temperature": 26.1, "target": 0.0},
                        "heater_bed": {"temperature": 26.2, "target": 0.0},
                    }
                }
            }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    client.connect()
    assert client.state.connected is True
    assert client.state.state == "IDLE"
    assert client.state.temperatures["nozzle"] == 26.1

    assert client.check_staleness() is True
    assert client.state.connected is True
    assert requested_urls == [
        "http://neptune.local:7125/server/info",
        "http://neptune.local:7125/printer/objects/query?webhooks&print_stats&virtual_sdcard&display_status&extruder&heater_bed",
        "http://neptune.local:7125/printer/objects/list",
        "http://neptune.local:7125/printer/objects/query?webhooks&print_stats&virtual_sdcard&display_status&extruder&heater_bed",
        "http://neptune.local:7125/printer/objects/list",
    ]


@pytest.mark.asyncio
async def test_klipper_connection_probe_uses_moonraker_client(monkeypatch):
    calls = []

    class FakeMoonrakerClient:
        state = SimpleNamespace(state="ready", raw_status={"klippy_state": "ready"})

        def connect(self):
            calls.append("connect")

        def disconnect(self):
            calls.append("disconnect")

    def fake_create_printer_client(printer):
        calls.append((printer.provider, printer.api_url, printer.auth_token, printer.ip_address))
        return FakeMoonrakerClient()

    monkeypatch.setattr(
        "backend.app.services.printer_manager.create_printer_client",
        fake_create_printer_client,
    )

    result = await PrinterManager().test_connection(
        ip_address="voron.local",
        serial_number="KLIPPER-VORON-LOCAL",
        access_code="moonraker",
        provider="klipper",
        api_url="http://voron.local:7125",
        auth_token="token",
    )

    assert result == {"success": True, "state": "ready", "model": "Klipper/Moonraker"}
    assert calls == [("klipper", "http://voron.local:7125", "token", "voron.local"), "connect", "disconnect"]


@pytest.mark.asyncio
async def test_prusalink_connection_probe_returns_detected_provider_options(monkeypatch):
    calls = []

    class FakePrusaLinkClient:
        state = SimpleNamespace(state="IDLE")

        def detect_api_auth_mode(self):
            calls.append("detect")
            return {"prusalink_api_mode": "modern", "prusalink_auth_mode": "digest"}

        def connect(self):
            calls.append("connect")

        def disconnect(self):
            calls.append("disconnect")

    def fake_create_printer_client(printer):
        calls.append(
            (printer.provider, printer.api_url, printer.auth_token, printer.ip_address, printer.provider_options)
        )
        return FakePrusaLinkClient()

    monkeypatch.setattr(
        "backend.app.services.printer_manager.create_printer_client",
        fake_create_printer_client,
    )

    result = await PrinterManager().test_connection(
        ip_address="prusa.local",
        serial_number="PRUSALINK-PRUSA-LOCAL",
        access_code="prusalink",
        provider="prusalink",
        api_url="http://prusa.local",
        auth_token="secret",
    )

    assert result == {
        "success": True,
        "state": "IDLE",
        "model": "PrusaLink",
        "provider_options": '{"prusalink_api_mode":"modern","prusalink_auth_mode":"digest"}',
    }
    assert calls == [
        ("prusalink", "http://prusa.local", "secret", "prusa.local", None),
        "detect",
        "connect",
        "disconnect",
    ]


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Unsupported printer provider"):
        normalize_provider("octoprint")


def test_moonraker_lists_gcode_files(monkeypatch):
    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        assert str(url) == "http://neptune.local:7125/server/files/list?root=gcodes"
        return httpx.Response(
            200,
            json={"result": [{"path": "cube.bgcode", "size": 1234, "modified": 1710000000}]},
            request=httpx.Request("GET", str(url)),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    assert client.list_files("/") == [
        {
            "name": "cube.bgcode",
            "type": "file",
            "size": 1234,
            "modified": "2024-03-09T16:00:00+00:00",
            "path": "/cube.bgcode",
        }
    ]


def test_moonraker_uploads_and_starts_print(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []
    gcode = tmp_path / "cube.gcode"
    gcode.write_text("G28\n", encoding="utf-8")

    def fake_post(url, **kwargs):
        calls.append((str(url), kwargs.get("json", {}).get("filename") or kwargs.get("data", {}).get("root", "")))
        return httpx.Response(200, json={"result": {}}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://neptune.local:7125")

    assert client.upload_file(gcode, "/cube.gcode") is True
    assert client.start_print("/cube.gcode") is True
    assert calls[0][0] == "http://neptune.local:7125/server/files/upload"
    assert calls[1] == ("http://neptune.local:7125/printer/print/start", "cube.gcode")


def test_moonraker_elegoo_maps_model_alias_to_gcodes_root(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []
    gcode = tmp_path / "cube.gcode"
    gcode.write_text("G28\n", encoding="utf-8")

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        calls.append(("get", str(url)))
        if str(url).endswith("printer/objects/query?configfile"):
            return httpx.Response(
                200,
                json={
                    "result": {"status": {"configfile": {"settings": {"virtual_sdcard": {"path": "~/gcode_files"}}}}}
                },
                request=httpx.Request("GET", str(url)),
            )
        assert str(url) == "http://neptune.local:7125/server/files/list?root=gcodes"
        return httpx.Response(
            200,
            json={"result": [{"path": "cube.gcode", "size": 1234, "modified": 1710000000}]},
            request=httpx.Request("GET", str(url)),
        )

    def fake_post(url, **kwargs):
        payload = kwargs.get("json") or kwargs.get("data") or {}
        calls.append(("post", f"{url} {payload}"))
        return httpx.Response(200, json={"result": {}}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://neptune.local:7125", printer_model="Elegoo Neptune 4 Pro")

    assert client.list_files("/model") == [
        {
            "name": "cube.gcode",
            "type": "file",
            "size": 1234,
            "modified": "2024-03-09T16:00:00+00:00",
            "path": "/cube.gcode",
        }
    ]
    assert client.upload_file(gcode, "/model/cube.gcode") is True
    assert client.start_print("/model/cube.gcode") is True

    assert ("post", "http://neptune.local:7125/server/files/upload {'root': 'gcodes', 'path': ''}") in calls
    assert ("post", "http://neptune.local:7125/printer/print/start {'filename': 'cube.gcode'}") in calls


def test_moonraker_elegoo_maps_mks_gcode_paths_to_gcodes_root(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_get(url, *, headers, timeout):  # noqa: ARG001
        calls.append(("get", str(url)))
        if str(url).endswith("printer/objects/query?configfile"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "status": {"configfile": {"settings": {"virtual_sdcard": {"path": "~/printer_data/gcodes"}}}}
                    }
                },
                request=httpx.Request("GET", str(url)),
            )
        assert str(url) == "http://neptune.local:7125/server/files/gcodes/cube.gcode"
        return httpx.Response(200, content=b"G28\n", request=httpx.Request("GET", str(url)))

    def fake_post(url, **kwargs):
        calls.append(("post", f"{url} {kwargs.get('json') or {}}"))
        return httpx.Response(200, json={"result": {}}, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    client = MoonrakerPrinterClient("http://neptune.local:7125", printer_model="Elegoo Neptune 4 Pro")

    assert client.download_file("/home/mks/printer_data/gcodes/cube.gcode") == b"G28\n"
    assert client.delete_file("/home/mks/gcode_files/cube.gcode") is True
    assert client.start_print("/home/mks/printer_data/gcodes/cube.gcode") is True

    assert ("post", "http://neptune.local:7125/server/files/delete_file {'path': 'gcodes/cube.gcode'}") in calls
    assert ("post", "http://neptune.local:7125/printer/print/start {'filename': 'cube.gcode'}") in calls


def test_prusalink_lists_uploads_and_starts_print(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []
    gcode = tmp_path / "cube.bgcode"
    gcode.write_text("G28\n", encoding="utf-8")

    def fake_request(method, url, **kwargs):  # noqa: ARG001
        calls.append((method.lower(), str(url)))
        if method.lower() == "get":
            return httpx.Response(
                200,
                json={"children": [{"name": "cube.bgcode", "type": "FILE", "size": 55}]},
                request=httpx.Request(method, str(url)),
            )
        return httpx.Response(204, request=httpx.Request(method, str(url)))

    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: fake_request("get", url, **kwargs))
    monkeypatch.setattr(httpx, "put", lambda url, **kwargs: fake_request("put", url, **kwargs))
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: fake_request("post", url, **kwargs))
    client = PrusaLinkPrinterClient("http://prusa.local", password="secret")

    assert client.list_files("/") == [
        {"name": "cube.bgcode", "type": "file", "size": 55, "modified": None, "path": "/cube.bgcode"}
    ]
    assert client.upload_file(gcode, "/cube.bgcode") is True
    assert client.start_print("/cube.bgcode") is True
    assert ("put", "http://prusa.local/api/v1/files/usb/cube.bgcode") in calls
    assert ("post", "http://prusa.local/api/v1/files/usb/cube.bgcode") in calls


def test_prusalink_upload_uses_digest_when_detected(monkeypatch, tmp_path):
    uploaded: list[tuple[str, type, dict[str, str]]] = []
    gcode = tmp_path / "cube.gcode"
    gcode.write_text("G28\n", encoding="utf-8")

    def fake_put(url, *, auth, headers, timeout, content):  # noqa: ARG001
        uploaded.append((str(url), type(auth), headers))
        return httpx.Response(204, request=httpx.Request("PUT", str(url)))

    monkeypatch.setattr(httpx, "put", fake_put)
    client = PrusaLinkPrinterClient("http://prusa.local", password="secret", api_mode="modern", auth_mode="digest")

    assert client.upload_file(gcode, "/cube.gcode") is True
    assert uploaded == [
        (
            "http://prusa.local/api/v1/files/usb/cube.gcode",
            httpx.DigestAuth,
            {"Content-Type": "application/octet-stream"},
        )
    ]


def test_prusalink_lifecycle_callbacks_fire_on_status_transitions(monkeypatch):
    statuses = [
        {
            "printer": {"state": "READY", "temp_nozzle": 25, "target_nozzle": 0, "temp_bed": 24, "target_bed": 0},
            "job": {},
        },
        {
            "printer": {
                "state": "PRINTING",
                "temp_nozzle": 210,
                "target_nozzle": 215,
                "temp_bed": 60,
                "target_bed": 60,
            },
            "job": {"id": 42, "progress": 12.5, "time_remaining": 1200},
        },
        {
            "printer": {"state": "FINISHED", "temp_nozzle": 180, "target_nozzle": 0, "temp_bed": 45, "target_bed": 0},
            "job": {"id": 42, "progress": 100, "time_remaining": 0},
        },
    ]
    job_details = [
        {},
        {
            "id": 42,
            "state": "PRINTING",
            "progress": 12.5,
            "time_remaining": 1200,
            "file": {"display_name": "mk4s_benchy.gcode"},
        },
        {
            "id": 42,
            "state": "FINISHED",
            "progress": 100,
            "time_remaining": 0,
            "file": {"display_name": "mk4s_benchy.gcode"},
        },
    ]

    def fake_get(url, *, auth, headers, timeout):  # noqa: ARG001
        if str(url).endswith("/api/v1/status"):
            payload = statuses.pop(0)
        else:
            payload = job_details.pop(0)
        return httpx.Response(200, json=payload, request=httpx.Request("GET", str(url)))

    starts: list[dict] = []
    completes: list[dict] = []
    states: list[str] = []
    bed_temps: list[float] = []
    monkeypatch.setattr(httpx, "get", fake_get)
    client = PrusaLinkPrinterClient(
        "http://prusa.local",
        password="dummy-prusalink-password",
        on_state_change=lambda state: states.append(state.state),
        on_print_start=starts.append,
        on_print_complete=completes.append,
        on_bed_temp_update=bed_temps.append,
    )

    assert client.request_status_update() is True
    assert starts == []
    assert completes == []

    assert client.request_status_update() is True
    assert starts == [
        {
            "filename": "mk4s_benchy.gcode",
            "subtask_name": "mk4s_benchy.gcode",
            "progress": 12.5,
            "remaining_time": 1200,
            "status": "RUNNING",
        }
    ]

    assert client.request_status_update() is True
    assert len(completes) == 1
    actual_time_seconds = completes[0].pop("actual_time_seconds")
    assert isinstance(actual_time_seconds, int)
    assert actual_time_seconds >= 0
    assert completes == [
        {
            "filename": "mk4s_benchy.gcode",
            "subtask_name": "mk4s_benchy.gcode",
            "progress": 100.0,
            "remaining_time": None,
            "status": "completed",
        }
    ]
    assert states == ["IDLE", "RUNNING", "FINISH"]
    assert bed_temps == [24.0, 60.0, 45.0]


def test_prusalink_factory_wires_lifecycle_callbacks():
    printer = SimpleNamespace(
        provider="prusalink",
        api_url="http://prusa.local",
        auth_token="dummy-prusalink-password",
        ip_address="prusa.local",
        provider_options=None,
    )
    callbacks = {
        "on_state_change": object(),
        "on_print_start": object(),
        "on_print_complete": object(),
        "on_bed_temp_update": object(),
    }

    client = create_printer_client(printer, **callbacks)

    assert isinstance(client, PrusaLinkPrinterClient)
    assert client.on_state_change is callbacks["on_state_change"]
    assert client.on_print_start is callbacks["on_print_start"]
    assert client.on_print_complete is callbacks["on_print_complete"]
    assert client.on_bed_temp_update is callbacks["on_bed_temp_update"]
