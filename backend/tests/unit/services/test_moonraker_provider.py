from backend.app.services.printer_providers.moonraker import MoonrakerPrinterClient


def _moonraker_status_with_cfs(active_filament="A"):
    return {
        "print_stats": {
            "state": "printing",
            "filename": "Cube_PLA_19m27s.gcode",
            "print_duration": 120.0,
        },
        "virtual_sdcard": {"progress": 0.25},
        "display_status": {"progress": 0.25},
        "extruder": {"temperature": 215.0, "target": 220.0},
        "heater_bed": {"temperature": 59.0, "target": 60.0},
        "box": {
            "filament": 1,
            "state": "connect",
            "auto_refill": 1,
            "enable": 1,
            "same_material": [
                ["101001", "00A2989", ["T1A"], "PLA"],
                ["001001", "0fff014", ["T1B"], "PLA"],
                ["001001", "0ffffff", ["T1C"], "PLA"],
                ["001001", "09ea7ae", ["T1D"], "PLA"],
            ],
            "T1": {
                "state": "connect",
                "filament": active_filament,
                "temperature": "25",
                "dry_and_humidity": "48",
                "version": "1.4.2",
                "sn": "10000949645L325LWVB",
                "mode": "2",
                "remain_len": ["41", "100", "100", "100"],
                "color_value": ["00A2989", "0fff014", "0ffffff", "09ea7ae"],
                "material_type": ["101001", "001001", "001001", "001001"],
                "vender": [
                    "7C2250276A210100100A29890165000001000000",
                    "unknown",
                    "unknown",
                    "unknown",
                ],
                "change_color_num": ["0", -1, -1, -1],
            },
            "T2": {"state": "None"},
            "T3": {"state": "None"},
            "T4": {"state": "None"},
        },
        "filament_rack": {
            "remain_material_color": "0ffffff",
            "remain_material_type": "001001",
            "remain_material_velocity": 575.0,
        },
        "filament_switch_sensor filament_sensor": {"filament_detected": True},
    }


def test_moonraker_normalizes_creality_k2_cfs_box_to_ams_shape(monkeypatch):
    client = MoonrakerPrinterClient("http://k2-plus.local:7125", printer_model="Creality K2 Plus")
    status = _moonraker_status_with_cfs("A")
    base_status = {
        key: status[key] for key in ("print_stats", "virtual_sdcard", "display_status", "extruder", "heater_bed")
    }
    cfs_status = {key: status[key] for key in ("box", "filament_rack", "filament_switch_sensor filament_sensor")}
    monkeypatch.setattr(client, "_query_objects", lambda object_names: base_status)
    monkeypatch.setattr(client, "_query_cfs_status", lambda: cfs_status)
    monkeypatch.setattr(client, "_query_fan_status", lambda: {})

    assert client.request_status_update() is True

    assert client.state.state == "RUNNING"
    assert client.state.progress == 25.0
    assert client.state.raw_data["box"]["state"] == "connect"
    assert client.state.raw_data["filament_rack"]["remain_material_type"] == "001001"
    assert client.state.raw_data["cfs"]["active_slots"] == ["T1A"]
    assert client.state.tray_now == 0
    assert client.state.raw_data["cfs"]["filament_detected"] is True

    ams = client.state.raw_data["ams"]
    assert len(ams) == 1
    assert ams[0]["id"] == 0
    assert ams[0]["humidity"] == 48
    assert ams[0]["temp"] == 25
    assert ams[0]["name"] == "CFS T1"
    assert ams[0]["tray"] == [
        {
            "id": 0,
            "slot": "T1A",
            "tray_type": "PLA",
            "material_code": "101001",
            "tray_color": "#0A2989",
            "remain": 41,
            "active": True,
            "state": 11,
            "tray_uuid": "T1A",
            "tag_uid": "",
            "vendor": "7C2250276A210100100A29890165000001000000",
        },
        {
            "id": 1,
            "slot": "T1B",
            "tray_type": "PLA",
            "material_code": "001001",
            "tray_color": "#fff014",
            "remain": 100,
            "active": False,
            "state": 11,
            "tray_uuid": "T1B",
            "tag_uid": "",
            "vendor": "unknown",
        },
        {
            "id": 2,
            "slot": "T1C",
            "tray_type": "PLA",
            "material_code": "001001",
            "tray_color": "#ffffff",
            "remain": 100,
            "active": False,
            "state": 11,
            "tray_uuid": "T1C",
            "tag_uid": "",
            "vendor": "unknown",
        },
        {
            "id": 3,
            "slot": "T1D",
            "tray_type": "PLA",
            "material_code": "001001",
            "tray_color": "#9ea7ae",
            "remain": 100,
            "active": False,
            "state": 11,
            "tray_uuid": "T1D",
            "tag_uid": "",
            "vendor": "unknown",
        },
    ]


