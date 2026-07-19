import httpx

from backend.app.services.printer_providers import prusalink
from backend.app.services.printer_providers.prusalink import PrusaLinkPrinterClient, _normalize_prusalink_file_meta


def test_prusalink_job_file_meta_is_normalized_into_lifecycle_payload():
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")

    client._apply_job_detail(
        {
            "id": 42,
            "state": "PRINTING",
            "progress": 12.5,
            "file": {
                "display_name": "book_stand.bgcode",
                "meta": {
                    "filament_type": "PETG",
                    "filament used [g]": 96,
                    "filament used [mm]": 31470,
                    "filament cost": 2.4,
                    "estimated_print_time": 18171,
                    "filament used [g] per tool": [96, 0],
                    "filament_type per tool": ["PETG", "PLA"],
                },
            },
        }
    )

    payload = client._build_lifecycle_payload()

    assert payload["filename"] == "book_stand.bgcode"
    assert payload["file_metadata"]["source"] == "prusalink_file_meta"
    assert payload["file_metadata"]["filament_used_grams"] == 96.0
    assert payload["file_metadata"]["filament_used_mm"] == 31470.0
    assert payload["file_metadata"]["filament_type"] == "PETG"
    assert payload["file_metadata"]["filament_cost"] == 2.4
    assert payload["file_metadata"]["print_time_seconds"] == 18171
    assert payload["file_metadata"]["filament_slots"] == [{"slot_id": 1, "used_g": 96.0, "type": "PETG"}]


def test_prusalink_refresh_current_file_metadata_fetches_job_without_lifecycle_callbacks(monkeypatch):
    start_payloads = []
    client = PrusaLinkPrinterClient(
        base_url="http://prusa.local",
        password="secret",
        on_print_start=start_payloads.append,
    )

    def fake_get(path):
        assert path == "api/v1/job"
        return {
            "id": 42,
            "state": "PRINTING",
            "file": {
                "display_name": "late-meta.bgcode",
                "meta": {
                    "filament_type": "PETG",
                    "filament used [g]": 96,
                    "filament cost": 2.4,
                },
            },
        }

    monkeypatch.setattr(client, "_get", fake_get)

    metadata = client.refresh_current_file_metadata()

    assert start_payloads == []
    assert client.state.subtask_name == "late-meta.bgcode"
    assert metadata["source"] == "prusalink_file_meta"
    assert metadata["filament_used_grams"] == 96.0
    assert metadata["filament_type"] == "PETG"
    assert metadata["filament_cost"] == 2.4


def test_prusalink_refresh_current_file_metadata_falls_back_to_file_endpoint(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")
    calls = []

    def fake_get(path):
        calls.append(path)
        if path == "api/v1/job":
            return {
                "id": 104,
                "state": "PRINTING",
                "file": {
                    "refs": {"download": "/usb/2LAYER~1.GCO"},
                    "name": "2LAYER~1.GCO",
                    "display_name": "2 layer cube.gcode",
                    "path": "/usb",
                },
            }
        if path == "api/v1/files/usb/2LAYER~1.GCO":
            return {
                "name": "2LAYER~1.GCO",
                "meta": {
                    "filament_type": "PETG",
                    "filament used [g]": 12.5,
                    "filament cost": 0.38,
                },
            }
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_get", fake_get)

    metadata = client.refresh_current_file_metadata()

    assert calls == ["api/v1/job", "api/v1/files/usb/2LAYER~1.GCO"]
    assert client.state.subtask_name == "2 layer cube.gcode"
    assert metadata["source"] == "prusalink_file_meta"
    assert metadata["filament_used_grams"] == 12.5
    assert metadata["filament_type"] == "PETG"
    assert metadata["filament_cost"] == 0.38


def test_prusalink_file_meta_normalizer_handles_empty_meta():
    assert _normalize_prusalink_file_meta(None) == {}
    assert _normalize_prusalink_file_meta({}) == {}


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


def test_prusalink_fractional_progress_is_normalized_for_notifications_and_cards(monkeypatch):
    """CORE One / PrusaLink can report job progress as 0..1; Printbuddy expects 0..100 percent."""
    observed_states = []
    client = PrusaLinkPrinterClient(
        base_url="http://prusa.local",
        password="secret",
        on_state_change=lambda state: observed_states.append(state.progress),
    )

    statuses = iter(
        [
            {
                "printer": {"state": "PRINTING"},
                "job": {"id": 42, "progress": 0.995, "time_remaining": 120},
            },
        ]
    )
    job_details = iter(
        [
            {
                "id": 42,
                "state": "PRINTING",
                "progress": 0.995,
                "time_remaining": 120,
                "file": {"display_name": "almost-done.bgcode"},
            },
        ]
    )

    def fake_get(path):
        if path == "api/v1/status":
            return next(statuses)
        if path == "api/v1/job":
            return next(job_details)
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.request_status_update() is True

    assert client.state.progress == 99.5
    assert observed_states == [99.5]


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
    assert put_urls == ["http://prusa.local/api/v1/files/usb/Love%20Paw%20Print.gcode"]


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


def test_prusalink_list_storages_normalizes_usb_local_and_unavailable_sdcard(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")

    def fake_get(path):
        assert path == "api/v1/storage"
        return {
            "storage_list": [
                {"path": "/local", "name": "Internal", "type": "LOCAL", "available": True},
                {"path": "/usb", "name": "Mock USB", "type": "USB", "available": True, "free_space": 1234},
                {"path": "/sdcard", "name": "SD Card", "type": "SDCARD", "available": False},
            ]
        }

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.list_storages() == [
        {
            "id": "local",
            "type": "LOCAL",
            "name": "Internal",
            "path": "/local",
            "available": True,
            "read_only": False,
            "used_bytes": None,
            "free_bytes": None,
        },
        {
            "id": "usb",
            "type": "USB",
            "name": "Mock USB",
            "path": "/usb",
            "available": True,
            "read_only": False,
            "used_bytes": None,
            "free_bytes": 1234,
        },
        {
            "id": "sdcard",
            "type": "SDCARD",
            "name": "SD Card",
            "path": "/sdcard",
            "available": False,
            "read_only": False,
            "used_bytes": None,
            "free_bytes": None,
        },
    ]


def test_prusalink_list_files_uses_explicit_storage_without_default_discovery(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")
    requested_paths: list[str] = []

    def fake_get(path):
        requested_paths.append(path)
        return {
            "children": [
                {"display_name": "Jobs", "type": "FOLDER"},
                {"display_name": "Part A.bgcode", "type": "PRINT_FILE", "size": 42},
            ]
        }

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.list_files("/queued jobs", storage="local") == [
        {"name": "Jobs", "type": "directory", "size": None, "modified": None, "path": "/queued jobs/Jobs"},
        {"name": "Part A.bgcode", "type": "file", "size": 42, "modified": None, "path": "/queued jobs/Part A.bgcode"},
    ]
    assert requested_paths == ["api/v1/files/local/queued%20jobs"]


def test_prusalink_start_print_uses_explicit_storage_namespace(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")
    posted_paths: list[str] = []

    def fake_request(method, path, *, json_payload=None):  # noqa: ARG001
        posted_paths.append(f"{method.upper()} {path}")
        return httpx.Response(204, request=httpx.Request(method.upper(), f"http://prusa.local/{path}"))

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.start_print("nested/Part A.bgcode", storage="local") is True

    assert posted_paths == ["POST api/v1/files/local/nested/Part%20A.bgcode"]
