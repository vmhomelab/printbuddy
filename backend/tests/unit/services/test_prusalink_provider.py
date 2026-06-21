import httpx

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