def test_moonraker_keeps_cfs_trays_when_active_filament_is_none(monkeypatch):
    client = MoonrakerPrinterClient("http://k2-plus.local:7125", printer_model="Creality K2 Plus")
    status = _moonraker_status_with_cfs("None")
    base_status = {
        key: status[key] for key in ("print_stats", "virtual_sdcard", "display_status", "extruder", "heater_bed")
    }
    cfs_status = {key: status[key] for key in ("box", "filament_rack", "filament_switch_sensor filament_sensor")}
    monkeypatch.setattr(client, "_query_objects", lambda object_names: base_status)
    monkeypatch.setattr(client, "_query_cfs_status", lambda: cfs_status)
    monkeypatch.setattr(client, "_query_fan_status", lambda: {})

    assert client.request_status_update() is True

    assert client.state.raw_data["cfs"]["active_slots"] == []
    assert client.state.tray_now == 255
    trays = client.state.raw_data["ams"][0]["tray"]
    assert [tray["slot"] for tray in trays] == ["T1A", "T1B", "T1C", "T1D"]
    assert all(tray["active"] is False for tray in trays)
    assert all(tray["state"] == 11 for tray in trays)


def test_moonraker_complete_state_clamps_progress_and_remaining_time(monkeypatch):
    client = MoonrakerPrinterClient("http://k2-plus.local:7125", printer_model="Creality K2 Plus")
    status = _moonraker_status_with_cfs("None")
    status["print_stats"] = {
        "state": "complete",
        "filename": "short-test.gcode",
        "print_duration": 90.0,
        "total_duration": 95.0,
    }
    # K2 firmware can leave display/virtual_sdcard progress behind on very short
    # jobs after print_stats has already moved to complete. Terminal states must
    # win over stale fractional progress so the dashboard and archive lifecycle
    # don't keep showing an in-progress ETA.
    status["virtual_sdcard"] = {"progress": 0.18, "file_position": 1234}
    status["display_status"] = {"progress": 0.18}
    base_status = {
        key: status[key] for key in ("print_stats", "virtual_sdcard", "display_status", "extruder", "heater_bed")
    }
    cfs_status = {key: status[key] for key in ("box", "filament_rack", "filament_switch_sensor filament_sensor")}
    monkeypatch.setattr(client, "_query_objects", lambda object_names: base_status)
    monkeypatch.setattr(client, "_query_cfs_status", lambda: cfs_status)
    monkeypatch.setattr(client, "_query_fan_status", lambda: {})

    assert client.request_status_update() is True

    assert client.state.state == "FINISH"
    assert client.state.progress == 100.0
    assert client.state.remaining_time == 0


def test_moonraker_discovers_and_normalizes_webcams(monkeypatch):
    client = MoonrakerPrinterClient("http://k2-plus.local:7125", printer_model="Creality K2 Plus")
    monkeypatch.setattr(
        client,
        "_get",
        lambda path: {
            "webcams": [
                {
                    "name": "Nozzle Cam",
                    "stream_url": "/webcam/?action=stream",
                    "snapshot_url": "http://camera.local/snapshot.jpg",
                }
            ]
        },
    )

    assert client.discover_webcams() == [
        {
            "name": "Nozzle Cam",
            "stream_url": "http://k2-plus.local:7125/webcam/?action=stream",
            "snapshot_url": "http://camera.local/snapshot.jpg",
            "camera_type": "mjpeg",
            "enabled": True,
            "raw": {
                "name": "Nozzle Cam",
                "stream_url": "/webcam/?action=stream",
                "snapshot_url": "http://camera.local/snapshot.jpg",
            },
        }
    ]


def test_moonraker_webcam_discovery_returns_empty_for_k2_without_moonraker_webcams(monkeypatch):
    client = MoonrakerPrinterClient("http://k2-plus.local:7125", printer_model="Creality K2 Plus")
    monkeypatch.setattr(client, "_get", lambda path: {"webcams": []})

    assert client.discover_webcams() == []
