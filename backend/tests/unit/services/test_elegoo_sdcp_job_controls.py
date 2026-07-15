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


def test_elegoo_sdcp_set_chamber_light_sends_validated_status_data_payload(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr(
        client,
        "_send_command",
        lambda command: sent_commands.append(command) or {"Data": {"Data": {"Ack": 0}}},
    )

    assert client.set_chamber_light(True) is True
    assert client.set_chamber_light(False) is True

    assert [command["Data"]["Cmd"] for command in sent_commands] == [403, 403]
    assert [command["Data"]["From"] for command in sent_commands] == [1, 1]
    assert [command["Topic"] for command in sent_commands] == [
        "sdcp/request/mainboard-id",
        "sdcp/request/mainboard-id",
    ]
    assert [command["Data"]["Data"] for command in sent_commands] == [
        {"LightStatus": {"SecondLight": True, "RgbLight": [0, 0, 0]}},
        {"LightStatus": {"SecondLight": False, "RgbLight": [0, 0, 0]}},
    ]
    assert sent_commands[0]["Data"]["MainboardID"] == "mainboard-id"
    assert sent_commands[0]["Data"]["TimeStamp"] > 0


def test_elegoo_sdcp_set_chamber_light_returns_false_when_ack_rejected(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr(client, "_send_command", lambda command: {"Data": {"Data": {"Ack": 2}}})

    assert client.set_chamber_light(True) is False
