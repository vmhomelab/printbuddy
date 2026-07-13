from backend.app.services.printer_providers.elegoo_sdcp import (
    ElegooSDCPPrinterClient,
    _map_sdcp_status,
)


def test_sdcp_status_mapping_keeps_code_3_conservative():
    assert _map_sdcp_status(1, {}) == "RUNNING"
    assert _map_sdcp_status(5, {}) == "RUNNING"
    assert _map_sdcp_status(7, {}) == "PAUSE"
    assert _map_sdcp_status(4, {}) == "FINISH"
    assert _map_sdcp_status(9, {}) == "FINISH"
    assert _map_sdcp_status(3, {"Progress": 42}) == "FAILED"
    assert _map_sdcp_status(3, {"Progress": 0}) == "IDLE"


def test_elegoo_sdcp_client_normalizes_status_payload(monkeypatch):
    client = ElegooSDCPPrinterClient("http://centauri.local")

    monkeypatch.setattr(
        client,
        "_query_status",
        lambda: {
            "Topic": "sdcp/status/MAINBOARD123",
            "Data": {
                "Status": {
                    "Status": 5,
                    "PrintInfo": {
                        "Filename": "benchy.gcode",
                        "Progress": 0.375,
                        "RemainingTime": 14,
                        "CurrentLayer": 23,
                        "TotalLayer": 120,
                    },
                    "TempOfNozzle": {"Temp": 214.5, "TargetTemp": 220},
                    "TempOfHotbed": {"Temp": 59.8, "TargetTemp": 60},
                }
            },
        },
    )

    assert client.request_status_update() is True
    assert client.state.connected is True
    assert client.state.state == "RUNNING"
    assert client.state.current_print == "benchy.gcode"
    assert client.state.progress == 37.5
    assert client.state.remaining_time == 14
    assert client.state.layer_num == 23
    assert client.state.total_layers == 120
    assert client.state.temperatures == {
        "nozzle": 214.5,
        "nozzle_target": 220.0,
        "bed": 59.8,
        "bed_target": 60.0,
    }


def test_elegoo_sdcp_client_connect_works_without_udp_discovery(monkeypatch):
    client = ElegooSDCPPrinterClient("10.17.10.50")
    monkeypatch.setattr(client, "discover", lambda: (_ for _ in ()).throw(TimeoutError("udp timeout")))
    monkeypatch.setattr(client, "_query_status", lambda: {"Data": {"Status": {"Status": 0}}})

    client.connect()

    assert client.state.connected is True
    assert client.state.state == "IDLE"


def test_elegoo_sdcp_client_normalizes_url_host():
    client = ElegooSDCPPrinterClient("http://10.17.10.50:3030/websocket")

    assert client.host == "10.17.10.50"
    assert client.websocket_url == "ws://10.17.10.50:3030/websocket"
