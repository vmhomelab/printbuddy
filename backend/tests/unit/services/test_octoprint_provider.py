"""OctoPrint provider tests.

The JSON fixtures in ``backend/tests/_fixtures/octoprint`` were recorded from
OctoPrint 1.11.8 driving its bundled virtual printer.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app.schemas.printer import PrinterCreate
from backend.app.services.printer_providers import _http_common
from backend.app.services.printer_providers.factory import create_printer_client
from backend.app.services.printer_providers.octoprint import (
    OctoPrintAuthError,
    OctoPrintPrinterClient,
    _map_octoprint_flags,
)

FIXTURES = Path(__file__).resolve().parents[2] / "_fixtures" / "octoprint"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeOctoPrint:
    """Route httpx.request calls to canned (status, json) responses."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, object]] | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[dict] = []

    def __call__(self, method, url, *, headers=None, timeout=None, **kwargs):  # noqa: ARG002
        path = httpx.URL(url).path
        self.calls.append({"method": method, "path": path, "headers": headers or {}, **kwargs})
        status, body = self.routes.get((method, path), (404, {"error": "not found"}))
        request = httpx.Request(method, url)
        if body is None:
            return httpx.Response(status, request=request)
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, request=request)
        return httpx.Response(status, json=body, request=request)

    def status(self, printer: str, job: str) -> None:
        printer_status = 409 if printer == "printer_offline" else 200
        self.routes[("GET", "/api/printer")] = (printer_status, _fixture(printer))
        self.routes[("GET", "/api/job")] = (200, _fixture(job))


@pytest.fixture
def fake(monkeypatch):
    server = FakeOctoPrint()
    monkeypatch.setattr(httpx, "request", server)
    return server


@pytest.fixture
def client():
    return OctoPrintPrinterClient("http://octopi.local", api_key="secret")


def test_factory_creates_octoprint_client_with_default_port():
    printer = SimpleNamespace(provider="octoprint", api_url=None, auth_token="key", ip_address="192.168.1.60")

    client = create_printer_client(printer)

    assert isinstance(client, OctoPrintPrinterClient)
    assert client.base_url == "http://192.168.1.60:5000/"
    assert client.api_key == "key"


@pytest.mark.parametrize(
    ("api_url", "expected_url", "expected_host"),
    [
        ("octopi.local", "http://octopi.local", "octopi.local"),
        ("http://192.168.1.60:5000/", "http://192.168.1.60:5000", "192.168.1.60"),
        ("https://print.example.org/octoprint", "https://print.example.org/octoprint", "print.example.org"),
    ],
)
def test_octoprint_printer_can_be_created_from_url_only(api_url, expected_url, expected_host):
    printer = PrinterCreate(name="Ender 3", provider="octoprint", api_url=api_url, auth_token="key")

    assert printer.api_url == expected_url
    assert printer.ip_address == expected_host
    assert printer.serial_number.startswith("OCTOPRINT-")


def test_octoprint_printer_can_be_created_with_ip_and_api_key_only():
    printer = PrinterCreate(name="Ender 3", provider="octoprint", ip_address="192.168.1.60", auth_token="key")

    assert printer.provider == "octoprint"
    assert printer.serial_number == "OCTOPRINT-192-168-1-60"
    assert printer.access_code == "octoprint"
    assert printer.api_url == "http://192.168.1.60:5000"


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"operational": True, "ready": True}, "IDLE"),
        ({"operational": True, "printing": True}, "RUNNING"),
        # OctoPrint keeps printing=true while pausing / cancelling.
        ({"operational": True, "printing": True, "pausing": True}, "PAUSE"),
        ({"operational": True, "paused": True}, "PAUSE"),
        ({"operational": True, "printing": True, "cancelling": True}, "RUNNING"),
        ({"operational": True, "resuming": True}, "RUNNING"),
        ({"operational": True, "finishing": True}, "RUNNING"),
        ({"error": True, "closedOrError": True}, "FAILED"),
        ({"closedOrError": True}, "OFFLINE"),
        ({}, "OFFLINE"),
        (None, "unknown"),
    ],
)
def test_flags_map_to_printbuddy_states(flags, expected):
    assert _map_octoprint_flags(flags) == expected


