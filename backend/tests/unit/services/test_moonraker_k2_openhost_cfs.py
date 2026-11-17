"""K2-OpenHost (Kalico) CFS: the driver's own ``box`` format.

The fixture is a real ``printer/objects/query?box`` response from a K2 Plus
with two CFS units running K2-OpenHost (api_version 1, revision 4).
"""

import httpx

from backend.app.services.printer_providers.moonraker import MoonrakerPrinterClient

OPENHOST_BOX = {
    "api_version": 1,
    "api_revision": 4,
    "print_mapping_version": 1,
    "print_info": {
        "filename": "EzBz LL Follower Boards_Feeder board - 4 of 5_PETG_1h45m_18g.gcode",
        "tools": [{"tool": 0, "color": "#10E700", "material": "PETG", "name": "SUNLU PETG @System"}],
    },
    "print_mapping": {"filename": None, "map": {}, "active_tool": None, "active_slot": None},
    "data_ready": True,
    "temp_c": 24,
    "humidity_pct": 17,
    "status": "OK",
    "status_code": 0,
    "state": "PRINT",
    "state_code": 2,
    "loaded_slot": 3,
    "slots": [
        {
            "index": 0,
            "present": True,
            "loaded": False,
            "material": "PETG",
            "color": "#4E9F48",
            "brand": "SUNLU",
            "name": "PETG2.0",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": False,
        },
        {
            "index": 1,
            "present": True,
            "loaded": False,
            "material": "PETG",
            "color": "#E0BC32",
            "brand": "SUNLU",
            "name": "PETG2.0",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "000000",
            "external": False,
        },
        {
            "index": 2,
            "present": True,
            "loaded": False,
            "material": "PETG",
            "color": "#7C5BD6",
            "brand": "Overture",
            "name": "PETG",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": False,
        },
        {
            "index": 3,
            "present": True,
            "loaded": True,
            "material": "PETG",
            "color": "#4E9F48",
            "brand": "SUNLU",
            "name": "ElitePETG",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": False,
        },
        {
            "index": 4,
            "present": False,
            "loaded": False,
            "material": "ASA",
            "color": "#00BCD4",
            "brand": "iSanmate",
            "name": "ASA",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": False,
        },
        {
            "index": 5,
            "present": False,
            "loaded": False,
            "material": "ASA",
            "color": "#00BCD4",
            "brand": "iSanmate",
            "name": "ASA",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": False,
        },
        {
            "index": 6,
            "present": False,
            "loaded": False,
            "material": "",
            "color": "",
            "brand": "",
            "name": "",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": False,
        },
        {
            "index": 7,
            "present": True,
            "loaded": False,
            "material": "ASA",
            "color": "#00BCD4",
            "brand": "iSanmate",
            "name": "ASA",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "000000",
            "external": False,
        },
        {
            "index": 8,
            "present": True,
            "loaded": False,
            "material": "",
            "color": "",
            "brand": "",
            "name": "",
            "spoolman_id": None,
            "rfid_percent": None,
            "rfid_reserve": "",
            "external": True,
        },
    ],
    "boxes": [
        {
            "address": 1,
            "online": True,
            "slots": [0, 1, 2, 3],
            "temp_c": 24,
            "humidity_pct": 17,
            "status": "OK",
            "status_code": 0,
            "state": "PRINT",
            "state_code": 2,
            "fault": None,
        },
        {
            "address": 2,
            "online": True,
            "slots": [4, 5, 6, 7],
            "temp_c": 23,
            "humidity_pct": 19,
            "status": "OK",
            "status_code": 0,
            "state": "IDLE",
            "state_code": 0,
            "fault": None,
        },
    ],
    "runout_swap_enabled": True,
    "filament_detected": True,
}

BASE_STATUS = {
    "print_stats": {"state": "printing", "filename": "board.gcode", "print_duration": 60},
    "virtual_sdcard": {"progress": 0.25, "file_path": "board.gcode"},
    "display_status": {"progress": 0.25},
    "extruder": {"temperature": 245.0, "target": 245.0},
    "heater_bed": {"temperature": 85.0, "target": 85.0},
}


