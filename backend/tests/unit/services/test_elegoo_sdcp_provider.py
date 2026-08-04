import hashlib

from backend.app.services.printer_providers.elegoo_sdcp import (
    ElegooSDCPPrinterClient,
    _map_sdcp_status,
)


def test_sdcp_status_mapping_keeps_code_3_conservative():
    assert _map_sdcp_status(1, {}) == "RUNNING"
    assert _map_sdcp_status(13, {}) == "RUNNING"
    assert _map_sdcp_status(16, {}) == "RUNNING"
    assert _map_sdcp_status(18, {}) == "RUNNING"
    assert _map_sdcp_status(21, {}) == "RUNNING"
    assert _map_sdcp_status(2, {}) == "PAUSE"
    assert _map_sdcp_status(4, {}) == "FINISH"
    assert _map_sdcp_status(9, {}) == "FINISH"
    assert _map_sdcp_status(3, {"CurrentTicks": 420, "TotalTicks": 1000}) == "FAILED"
    assert _map_sdcp_status(3, {"CurrentTicks": 0, "TotalTicks": 1000}) == "IDLE"


def test_elegoo_sdcp_client_normalizes_status_payload(monkeypatch):
    client = ElegooSDCPPrinterClient("http://centauri.local")

    monkeypatch.setattr(
        client,
        "_query_status",
        lambda: {
            "Topic": "sdcp/status/MAINBOARD123",
            "Data": {
                "Status": {
                    "Status": 13,
                    "PrintInfo": {
                        "Filename": "benchy.gcode",
                        "CurrentTicks": 375,
                        "TotalTicks": 1000,
                        "RemainTime": 14,
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


def test_elegoo_sdcp_client_normalizes_real_centauri_carbon_status_payload(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")

    monkeypatch.setattr(
        client,
        "_query_status",
        lambda: {
            "Status": {
                "CurrentStatus": [0],
                "TimeLapseStatus": 0,
                "TempOfHotbed": 33.0421938295653,
                "TempOfNozzle": 34.69525525186664,
                "TempOfBox": 31.48965520230296,
                "TempTargetHotbed": 0,
                "TempTargetNozzle": 0,
                "TempTargetBox": 0,
                "CurrentFanSpeed": {"ModelFan": 42, "AuxiliaryFan": 17, "BoxFan": 5},
                "LightStatus": {"SecondLight": 1, "RgbLight": [0, 0, 0]},
                "PrintInfo": {
                    "Status": 0,
                    "CurrentLayer": 0,
                    "TotalLayer": 0,
                    "CurrentTicks": 0,
                    "TotalTicks": 0,
                    "Filename": "",
                    "TaskId": "",
                    "PrintSpeedPct": 100,
                    "Progress": 0,
                },
            },
            "MainboardID": "4c8918d80103d46c00004c0000000000",
            "Topic": "sdcp/status/4c8918d80103d46c0000000000000",
        },
    )

    assert client.request_status_update() is True
    assert client.state.connected is True
    assert client.state.state == "IDLE"
    assert client.state.progress == 0.0
    assert client.state.layer_num == 0
    assert client.state.total_layers == 0
    assert client.state.temperatures == {
        "nozzle": 34.69525525186664,
        "nozzle_target": 0.0,
        "bed": 33.0421938295653,
        "bed_target": 0.0,
        "chamber": 31.48965520230296,
        "chamber_target": 0.0,
    }
    assert client.state.cooling_fan_speed == 42
    assert client.state.big_fan1_speed == 17
    assert client.state.big_fan2_speed == 5
    assert client.state.chamber_light is True


def test_elegoo_sdcp_client_clears_active_print_metadata_when_idle(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")
    payloads = iter(
        [
            {
                "Status": {
                    "CurrentStatus": [13],
                    "TempOfHotbed": 70,
                    "TempOfNozzle": 250,
                    "PrintInfo": {
                        "Status": 13,
                        "Filename": "finished-gridfinity-plate.gcode",
                        "Progress": 92,
                        "RemainTime": 12,
                        "CurrentLayer": 184,
                        "TotalLayer": 200,
                    },
                }
            },
            {
                "Status": {
                    "CurrentStatus": [0],
                    "TempOfHotbed": 32,
                    "TempOfNozzle": 34,
                    "PrintInfo": {
                        "Status": 0,
                        "Filename": "finished-gridfinity-plate.gcode",
                        "Progress": 0,
                        "RemainTime": 0,
                        "CurrentLayer": 200,
                        "TotalLayer": 200,
                    },
                }
            },
        ]
    )
    monkeypatch.setattr(client, "_query_status", lambda: next(payloads))

    assert client.request_status_update() is True
    assert client.state.state == "RUNNING"
    assert client.state.current_print == "finished-gridfinity-plate.gcode"

    assert client.request_status_update() is True
    assert client.state.state == "IDLE"
    assert client.state.current_print is None
    assert client.state.subtask_name is None
    assert client.state.gcode_file is None
    assert client.state.progress == 0.0
    assert client.state.remaining_time == 0
    assert client.state.layer_num == 0
    assert client.state.total_layers == 0


def test_elegoo_sdcp_chamber_displays_temp_target_box_when_actual_box_temp_missing(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")

    monkeypatch.setattr(
        client,
        "_query_status",
        lambda: {
            "Status": {
                "CurrentStatus": [13],
                "TempOfHotbed": 70,
                "TempOfNozzle": 250,
                "TempTargetHotbed": 70,
                "TempTargetNozzle": 250,
                "TempTargetBox": 45,
                "PrintInfo": {"Status": 13, "Filename": "test.gcode", "Progress": 25},
            }
        },
    )

    assert client.request_status_update() is True
    assert client.state.state == "RUNNING"
    assert client.state.temperatures["chamber"] == 45.0
    assert client.state.temperatures["chamber_target"] == 45.0


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


def test_elegoo_sdcp_upload_posts_sdcp_multipart_chunks(monkeypatch, tmp_path):
    payload = b"G28\n" + b"G1 X1 Y1\n" * 128
    local_file = tmp_path / "calibration.gcode"
    local_file.write_bytes(payload)
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"success": True}

        def raise_for_status(self):
            return None

    class FakeHTTPClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, data, files):
            calls.append({"url": url, "data": data, "files": files})
            return FakeResponse()

    monkeypatch.setattr("backend.app.services.printer_providers.elegoo_sdcp.httpx.Client", FakeHTTPClient)
    client = ElegooSDCPPrinterClient("192.168.1.181")

    assert client.upload_file(local_file, "/Remote_Name.gcode") is True

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "http://192.168.1.181:3030/uploadFile/upload"
    assert call["data"]["Offset"] == "0"
    assert call["data"]["TotalSize"] == str(len(payload))
    assert call["data"]["Check"] == "1"
    assert call["data"]["S-File-MD5"] == hashlib.md5(payload).hexdigest()
    assert call["files"]["File"][0] == "Remote_Name.gcode"
    assert call["files"]["File"][1] == payload


def test_elegoo_sdcp_start_print_sends_full_cmd_128_payload(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr("backend.app.services.printer_providers.elegoo_sdcp.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_confirm_print_started", lambda filename: True)
    monkeypatch.setattr(
        client,
        "_send_command",
        lambda command: sent_commands.append(command) or {"Data": {"Data": {"Ack": 0}}},
    )

    assert client.start_print("/local/calibration.gcode", bed_levelling=True) is True

    assert len(sent_commands) == 1
    command = sent_commands[0]
    assert "Topic" not in command
    assert command["Id"] == ""
    assert command["Data"]["Cmd"] == 128
    assert command["Data"]["From"] == 1
    assert command["Data"]["MainboardID"] == ""
    assert len(command["Data"]["RequestID"]) == 32
    assert "TimeStamp" in command["Data"]
    assert "Timestamp" not in command["Data"]
    assert command["Data"]["Data"] == {
        "Filename": "/local/calibration.gcode",
        "StartLayer": 0,
        "Calibration_switch": 1,
        "PrintPlatformType": 0,
        "Tlp_Switch": 0,
    }


def test_elegoo_sdcp_get_file_info_fetches_estimated_weight_and_time(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"

    def fake_send(command):
        sent_commands.append(command)
        return {
            "Data": {
                "Data": {
                    "Ack": 0,
                    "FileInfo": {
                        "Thumbnail": "http://192.168.1.181:80/thumbnail/bracket.gcode.png",
                        "EstTime": 2608,
                        "EstWeight": 9.79,
                    },
                }
            }
        }

    monkeypatch.setattr(client, "_send_command", fake_send)

    info = client.get_file_info("/local/bracket.gcode")

    assert info == {
        "path": "/local/bracket.gcode",
        "thumbnail": "http://192.168.1.181:80/thumbnail/bracket.gcode.png",
        "estimated_time_seconds": 2608,
        "estimated_weight_grams": 9.79,
    }
    command = sent_commands[0]
    assert command["Data"]["Cmd"] == 260
    assert command["Data"]["Data"] == {"Url": "/local/bracket.gcode"}
    assert command["Data"]["From"] == 1


def test_elegoo_sdcp_list_files_defaults_to_usb_and_normalizes_entries(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"

    def fake_send(command):
        sent_commands.append(command)
        return {
            "Data": {
                "Data": {
                    "Ack": 0,
                    "FileList": [
                        {
                            "name": "/usb/Calibration Cube",
                            "usedSize": 0,
                            "totalSize": 0,
                            "storageType": 1,
                            "type": 0,
                        },
                        {
                            "name": "/usb/benchy.gcode",
                            "usedSize": 123456,
                            "totalSize": 987654,
                            "storageType": 1,
                            "type": 1,
                        },
                    ],
                }
            }
        }

    monkeypatch.setattr(client, "_send_command", fake_send)

    assert client.list_files("/") == [
        {
            "name": "Calibration Cube",
            "type": "directory",
            "size": 0,
            "modified": None,
            "path": "/usb/Calibration Cube",
            "storage_type": "external",
        },
        {
            "name": "benchy.gcode",
            "type": "file",
            "size": 123456,
            "modified": None,
            "path": "/usb/benchy.gcode",
            "storage_type": "external",
        },
    ]
    command = sent_commands[0]
    assert command["Topic"] == "sdcp/request/mainboard-id"
    assert command["Data"]["Cmd"] == 258
    assert command["Data"]["Data"] == {"Url": "/usb/"}
    assert command["Data"]["From"] == 1
    assert command["Data"]["MainboardID"] == "mainboard-id"


def test_elegoo_sdcp_list_files_preserves_explicit_local_path(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr(
        client,
        "_send_command",
        lambda command: sent_commands.append(command) or {"Data": {"Data": {"Ack": 0, "FileList": []}}},
    )

    assert client.list_files("/local/cache") == []

    assert sent_commands[0]["Data"]["Data"] == {"Url": "/local/cache"}


def test_elegoo_sdcp_list_files_returns_empty_for_rejected_ack(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr(client, "_send_command", lambda command: {"Data": {"Data": {"Ack": 123, "FileList": []}}})

    assert client.list_files("/usb/") == []


def test_elegoo_sdcp_start_print_can_disable_bed_levelling(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr("backend.app.services.printer_providers.elegoo_sdcp.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_confirm_print_started", lambda filename: True)
    monkeypatch.setattr(
        client,
        "_send_command",
        lambda command: sent_commands.append(command) or {"Data": {"Data": {"Ack": 0}}},
    )

    assert client.start_print("calibration.gcode", bed_levelling=False) is True

    assert sent_commands[0]["Data"]["Data"]["Calibration_switch"] == 0


def test_elegoo_sdcp_start_print_uses_requested_print_platform_type(monkeypatch):
    sent_commands = []
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    monkeypatch.setattr("backend.app.services.printer_providers.elegoo_sdcp.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_confirm_print_started", lambda filename: True)
    monkeypatch.setattr(
        client,
        "_send_command",
        lambda command: sent_commands.append(command) or {"Data": {"Data": {"Ack": 0}}},
    )

    assert client.start_print("/local/calibration.gcode", print_platform_type=1) is True

    assert sent_commands[0]["Data"]["Data"]["PrintPlatformType"] == 1


def test_elegoo_sdcp_start_print_reconciles_command_timeout_with_active_status(monkeypatch):
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "printer-id"
    client.mainboard_id = "mainboard-id"
    client.state.state = "IDLE"
    monkeypatch.setattr("backend.app.services.printer_providers.elegoo_sdcp.time.sleep", lambda seconds: None)
    monkeypatch.setattr(client, "_send_command", lambda command: (_ for _ in ()).throw(TimeoutError("slow ack")))

    def fake_status_update():
        client.state.state = "RUNNING"
        client.state.gcode_file = "calibration.gcode"
        client.state.current_print = "calibration.gcode"
        return True

    monkeypatch.setattr(client, "request_status_update", fake_status_update)

    assert client.start_print("calibration.gcode") is True


def test_elegoo_sdcp_status_populates_connection_details():
    client = ElegooSDCPPrinterClient("192.168.1.181")
    client.printer_id = "979d4C788A4a78bC777A870F1A02867A"
    client.mainboard_id = "4c8918d80103d46c00004c0000000000"
    client.discovery_info = {
        "Id": client.printer_id,
        "MainboardID": client.mainboard_id,
        "ProtocolVersion": "V3.0.0",
        "FirmwareVersion": "V0.3.0-o",
        "MachineName": "Centauri Carbon",
        "BrandName": "ELEGOO",
    }

    assert client.connection_details == {
        "printer_id": "979d4C788A4a78bC777A870F1A02867A",
        "mainboard_id": "4c8918d80103d46c00004c0000000000",
        "protocol_version": "V3.0.0",
        "firmware_version": "V0.3.0-o",
        "machine_name": "Centauri Carbon",
        "brand_name": "ELEGOO",
    }
