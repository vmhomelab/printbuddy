"""QIDI Box (Plus4 / Q2 / Max4 multi-material unit) on Moonraker.

The fixture holds the ``box_extras`` and ``multi_color_controller`` objects
from a real ``printer/objects/query`` response: one QIDI Box online (slots
0-3 configured, slot 2 loaded), three Box positions offline.
"""

import copy
import json
from pathlib import Path

from backend.app.services.printer_providers.moonraker import MoonrakerPrinterClient

QIDI_STATUS = json.loads((Path(__file__).parent / "fixtures" / "qidi_box_status.json").read_text(encoding="utf-8"))

BASE_STATUS = {
    "print_stats": {"state": "standby", "filename": "", "print_duration": 0},
    "virtual_sdcard": {"progress": 0.0, "file_path": None},
    "display_status": {"progress": 0.0},
    "extruder": {"temperature": 25.0, "target": 0.0},
    "heater_bed": {"temperature": 25.0, "target": 0.0},
}

QIDI_OBJECTS = ["box_extras", "box_stepper slot0", "multi_color_controller", "heater_generic heater_box1"]


def _client(monkeypatch, qidi_status=None, available=None):
    qidi_status = QIDI_STATUS if qidi_status is None else qidi_status
    client = MoonrakerPrinterClient("http://qidi.local:7125", printer_model="QIDI Q2")
    queried: list[list[str]] = []

    def query_objects(names):
        queried.append(list(names))
        if names[0] == "box_extras":
            return {name: copy.deepcopy(qidi_status[name]) for name in names if name in qidi_status}
        return dict(BASE_STATUS)

    monkeypatch.setattr(client, "_query_objects", query_objects)
    monkeypatch.setattr(client, "_query_fan_status", lambda *args, **kwargs: {})
    monkeypatch.setattr(client, "_query_chamber_status", lambda *args, **kwargs: {})
    monkeypatch.setattr(client, "_available_objects", lambda: list(QIDI_OBJECTS if available is None else available))
    assert client.request_status_update() is True
    client._test_queried = queried
    return client


def test_online_box_becomes_one_ams_unit(monkeypatch):
    client = _client(monkeypatch)

    ams = client.state.raw_data["ams"]
    assert len(ams) == 1
    unit = ams[0]
    assert unit["id"] == 0
    assert unit["name"] == "QIDI Box 1"
    assert unit["module_type"] == "qidi_box"
    assert (unit["humidity_raw"], unit["temp"]) == (46, 27)
    assert [tray["slot"] for tray in unit["tray"]] == ["1A", "1B", "1C", "1D"]
    assert [(tray["tray_type"], tray["tray_color"]) for tray in unit["tray"]] == [
        ("PLA", "#FAFAFA"),
        ("PLA", "#060606"),
        ("PLA", "#060606"),
        ("PLA", "#228332"),
    ]
    assert unit["tray"][3] == {
        "id": 3,
        "slot": "1D",
        "tray_type": "PLA",
        "tray_sub_brands": "PLA",
        "tray_color": "#228332",
        "remain": -1,
        "active": False,
        "state": 11,
        "tray_uuid": "1D",
        "tag_uid": "",
        "vendor": "Generic",
        "qidi_filament_id": "QFA90",
        "nozzle_temp_min": 190,
        "nozzle_temp_max": 240,
    }


def test_loaded_slot_marks_the_active_tray(monkeypatch):
    client = _client(monkeypatch)

    trays = client.state.raw_data["ams"][0]["tray"]
    assert [tray["active"] for tray in trays] == [False, False, True, False]
    assert client.state.tray_now == 2
    box = client.state.raw_data["qidi_box"]
    assert box["loaded_slot"] == 2
    assert box["active_slots"] == ["1C"]
    assert box["auto_refill"] == [{"color": "#060606", "type": "PLA", "slot": ["1B", "1C"]}]


def test_external_spool_becomes_virtual_tray(monkeypatch):
    client = _client(monkeypatch)

    assert client.state.raw_data["vt_tray"] == [
        {
            "id": 254,
            "tray_type": "PLA",
            "tray_sub_brands": "PLA Basic",
            "tray_color": "#FAFAFA",
            "remain": -1,
            "tag_uid": "",
            "tray_uuid": "",
            "vendor": "QIDI",
        }
    ]


def test_slot_without_spool_is_empty(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["box_extras"]["boxes"][0]["box_inserted_1"] = 0
    client = _client(monkeypatch, status)

    tray = client.state.raw_data["ams"][0]["tray"][1]
    assert (tray["state"], tray["tray_type"], tray["tray_color"], tray["vendor"]) == (9, "", None, "")


def test_rfid_spool_reports_fill_level(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    info = status["box_extras"]["boxes"][0]["filament_info"][0]
    info.update(info_from_rfid=1, filament_per=63)
    client = _client(monkeypatch, status)

    assert [tray["remain"] for tray in client.state.raw_data["ams"][0]["tray"]] == [63, -1, -1, -1]


def test_second_online_box_uses_global_slot_numbers(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    second = status["box_extras"]["boxes"][1]
    second.update(is_online=1, box_inserted_0=1, aht20_humidity=31, aht20_temp=24)
    status["box_extras"]["loaded_slot"] = "slot4"
    client = _client(monkeypatch, status)

    ams = client.state.raw_data["ams"]
    assert [unit["name"] for unit in ams] == ["QIDI Box 1", "QIDI Box 2"]
    assert [tray["state"] for tray in ams[1]["tray"]] == [11, 9, 9, 9]
    assert ams[1]["tray"][0]["slot"] == "2A"
    assert ams[1]["tray"][0]["active"] is True
    assert client.state.tray_now == 4


def test_no_loaded_slot_leaves_tray_now_unset(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["box_extras"]["loaded_slot"] = "slot16"
    client = _client(monkeypatch, status)

    assert client.state.tray_now == 255
    assert not any(tray["active"] for tray in client.state.raw_data["ams"][0]["tray"])


def test_disabled_box_is_not_shown(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["multi_color_controller"]["enable_box"] = 0
    client = _client(monkeypatch, status)

    assert "qidi_box" not in client.state.raw_data
    assert not client.state.raw_data.get("ams")


def test_stock_firmware_without_multi_color_controller(monkeypatch):
    status = {"box_extras": copy.deepcopy(QIDI_STATUS["box_extras"])}
    client = _client(monkeypatch, status, available=["box_extras", "box_stepper slot0"])

    assert [unit["name"] for unit in client.state.raw_data["ams"]] == ["QIDI Box 1"]
    assert "vt_tray" not in client.state.raw_data


def test_printers_without_box_extras_do_not_query_it(monkeypatch):
    client = _client(monkeypatch, available=["multi_color_controller"])

    assert ["box_extras", "multi_color_controller"] not in client._test_queried
    assert "qidi_box" not in client.state.raw_data


def test_load_and_unload_never_send_creality_commands(monkeypatch):
    client = _client(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(client, "send_gcode", lambda script: sent.append(script) or True)

    assert client.ams_load_filament(1) is False
    assert client.ams_unload_filament(1) is False
    assert sent == []