def _client_with_box(monkeypatch, box):
    client = MoonrakerPrinterClient("http://k2.local:7125", printer_model="Creality K2 Plus")
    monkeypatch.setattr(client, "_query_objects", lambda object_names: dict(BASE_STATUS))
    monkeypatch.setattr(client, "_query_cfs_status", lambda *args, **kwargs: {"box": box})
    monkeypatch.setattr(client, "_query_fan_status", lambda *args, **kwargs: {})
    monkeypatch.setattr(client, "_available_objects", lambda: [])
    assert client.request_status_update() is True
    return client


def test_openhost_box_becomes_two_cfs_units(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)

    ams = client.state.raw_data["ams"]
    assert [unit["name"] for unit in ams] == ["CFS T1", "CFS T2"]
    assert [unit["module_type"] for unit in ams] == ["k2oh_cfs", "k2oh_cfs"]
    assert [(unit["humidity_raw"], unit["temp"]) for unit in ams] == [(17, 24), (19, 23)]
    assert [len(unit["tray"]) for unit in ams] == [4, 4]

    first = ams[0]["tray"]
    assert [tray["slot"] for tray in first] == ["T1A", "T1B", "T1C", "T1D"]
    assert first[2] == {
        "id": 2,
        "slot": "T1C",
        "tray_type": "PETG",
        "tray_sub_brands": "PETG",
        "tray_color": "#7C5BD6",
        "remain": None,
        "active": False,
        "state": 11,
        "tray_uuid": "T1C",
        "tag_uid": "",
        "vendor": "Overture",
    }
    assert first[3]["active"] is True
    assert first[3]["tray_sub_brands"] == "ElitePETG"


def test_openhost_marks_absent_slots_empty_and_tracks_loaded_slot(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)

    second = client.state.raw_data["ams"][1]["tray"]
    # Slots 4-6 keep stale metadata but have no spool: show them empty.
    assert [(tray["state"], tray["tray_type"], tray["tray_color"]) for tray in second] == [
        (9, "", None),
        (9, "", None),
        (9, "", None),
        (11, "ASA", "#00BCD4"),
    ]
    assert client.state.tray_now == 3
    cfs = client.state.raw_data["cfs"]
    assert cfs["type"] == "k2_openhost_cfs"
    assert cfs["active_slots"] == ["T1D"]
    assert cfs["slot_index_by_tray"] == {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7}


def test_openhost_external_spool_becomes_virtual_tray(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)

    assert client.state.raw_data["vt_tray"] == [
        {
            "id": 254,
            "tray_type": "",
            "tray_sub_brands": "",
            "tray_color": None,
            "remain": None,
            "tag_uid": "",
            "tray_uuid": "",
        }
    ]


def test_offline_box_is_skipped(monkeypatch):
    box = dict(OPENHOST_BOX, boxes=[dict(OPENHOST_BOX["boxes"][0]), dict(OPENHOST_BOX["boxes"][1], online=False)])
    client = _client_with_box(monkeypatch, box)

    assert [unit["name"] for unit in client.state.raw_data["ams"]] == ["CFS T1"]


class _Printer:
    """Records gcode scripts and answers like Moonraker/the K2-OpenHost firmware."""

    def __init__(self, client, monkeypatch, *, tools=(0,), refuse=None):
        self.scripts: list[str] = []
        self.posts: list[tuple[str, dict]] = []
        self.tools = list(tools)
        self.refuse = refuse or {}
        self.print_info_file = None
        self.client = client
        monkeypatch.setattr(client, "_post", self._post)
        monkeypatch.setattr(client, "_query_objects", self._query_objects)

    def _post(self, path, payload):
        self.posts.append((path, payload))
        if path == "printer/gcode/script":
            script = payload["script"]
            self.scripts.append(script)
            for prefix, message in self.refuse.items():
                if script.startswith(prefix):
                    request = httpx.Request("POST", "http://k2.local:7125/printer/gcode/script")
                    response = httpx.Response(400, json={"error": {"code": 400, "message": message}}, request=request)
                    raise httpx.HTTPStatusError("400", request=request, response=response)
            if script.startswith("BOX_PRINT_INFO"):
                self.print_info_file = script.split('FILENAME="', 1)[1].rstrip('"')
        return {}

    def _query_objects(self, names):
        if names == ["box"]:
            return {
                "box": {
                    "print_info": {
                        "filename": self.print_info_file,
                        "tools": [{"tool": tool, "material": "PETG"} for tool in self.tools],
                    }
                }
            }
        return dict(BASE_STATUS)


