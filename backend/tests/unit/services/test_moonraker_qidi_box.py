"""QIDI Box (Plus4 / Q2 / Max4 multi-material unit) on Moonraker.

The fixture holds the ``box_extras``, ``multi_color_controller`` and
``save_variables`` objects from a real ``printer/objects/query`` response of a
QIDI Max 4 (firmware 01.01.07, Valve Oil installed): one QIDI Box online with
four spools, slot 2 loaded into the toolhead, three Box positions offline.
"""

import copy
import json
from pathlib import Path

import httpx

from backend.app.services.printer_providers.moonraker import MoonrakerPrinterClient

QIDI_STATUS = json.loads((Path(__file__).parent / "fixtures" / "qidi_box_status.json").read_text(encoding="utf-8"))

BASE_STATUS = {
    "print_stats": {"state": "standby", "filename": "", "print_duration": 0},
    "virtual_sdcard": {"progress": 0.0, "file_path": None},
    "display_status": {"progress": 0.0},
    "extruder": {"temperature": 25.0, "target": 0.0},
    "heater_bed": {"temperature": 25.0, "target": 0.0},
}

QIDI_OBJECTS = [
    "box_extras",
    "box_stepper slot0",
    "multi_color_controller",
    "save_variables",
    "heater_generic heater_box1",
]


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
        "qidi_slot_state": 1,
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


def test_slot_states_come_from_save_variables(monkeypatch):
    client = _client(monkeypatch)

    # slot0 1 (in the Box), slot1 3 (in the feeder), slot2 2 (in the extruder), slot3 1
    trays = client.state.raw_data["ams"][0]["tray"]
    assert [tray["qidi_slot_state"] for tray in trays] == [1, 3, 2, 1]
    assert [tray["state"] for tray in trays] == [11, 11, 11, 11]