def test_status_update_while_printing(fake, client):
    fake.status("printer_printing", "job_printing")

    client.request_status_update()

    assert client.state.connected is True
    assert client.state.state == "RUNNING"
    # completion is already a percentage; it must not be multiplied by 100.
    assert client.state.progress == pytest.approx(20.794, abs=0.01)
    assert client.state.subtask_name == "cube.gcode"
    assert client.state.gcode_file == "prints/cube.gcode"
    assert client.state.temperatures["nozzle_target"] == pytest.approx(200.0)
    assert client.state.temperatures["bed_target"] == pytest.approx(50.0)
    assert client.state.raw_data["file_metadata"]["print_time_seconds"] == 25
    assert client.state.raw_data["file_metadata"]["filament_used_mm"] == pytest.approx(5.9)
    status_call = next(call for call in fake.calls if call["path"] == "/api/printer")
    assert status_call["headers"] == {"X-Api-Key": "secret"}


def test_small_completion_values_are_not_scaled(fake, client):
    fake.status("printer_printing", "job_printing")
    job = _fixture("job_printing")
    job["progress"]["completion"] = 0.23
    fake.routes[("GET", "/api/job")] = (200, job)

    client.request_status_update()

    assert client.state.progress == pytest.approx(0.23)


def test_remaining_time_falls_back_to_estimate_when_octoprint_has_none(fake, client):
    fake.status("printer_printing", "job_printing")
    job = _fixture("job_printing")
    job["job"]["estimatedPrintTime"] = 3600
    job["progress"].update({"printTimeLeft": None, "printTime": 600})
    fake.routes[("GET", "/api/job")] = (200, job)

    client.request_status_update()

    assert client.state.remaining_time == 50


def test_paused_status(fake, client):
    fake.status("printer_paused", "job_paused")

    client.request_status_update()

    assert client.state.state == "PAUSE"


def test_printer_not_connected_to_octoprint_is_offline_not_an_error(fake, client):
    fake.status("printer_offline", "job_offline")

    assert client.request_status_update() is True

    assert client.state.state == "OFFLINE"
    assert client.state.connected is False
    assert client.state.temperatures == {}


def test_check_staleness_reports_unreachable_octoprint(monkeypatch, client):
    def unreachable(*args, **kwargs):  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", unreachable)

    assert client.check_staleness() is False


def _lifecycle_client(events: list) -> OctoPrintPrinterClient:
    return OctoPrintPrinterClient(
        "http://octopi.local",
        api_key="secret",
        on_print_start=lambda payload: events.append(("start", payload)),
        on_print_complete=lambda payload: events.append(("complete", payload)),
    )


def test_finished_print_reports_completed_once(fake, monkeypatch):
    times = iter([100.0, 160.0])
    monkeypatch.setattr(_http_common.time, "monotonic", lambda: next(times))
    events: list = []
    client = _lifecycle_client(events)

    for printer, job in [
        ("printer_idle", "job_offline"),
        ("printer_printing", "job_printing"),
        ("printer_paused", "job_paused"),
        ("printer_printing", "job_printing"),
        ("printer_idle", "job_finished"),
    ]:
        fake.status(printer, job)
        client.request_status_update()

    assert [kind for kind, _ in events] == ["start", "complete"]
    complete = events[1][1]
    assert complete["status"] == "completed"
    assert complete["filename"] == "root.gcode"
    assert complete["actual_time_seconds"] == 60