def test_openhost_load_selects_the_firmware_slot(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)
    client.state.state = "IDLE"
    printer = _Printer(client, monkeypatch)

    assert client.ams_load_filament(7) is True  # CFS T2, fourth slot
    assert client.ams_load_filament(254) is True  # external spool
    assert client.ams_unload_filament(3) is True
    assert printer.scripts == ["BOX_SELECT_SLOT SLOT=7", "BOX_SELECT_SLOT SLOT=8", "BOX_UNLOAD"]
    assert not any("M8200" in script for script in printer.scripts)


def test_openhost_load_is_refused_while_printing(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)
    printer = _Printer(client, monkeypatch)
    client.state.state = "RUNNING"

    assert client.ams_load_filament(1) is False
    assert client.ams_unload_filament() is False
    assert printer.scripts == []
    assert "current print" in client.last_error


def test_openhost_load_reports_the_firmware_refusal(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)
    client.state.state = "IDLE"
    _Printer(client, monkeypatch, refuse={"BOX_SELECT_SLOT": "[BOX]: Box 2 slot B is not an online CFS slot"})

    assert client.ams_load_filament(5) is False
    assert client.last_error == "[BOX]: Box 2 slot B is not an online CFS slot"


def test_openhost_print_sends_the_chosen_tool_map_before_starting(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)
    client.state.state = "IDLE"
    printer = _Printer(client, monkeypatch, tools=(0, 1))

    # T0 -> CFS T2 slot D (7), T1 -> external spool (254 -> firmware slot 8)
    assert client.start_print("board.gcode", ams_mapping=[7, 254]) is True

    assert printer.scripts == ['BOX_PRINT_INFO FILENAME="board.gcode"', "BOX_PRINT_MAP MAP=0:7,1:8"]
    assert printer.posts[-1] == ("printer/print/start", {"filename": "board.gcode"})


def test_openhost_print_without_a_complete_choice_lets_the_firmware_map(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)
    printer = _Printer(client, monkeypatch, tools=(0, 1))

    # T1 has no slot chosen: no partial map (the firmware would refuse it).
    assert client.start_print("board.gcode", ams_mapping=[3, -1]) is True
    assert printer.scripts == ['BOX_PRINT_INFO FILENAME="board.gcode"']
    assert printer.posts[-1][0] == "printer/print/start"

    printer.scripts.clear()
    assert client.start_print("board.gcode", ams_mapping=None) is True
    assert printer.scripts == []


def test_openhost_print_refused_by_the_firmware_does_not_start(monkeypatch):
    client = _client_with_box(monkeypatch, OPENHOST_BOX)
    printer = _Printer(client, monkeypatch, tools=(0,), refuse={"BOX_PRINT_MAP": "[BOX]: Box 2 slot A has no filament"})

    assert client.start_print("board.gcode", ams_mapping=[4]) is False
    assert client.last_error == "[BOX]: Box 2 slot A has no filament"
    assert all(path != "printer/print/start" for path, _ in printer.posts)


def test_creality_cfs_printers_keep_the_m8200_path(monkeypatch):
    client = MoonrakerPrinterClient("http://k2.local:7125", printer_model="Creality K2 Plus")
    assert client.is_k2_openhost_cfs() is False
    sent = []
    monkeypatch.setattr(client, "send_gcode", lambda script: sent.append(script) or True)

    assert client.ams_load_filament(1) is True
    assert sent == ["M8200 P\nM8200 L I=1\nM8200 O"]


def test_print_dispatch_shows_the_firmware_reason(monkeypatch):
    from backend.app.services import print_scheduler as scheduler_module

    class _Client:
        last_error = "[BOX]: Box 2 slot A has no filament"

    scheduler = scheduler_module.PrintScheduler
    monkeypatch.setattr(scheduler_module.printer_manager, "get_client", lambda printer_id: _Client())
    message = scheduler._start_failure_message(1)
    assert message == "Failed to send print command to printer: [BOX]: Box 2 slot A has no filament"

    monkeypatch.setattr(scheduler_module.printer_manager, "get_client", lambda printer_id: None)
    assert scheduler._start_failure_message(1) == "Failed to send print command to printer"
