from backend.app.services.printer_providers.elegoo_sdcp import ElegooSDCPPrinterClient


def test_elegoo_sdcp_pause_resume_stop_send_job_control_commands(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr(
        client,
        "_send_command",
        lambda command: sent_commands.append(command) or {"Data": {"Data": {"Ack": 0}}},
    )

    assert client.pause_print() is True
    assert client.resume_print() is True
    assert client.stop_print() is True

    assert [command["Data"]["Cmd"] for command in sent_commands] == [129, 131, 130]
    assert [command["Data"]["From"] for command in sent_commands] == [1, 1, 1]
    assert [command["Topic"] for command in sent_commands] == [
        "sdcp/request/mainboard-id",
        "sdcp/request/mainboard-id",
        "sdcp/request/mainboard-id",
    ]
    assert [command["Data"]["Data"] for command in sent_commands] == [{}, {}, {}]


def test_elegoo_sdcp_job_control_returns_false_when_ack_rejected(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr(client, "_send_command", lambda command: {"Data": {"Data": {"Ack": 1}}})

    assert client.pause_print() is False