def test_cancelled_print_reports_stopped(fake):
    events: list = []
    client = _lifecycle_client(events)

    for printer, job in [
        ("printer_idle", "job_offline"),
        ("printer_printing", "job_printing"),
        ("printer_idle", "job_cancelled"),
    ]:
        fake.status(printer, job)
        client.request_status_update()

    assert [kind for kind, _ in events] == ["start", "complete"]
    assert events[1][1]["status"] == "stopped"


def test_serial_disconnect_during_print_reports_failed(fake):
    events: list = []
    client = _lifecycle_client(events)

    for printer, job in [
        ("printer_idle", "job_offline"),
        ("printer_printing", "job_printing"),
        ("printer_offline", "job_offline"),
    ]:
        fake.status(printer, job)
        client.request_status_update()

    assert events[-1][0] == "complete"
    assert events[-1][1]["status"] == "failed"


def test_connect_requires_an_octoprint_version_response(fake, client):
    fake.routes[("GET", "/api/version")] = (200, {"api": "0.1", "server": "1.0", "text": "SomethingElse"})

    with pytest.raises(RuntimeError, match="OctoPrint"):
        client.connect()


def test_connect_reads_version_and_status(fake, client):
    fake.routes[("GET", "/api/version")] = (200, _fixture("version"))
    fake.status("printer_idle", "job_offline")

    client.connect()

    assert client.state.firmware_version == "1.11.8"
    assert client.state.state == "IDLE"


def test_verify_api_key_rejects_anonymous_fallback(fake, client):
    fake.routes[("GET", "/api/currentuser")] = (200, _fixture("currentuser_invalid"))

    with pytest.raises(OctoPrintAuthError, match="did not accept"):
        client.verify_api_key()


def test_verify_api_key_lists_missing_permissions(fake, client):
    fake.routes[("GET", "/api/currentuser")] = (200, _fixture("currentuser_limited"))

    with pytest.raises(OctoPrintAuthError) as exc_info:
        client.verify_api_key()

    assert exc_info.value.missing_permissions == ["CONTROL", "PRINT", "FILES_UPLOAD", "FILES_DELETE", "FILES_SELECT"]


def test_verify_api_key_accepts_admin(fake, client):
    fake.routes[("GET", "/api/currentuser")] = (200, {"name": "admin", "permissions": ["ADMIN"], "groups": []})

    assert client.verify_api_key()["name"] == "admin"


@pytest.mark.parametrize(
    ("method_name", "payload"),
    [
        ("pause_print", {"command": "pause", "action": "pause"}),
        ("resume_print", {"command": "pause", "action": "resume"}),
        ("stop_print", {"command": "cancel"}),
    ],
)
def test_job_commands_post_explicit_actions(fake, client, method_name, payload):
    fake.routes[("POST", "/api/job")] = (204, None)

    assert getattr(client, method_name)() is True

    assert fake.calls[-1]["json"] == payload


def test_job_command_conflict_returns_false(fake, client):
    fake.routes[("POST", "/api/job")] = (409, {"error": "Printer is not operational"})

    assert client.pause_print() is False


def test_start_print_selects_and_prints_file(fake, client):
    fake.routes[("POST", "/api/files/local/prints/my cube.gcode")] = (204, None)

    assert client.start_print("/prints/my cube.gcode") is True

    assert fake.calls[-1]["json"] == {"command": "select", "print": True}


def test_list_files_at_storage_root(fake, client):
    fake.routes[("GET", "/api/files/local")] = (200, _fixture("files_local_recursive"))

    files = client.list_files("/")

    by_name = {entry["name"]: entry for entry in files}
    assert by_name["root.gcode"] == {
        "name": "root.gcode",
        "type": "file",
        "size": 1914,
        "modified": 1793375603,
        "path": "/root.gcode",
        "print_time_seconds": 25,
    }
    assert by_name["prints"]["type"] == "directory"
    assert by_name["prints"]["path"] == "/prints"


def test_list_files_in_folder(fake, client):
    fake.routes[("GET", "/api/files/local/prints")] = (200, _fixture("files_folder_prints"))

    files = client.list_files("/prints")

    assert [(entry["name"], entry["path"]) for entry in files] == [("cube.gcode", "/prints/cube.gcode")]


