import httpx

from backend.app.services.printer_providers import prusalink
from backend.app.services.printer_providers.prusalink import PrusaLinkPrinterClient


def test_prusalink_send_gcode_returns_false_when_control_endpoint_is_missing(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")

    def fake_request(method, path, *, json_payload=None):  # noqa: ARG001
        request = httpx.Request(method.upper(), f"http://prusa.local/{path}")
        return httpx.Response(404, request=request)

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.send_gcode("G28") is False


def test_prusalink_finished_job_state_emits_completed_even_without_full_progress(monkeypatch):
    completion_payloads = []
    client = PrusaLinkPrinterClient(
        base_url="http://prusa.local",
        password="secret",
        on_print_complete=completion_payloads.append,
    )
    responses = iter(
        [
            {
                "printer": {"state": "PRINTING"},
                "job": {"id": 42, "progress": 42.0, "time_remaining": 120},
            },
            {"id": 42, "state": "PRINTING", "progress": 42.0, "time_remaining": 120},
            {
                "printer": {"state": "FINISHED"},
                "job": {"id": 42, "progress": 0.0, "time_remaining": 0},
            },
            {
                "id": 42,
                "state": "FINISHED",
                "progress": 0.0,
                "time_remaining": 0,
                "file": {"display_name": "finished-test.bgcode"},
            },
        ]
    )

    def fake_get(path):  # noqa: ARG001
        return next(responses)

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.request_status_update() is True
    assert completion_payloads == []

    assert client.request_status_update() is True

    assert completion_payloads == [
        {
            "filename": "finished-test.bgcode",
            "subtask_name": "finished-test.bgcode",
            "progress": 0.0,
            "remaining_time": None,
            "status": "completed",
        }
    ]


def test_prusalink_upload_uses_discovered_usb_storage(monkeypatch, tmp_path):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")
    local_file = tmp_path / "Love Paw Print.gcode"
    local_file.write_text("G28\n", encoding="utf-8")
    requested_paths: list[str] = []
    put_urls: list[str] = []

    def fake_get(path):
        requested_paths.append(path)
        if path == "api/v1/storage":
            return {
                "storage_list": [{"path": "/usb", "name": "usb", "type": "USB", "read_only": False, "available": True}]
            }
        raise AssertionError(f"unexpected path: {path}")

    def fake_put(url, **kwargs):  # noqa: ARG001
        put_urls.append(str(url))
        return httpx.Response(201, request=httpx.Request("PUT", url))

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(httpx, "put", fake_put)

    assert client.upload_file(local_file, "Love Paw Print.gcode") is True

    assert requested_paths == ["api/v1/storage"]
    assert put_urls == ["http://prusa.local/api/v1/files/usb/Love%20Paw%20Print.gcode?overwrite=0"]


def test_prusalink_start_print_uses_discovered_usb_storage(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")
    posted_paths: list[str] = []

    def fake_get(path):
        if path == "api/v1/storage":
            return {
                "storage_list": [{"path": "/usb", "name": "usb", "type": "USB", "read_only": False, "available": True}]
            }
        raise AssertionError(f"unexpected path: {path}")

    def fake_request(method, path, *, json_payload=None):  # noqa: ARG001
        posted_paths.append(f"{method.upper()} {path}")
        return httpx.Response(204, request=httpx.Request(method.upper(), f"http://prusa.local/{path}"))

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "_request", fake_request)

    assert client.start_print("Love Paw Print.gcode") is True

    assert posted_paths == ["POST api/v1/files/usb/Love%20Paw%20Print.gcode"]


def test_prusalink_storage_discovery_prefers_path_over_display_name(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")

    def fake_get(path):
        if path == "api/v1/storage":
            return {
                "storage_list": [
                    {
                        "path": "/usb",
                        "name": "Mock USB",
                        "type": "USB",
                        "read_only": False,
                        "available": True,
                    }
                ]
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.file_storage == "usb"


def test_prusalink_falls_back_to_usb_storage_when_storage_probe_fails(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")

    def fake_get(path):
        if path == "api/v1/storage":
            request = httpx.Request("GET", "http://prusa.local/api/v1/storage")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.file_storage == "usb"


def test_prusalink_completion_payload_includes_elapsed_time(monkeypatch):
    complete_payloads = []
    client = PrusaLinkPrinterClient(
        base_url="http://prusa.local",
        password="secret",
        on_print_complete=lambda payload: complete_payloads.append(payload),
    )

    statuses = iter(
        [
            {
                "printer": {"state": "READY"},
                "job": {},
            },
            {
                "printer": {"state": "PRINTING"},
                "job": {"progress": 10, "time_remaining": 3600},
            },
            {
                "printer": {"state": "FINISHED"},
                "job": {"progress": 100, "time_remaining": 0},
            },
        ]
    )
    job_details = iter(
        [
            {},
            {"state": "PRINTING", "progress": 10, "file": {"display_name": "Notification test.gcode"}},
            {"state": "FINISHED", "progress": 100, "file": {"display_name": "Notification test.gcode"}},
        ]
    )

    def fake_get(path):
        if path == "api/v1/status":
            return next(statuses)
        if path == "api/v1/job":
            return next(job_details)
        raise AssertionError(f"unexpected path: {path}")

    times = iter([100.0, 160.0])
    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(prusalink.time, "monotonic", lambda: next(times))

    client.request_status_update()  # baseline idle; no callbacks
    client.request_status_update()  # start; records monotonic 100.0
    client.request_status_update()  # finish; emits elapsed time

    assert complete_payloads == [
        {
            "filename": "Notification test.gcode",
            "subtask_name": "Notification test.gcode",
            "progress": 100.0,
            "remaining_time": None,
            "status": "completed",
            "actual_time_seconds": 60,
        }
    ]
