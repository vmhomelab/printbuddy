import httpx

from backend.app.services.printer_providers.prusalink import PrusaLinkPrinterClient


def test_prusalink_send_gcode_returns_false_when_control_endpoint_is_missing(monkeypatch):
    client = PrusaLinkPrinterClient(base_url="http://prusa.local", password="secret")

    def fake_request(method, path, *, json_payload=None):  # noqa: ARG001
        request = httpx.Request(method.upper(), f"http://prusa.local/{path}")
        return httpx.Response(404, request=request)

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.send_gcode("G28") is False