def test_upload_file_posts_multipart_with_target_folder(fake, client, tmp_path):
    fake.routes[("POST", "/api/files/local")] = (201, _fixture("upload_response"))
    local = tmp_path / "cube.gcode"
    local.write_text("G28\n")

    assert client.upload_file(local, "/prints/cube.gcode") is True

    call = fake.calls[-1]
    assert call["data"] == {"path": "prints"}
    filename, _fh, content_type = call["files"]["file"]
    assert filename == "cube.gcode"
    assert content_type == "application/octet-stream"


def test_download_and_delete_file(fake, client):
    fake.routes[("GET", "/downloads/files/local/prints/cube.gcode")] = (200, b"G28\n")
    fake.routes[("DELETE", "/api/files/local/prints/cube.gcode")] = (204, None)

    assert client.download_file("/prints/cube.gcode") == b"G28\n"
    assert client.delete_file("/prints/cube.gcode") is True
    assert client.delete_file("/prints/missing.gcode") is False


def test_sdcard_storage_is_addressed_explicitly(fake, client):
    fake.routes[("GET", "/api/files/sdcard")] = (200, {"files": []})

    assert client.list_files("/", storage="sdcard") == []
    assert fake.calls[-1]["path"] == "/api/files/sdcard"


@pytest.mark.parametrize(("speed", "gcode"), [(100, "M106 S255"), (50, "M106 S128"), (0, "M107")])
def test_part_fan_speed_maps_to_m106(fake, client, speed, gcode):
    fake.routes[("POST", "/api/printer/command")] = (204, None)

    assert client.set_fan_speed("part", speed) is True

    assert fake.calls[-1]["json"] == {"commands": [gcode]}


def test_other_fans_are_not_supported(client):
    with pytest.raises(ValueError):
        client.set_fan_speed("chamber", 50)


def test_home_axes_uses_printhead_command(fake, client):
    fake.routes[("POST", "/api/printer/printhead")] = (204, None)

    assert client.home_axes(["x", "y"]) is True

    assert fake.calls[-1]["json"] == {"command": "home", "axes": ["x", "y"]}


def test_discover_webcam_resolves_relative_urls_and_rotation(fake):
    client = OctoPrintPrinterClient("http://octopi.local/octoprint/", api_key="secret")
    fake.routes[("GET", "/octoprint/api/settings")] = (200, _fixture("settings_webcam"))

    webcam = client.discover_webcam()

    assert webcam == {
        # "/webcam/..." is host-relative, as in OctoPrint's own web UI.
        "camera_url": "http://octopi.local/webcam/?action=stream",
        "camera_snapshot_url": "http://octopi.local:8080/?action=snapshot",
        "camera_type": "mjpeg",
        # rotate90 (counter-clockwise) + flipH/flipV (180) = 90 clockwise.
        "camera_rotation": 90,
    }


def test_discover_webcam_falls_back_to_legacy_settings(fake, client):
    fake.routes[("GET", "/api/settings")] = (
        200,
        {"webcam": {"webcamEnabled": True, "streamUrl": "", "snapshotUrl": "/webcam/?action=snapshot"}},
    )

    webcam = client.discover_webcam()

    assert webcam["camera_url"] == "http://octopi.local/webcam/?action=snapshot"
    assert webcam["camera_type"] == "snapshot"
    assert webcam["camera_rotation"] == 0


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"webcam": {"webcamEnabled": False, "streamUrl": "/webcam/?action=stream"}},
        {"webcam": {"webcamEnabled": True, "webcams": [{"name": "classic", "compat": {"stream": ""}}]}},
    ],
)
def test_discover_webcam_returns_none_without_a_camera(fake, client, settings):
    fake.routes[("GET", "/api/settings")] = (200, settings)

    assert client.discover_webcam() is None