def test_empty_slot_state_shows_an_empty_slot(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["save_variables"]["variables"]["slot1"] = 0
    client = _client(monkeypatch, status)

    tray = client.state.raw_data["ams"][0]["tray"][1]
    assert (tray["state"], tray["tray_type"], tray["tray_color"], tray["vendor"]) == (9, "", None, "")


def test_without_save_variables_box_inserted_decides(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    del status["save_variables"]
    status["box_extras"]["boxes"][0]["box_inserted_1"] = 0
    client = _client(monkeypatch, status, available=["box_extras", "multi_color_controller"])

    trays = client.state.raw_data["ams"][0]["tray"]
    assert [tray["state"] for tray in trays] == [11, 9, 11, 11]
    # box_extras.loaded_slot is the fallback for the active slot
    assert client.state.tray_now == 2


def test_active_slot_is_the_one_in_the_extruder_not_the_hub(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    variables = status["save_variables"]["variables"]
    # A failed load of slot 3: it reached the hub (loaded_slot), but slot 0 is in the extruder.
    status["box_extras"]["loaded_slot"] = "slot3"
    variables.update(slot0=2, slot2=1, slot3=-2, slot_sync="slot0")
    client = _client(monkeypatch, status)

    assert client.state.tray_now == 0
    assert client.state.raw_data["qidi_box"]["active_slots"] == ["1A"]


def test_slot_sync_is_used_when_no_slot_is_in_the_extruder(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["save_variables"]["variables"].update(slot2=1, slot_sync="slot3")
    client = _client(monkeypatch, status)

    assert client.state.tray_now == 3


def test_nothing_loaded_leaves_tray_now_unset(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["save_variables"]["variables"].update(slot2=1, slot_sync="slot-1")
    client = _client(monkeypatch, status)

    assert client.state.tray_now == 255
    assert not any(tray["active"] for tray in client.state.raw_data["ams"][0]["tray"])


def test_rfid_spool_reports_fill_level(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    info = status["box_extras"]["boxes"][0]["filament_info"][0]
    info.update(info_from_rfid=1, filament_per=63)
    client = _client(monkeypatch, status)

    assert [tray["remain"] for tray in client.state.raw_data["ams"][0]["tray"]] == [63, -1, -1, -1]


def test_second_online_box_uses_global_slot_numbers(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["box_extras"]["boxes"][1].update(is_online=1, aht20_humidity=31, aht20_temp=24)
    status["save_variables"]["variables"].update(slot2=1, slot4=2, slot_sync="slot4")
    client = _client(monkeypatch, status)

    ams = client.state.raw_data["ams"]
    assert [unit["name"] for unit in ams] == ["QIDI Box 1", "QIDI Box 2"]
    assert [tray["state"] for tray in ams[1]["tray"]] == [11, 9, 9, 9]
    assert ams[1]["tray"][0]["slot"] == "2A"
    assert ams[1]["tray"][0]["active"] is True
    assert client.state.tray_now == 4
    assert client.state.raw_data["qidi_box"]["online_slots"] == [0, 1, 2, 3, 4, 5, 6, 7]


def test_external_spool_print_still_shows_the_box(monkeypatch):
    # enable_box 0 only means the last print used the external spool.
    status = copy.deepcopy(QIDI_STATUS)
    status["multi_color_controller"]["enable_box"] = 0
    status["save_variables"]["variables"]["enable_box"] = 0
    client = _client(monkeypatch, status)

    assert [unit["name"] for unit in client.state.raw_data["ams"]] == ["QIDI Box 1"]
    assert client.state.raw_data["qidi_box"]["enable_box"] == 0


def test_stock_firmware_without_multi_color_controller(monkeypatch):
    status = {"box_extras": copy.deepcopy(QIDI_STATUS["box_extras"])}
    client = _client(monkeypatch, status, available=["box_extras", "box_stepper slot0"])

    assert [unit["name"] for unit in client.state.raw_data["ams"]] == ["QIDI Box 1"]
    assert "vt_tray" not in client.state.raw_data


def test_printers_without_box_extras_do_not_query_it(monkeypatch):
    client = _client(monkeypatch, available=["multi_color_controller", "save_variables"])

    assert not any(names and names[0] == "box_extras" for names in client._test_queried)
    assert "qidi_box" not in client.state.raw_data


# ----------------------------------------------------------------------
# Control
# ----------------------------------------------------------------------


class _Printer:
    """Records G-code scripts; optionally refuses them like Moonraker does."""

    def __init__(self, client, monkeypatch, refuse=None):
        self.scripts: list[str] = []
        self.refuse = refuse
        monkeypatch.setattr(client, "_post", self._post)

    def _post(self, path, payload):
        if path == "printer/gcode/script":
            script = payload["script"]
            self.scripts.append(script)
            if self.refuse:
                request = httpx.Request("POST", "http://qidi.local:7125/printer/gcode/script")
                response = httpx.Response(400, json={"error": {"code": 400, "message": self.refuse}}, request=request)
                raise httpx.HTTPStatusError("400", request=request, response=response)
        elif path == "printer/print/start":
            self.scripts.append(f"START {payload['filename']}")
        return {}


def test_load_sends_the_global_slot(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.ams_load_filament(3) is True
    assert printer.scripts == ["LOAD_FILAMENT_CONTROL SLOT=3"]


def test_load_refuses_slots_on_no_connected_box(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    # slot 4 would shut Klipper down with one Box; 254 is the external spool.
    assert client.ams_load_filament(4) is False
    assert client.ams_load_filament(254) is False
    assert printer.scripts == []
    assert "not on a connected Box" in client.last_error


def test_unload_without_slot_unloads_the_loaded_slot(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.ams_unload_filament() is True
    assert printer.scripts == ["UNLOAD_FILAMENT_CONTROL SLOT=2"]


def test_unload_with_nothing_loaded_is_refused(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["save_variables"]["variables"].update(slot2=1, slot_sync="slot-1")
    client = _client(monkeypatch, status)
    printer = _Printer(client, monkeypatch)

    assert client.ams_unload_filament() is False
    assert printer.scripts == []
    assert client.last_error == "No QIDI Box slot is loaded"


def test_box_commands_are_refused_while_printing(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)
    client.state.state = "RUNNING"

    assert client.ams_load_filament(1) is False
    assert client.ams_unload_filament() is False
    assert printer.scripts == []
    assert "current print" in client.last_error


def test_box_commands_wait_for_a_running_flow(monkeypatch):
    status = copy.deepcopy(QIDI_STATUS)
    status["multi_color_controller"]["task"]["flow_id"] = 1
    client = _client(monkeypatch, status)
    printer = _Printer(client, monkeypatch)

    assert client.ams_load_filament(1) is False
    assert printer.scripts == []
    assert "still loading or unloading" in client.last_error


def test_load_reports_the_firmware_refusal(monkeypatch):
    client = _client(monkeypatch)
    _Printer(client, monkeypatch, refuse="Code:QDE_004_002; Message:Extruder has been loaded, cannot load 1B.")

    assert client.ams_load_filament(1) is False
    assert "QDE_004_002" in client.last_error


def test_print_saves_the_chosen_tool_to_slot_mapping(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.start_print("cube.gcode", ams_mapping=[3, -1, 0]) is True
    assert printer.scripts == [
        "SAVE_VARIABLE VARIABLE=enable_box VALUE=1\n"
        "SAVE_VARIABLE VARIABLE=value_t0 VALUE='\"slot3\"'\n"
        "SAVE_VARIABLE VARIABLE=value_t2 VALUE='\"slot0\"'",
        "START cube.gcode",
    ]


def test_external_spool_print_disables_the_box(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.start_print("cube.gcode", ams_mapping=[254]) is True
    assert printer.scripts == ["SAVE_VARIABLE VARIABLE=enable_box VALUE=0", "START cube.gcode"]


def test_print_without_a_choice_keeps_the_printer_mapping(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.start_print("cube.gcode") is True
    assert client.start_print("cube.gcode", ams_mapping=[-1, -1]) is True
    assert printer.scripts == ["START cube.gcode", "START cube.gcode"]


def test_print_mapped_to_a_missing_box_does_not_start(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.start_print("cube.gcode", ams_mapping=[0, 5]) is False
    assert printer.scripts == []
    assert client.last_error == "QIDI Box slot 5 chosen for T1 is not on a connected Box"


def test_print_mixing_external_spool_and_box_does_not_start(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    assert client.start_print("cube.gcode", ams_mapping=[0, 254]) is False
    assert printer.scripts == []
    assert "not both" in client.last_error


def test_never_sends_creality_m8200(monkeypatch):
    client = _client(monkeypatch)
    printer = _Printer(client, monkeypatch)

    client.ams_load_filament(1)
    client.ams_unload_filament(1)
    client.start_print("cube.gcode", ams_mapping=[1])
    assert not any("M8200" in script for script in printer.scripts)
