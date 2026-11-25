"""H3C support (ported from upstream 1.3.1, #3442).

The H3C's AMS 3H is one unit (32, AMS type 6) with nine slots, numbered
28 + slot; each hotend also has its own external input 247-255. These tests
cover the H3C-only branches and that the numbering of the other printers is
unchanged.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend.app.services.bambu_mqtt import BambuMQTTClient, ams3h_drying_cooling_temp
from backend.app.services.spool_assignment_notifications import (
    _decode_mqtt_mapping_to_global_trays,
    _global_tray_from_assignment,
    _slot_label_from_global_tray,
)
from backend.app.services.spoolman_tracking import _global_tray_id_to_ams_slot, build_ams_tray_lookup
from backend.app.services.usage_tracker import _decode_mqtt_mapping
from backend.app.utils.printer_models import (
    chamber_heater_needs_heating_mode,
    get_rod_type,
    has_ams3h,
    normalize_printer_model,
    normalize_printer_model_id,
    usage_progress,
)
from backend.app.utils.tray_ids import h3c_global_tray, h3c_slot_key

# AMS 3H unit as the H3C reports it: info's low nibble 6 = ZMULTI_A.
AMS3H_INFO = "1006"


def _ams3h_unit(trays: list[dict] | None = None, **extra) -> dict:
    if trays is None:
        trays = [{"id": str(k), "tray_type": "PLA", "tray_color": "FF0000FF"} for k in range(9)]
    return {"id": "32", "info": AMS3H_INFO, "tray": trays, **extra}


def _client(model: str | None) -> BambuMQTTClient:
    client = BambuMQTTClient(ip_address="192.168.1.100", serial_number="TEST123", access_code="12345678", model=model)
    client._client = MagicMock()
    client.state.connected = True
    return client


def _published(client: BambuMQTTClient) -> dict:
    return json.loads(client._client.publish.call_args[0][1])["print"]


# ---------------------------------------------------------------------------
# Model recognition
# ---------------------------------------------------------------------------


class TestModels:
    def test_model_names(self):
        assert normalize_printer_model_id("N10") == "H3C"
        assert normalize_printer_model("Bambu Lab H3C") == "H3C"
        assert get_rod_type("H3C") == "linear_rail"
        assert get_rod_type("N10") == "linear_rail"

    @pytest.mark.parametrize("model", ["H3C", "h3c", "N10", " H3C "])
    def test_h3c_flags(self, model):
        assert has_ams3h(model)
        assert chamber_heater_needs_heating_mode(model)

    @pytest.mark.parametrize("model", [None, "", "H2C", "H2D", "X1C", "P2S", "N7"])
    def test_other_models_unflagged(self, model):
        assert not has_ams3h(model)
        assert not chamber_heater_needs_heating_mode(model)

    def test_usage_progress_by_layers_on_h3c(self):
        # The H3C's progress counts the ~8 min start sequence.
        assert usage_progress("H3C", 20.0, 0, 100) == 0.0
        assert usage_progress("H3C", 60.0, 50, 100) == 50.0
        assert usage_progress("H3C", 60.0, 150, 100) == 100.0

    def test_usage_progress_unchanged_elsewhere(self):
        assert usage_progress("X1C", 42.0, 10, 100) == 42.0
        assert usage_progress("X1C", None, 10, 100) == 0.0


# ---------------------------------------------------------------------------
# Tray numbering helpers
# ---------------------------------------------------------------------------


class TestTrayIds:
    def test_h3c_global_tray(self):
        assert h3c_global_tray(32, 0) == 28
        assert h3c_global_tray(32, 8) == 36
        assert h3c_global_tray(255, 0) == 254
        assert h3c_global_tray(255, 1) == 255
        assert h3c_global_tray(255, 2) == 247
        assert h3c_global_tray(255, 8) == 253
        assert h3c_global_tray(0, 1) is None
        assert h3c_global_tray(32, 9) is None

    def test_h3c_slot_key(self):
        assert h3c_slot_key(28) == (32, 0)
        assert h3c_slot_key(36) == (32, 8)
        assert h3c_slot_key(247) == (255, 2)
        assert h3c_slot_key(253) == (255, 8)
        # Left to the callers' usual decoding.
        assert h3c_slot_key(254) is None
        assert h3c_slot_key(3) is None
        assert h3c_slot_key(128) is None


# ---------------------------------------------------------------------------
# MQTT state parsing
# ---------------------------------------------------------------------------


class TestMqttParsing:
    def test_ams3h_tray_now_raw_slot_becomes_global(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()], "tray_now": "3"})
        assert client.state.tray_now == 31
        assert client.tray_layout.rack

    def test_ams3h_tray_now_before_any_ams_data(self):
        """An H3C is known by its model before its AMS units arrive."""
        client = _client("H3C")
        client._handle_ams_data({"tray_now": "5"})
        assert client.state.tray_now == 33

    def test_ams3h_external_input_kept(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()], "tray_now": "249"})
        assert client.state.tray_now == 249

    def test_regular_printer_tray_now_unchanged(self):
        client = _client("X1C")
        client._handle_ams_data({"ams": [{"id": "0", "info": "1001", "tray": [{"id": "0"}]}], "tray_now": "3"})
        assert client.state.tray_now == 3
        assert not client.tray_layout.rack

    def test_tray_exist_bits_use_global_tray_bits(self):
        """Bits 28-36 carry the AMS 3H slots; slot 4 (bit 32) is empty here."""
        client = _client("H3C")
        bits = sum(1 << (28 + k) for k in range(9) if k != 4)
        client._handle_ams_data({"ams": [_ams3h_unit()], "tray_exist_bits": format(bits, "x")})
        trays = {int(t["id"]): t for t in client.state.raw_data["ams"][0]["tray"]}
        assert trays[4]["tray_type"] == ""
        assert trays[4]["state"] == 9
        assert all(trays[k]["tray_type"] == "PLA" for k in range(9) if k != 4)

    def test_partial_state_push_keeps_loaded_slot(self):
        """A loaded AMS 3H slot reports state 27; an {id, state} push must not clear it."""
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()]})
        client._handle_ams_data({"ams": [{"id": "32", "tray": [{"id": "2", "state": 27}]}]})
        trays = {int(t["id"]): t for t in client.state.raw_data["ams"][0]["tray"]}
        assert trays[2]["tray_type"] == "PLA"

    def test_ams3h_not_in_extruder_map(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()]})
        assert "32" not in (client.state.ams_extruder_map or {})

    def test_zone_info_lifted_onto_unit(self):
        zones = [
            {"zone_id": 1, "zone_slots": [0, 1], "dry_time": 30, "temp": "45.0", "humidity_raw": "12"},
            {"zone_id": 2, "zone_slots": [2, 3, 4, 5, 6, 7, 8], "temp": "24.5", "humidity_raw": "38"},
        ]
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit(zone_info=zones)]})
        unit = client.state.raw_data["ams"][0]
        assert unit["dry_zone_id"] == 1
        assert unit["dry_zone_slots"] == [0, 1]
        assert unit["dry_time"] == 30
        # The unit shows the ambient zone's readings, as Studio does.
        assert unit["temp"] == "24.5"
        assert unit["humidity_raw"] == "38"

    def test_mounted_hotend_temperature_on_h3c(self):
        """nozzle_temper reports the hotend just put back; the mounted one is in extruder.info."""
        client = _client("H3C")
        client._update_state(
            {"nozzle_temper": 80.0, "device": {"extruder": {"info": [{"id": 0, "temp": 220 * 65536 + 200}]}}}
        )
        assert client.state.temperatures["nozzle"] == 200.0
        assert client.state.temperatures["nozzle_target"] == 220.0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


class TestCommands:
    def test_start_print_mapping(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()]})
        client.start_print("test.3mf", ams_mapping=[30, 248, -1])
        cmd = _published(client)
        assert cmd["ams_mapping"] == [30, -1, -1]
        assert cmd["ams_mapping2"] == [
            {"ams_id": 32, "slot_id": 2},
            {"ams_id": 248, "slot_id": 0},
            {"ams_id": 255, "slot_id": 255},
        ]

    def test_start_print_mapping_unchanged_on_x1c(self):
        client = _client("X1C")
        client.start_print("test.3mf", ams_mapping=[0, 5, 30])
        cmd = _published(client)
        assert cmd["ams_mapping2"] == [
            {"ams_id": 0, "slot_id": 0},
            {"ams_id": 1, "slot_id": 1},
            {"ams_id": 7, "slot_id": 2},
        ]

    def test_chamber_heater_switches_airduct_first(self):
        client = _client("H3C")
        client.state.airduct_mode = 0
        client.set_chamber_temperature(50)
        commands = [json.loads(c[0][1])["print"] for c in client._client.publish.call_args_list]
        assert commands[0]["command"] == "set_airduct"
        assert commands[0]["modeId"] == 1
        assert "M141 S50" in commands[-1]["param"]

    def test_chamber_heater_no_airduct_switch_on_h2d(self):
        client = _client("H2D")
        client.state.airduct_mode = 0
        client.set_chamber_temperature(50)
        commands = [json.loads(c[0][1])["print"] for c in client._client.publish.call_args_list]
        assert all(c.get("command") != "set_airduct" for c in commands)

    def test_drying_names_zone_and_cooling_temp(self):
        client = _client("H3C")
        zones = [{"zone_id": 3, "zone_slots": [0, 1]}]
        client._handle_ams_data({"ams": [_ams3h_unit(zone_info=zones)]})
        client.send_drying_command(ams_id=32, temp=55, duration=4, mode=1, filament="PETG", rotate_tray=True)
        cmd = _published(client)
        assert cmd["zone_id"] == 3
        assert cmd["cooling_temp"] == ams3h_drying_cooling_temp("PETG") == 75
        assert cmd["rotate_tray"] is False

    def test_drying_unchanged_on_ams_ht(self):
        client = _client("H2D")
        client.send_drying_command(ams_id=128, temp=75, duration=8, mode=1, filament="ABS")
        cmd = _published(client)
        assert "zone_id" not in cmd
        assert cmd["cooling_temp"] == 45

    def test_load_ams3h_slot(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()]})
        assert client.ams_load_filament(30) is True
        cmd = _published(client)
        assert cmd["command"] == "ams_change_filament"
        assert (cmd["ams_id"], cmd["slot_id"], cmd["target"]) == (32, 2, 32)
        assert client.state.pending_tray_target == 30

    def test_load_refuses_empty_slot_and_external(self):
        trays = [{"id": str(k), "tray_type": "PLA" if k else ""} for k in range(9)]
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit(trays)]})
        assert client.ams_load_filament(28) is False  # slot 1 has no filament
        assert client.ams_load_filament(250) is False  # an external input can't feed itself

    def test_unload_retracts_the_mounted_hotend(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()], "tray_now": "4"})
        client._client.publish.reset_mock()
        assert client.ams_unload_filament() is True
        cmd = _published(client)
        assert (cmd["ams_id"], cmd["target"], cmd["slot_id"]) == (32, 255, 255 - 4)

    def test_filament_setting_addresses_unit_32(self):
        client = _client("H3C")
        client._handle_ams_data({"ams": [_ams3h_unit()]})
        client.ams_set_filament_setting(
            ams_id=32,
            tray_id=6,
            tray_info_idx="GFA00",
            tray_type="PLA",
            tray_sub_brands="PLA Basic",
            tray_color="FF0000FF",
            nozzle_temp_min=190,
            nozzle_temp_max=230,
        )
        cmd = _published(client)
        assert (cmd["ams_id"], cmd["tray_id"], cmd["slot_id"]) == (32, 6, 6)


# ---------------------------------------------------------------------------
# Usage, Spoolman and notifications
# ---------------------------------------------------------------------------


class TestUsageAndAssignments:
    def test_mqtt_mapping_decodes_ams3h_and_inputs(self):
        mapping = [(32 << 8) | 2, (248 << 8), 65535]
        assert _decode_mqtt_mapping(mapping) == [30, 248, -1]
        assert _decode_mqtt_mapping_to_global_trays(mapping) == [30, 248]

    def test_regular_mapping_unchanged(self):
        assert _decode_mqtt_mapping([(1 << 8) | 2, (255 << 8) | 0]) == [6, 254]

    def test_spoolman_tray_lookup_and_slot_keys(self):
        lookup = build_ams_tray_lookup({"ams": [_ams3h_unit()]})
        assert set(lookup) == set(range(28, 37))
        assert _global_tray_id_to_ams_slot(30, ams3h=True) == (32, 2)
        assert _global_tray_id_to_ams_slot(249, ams3h=True) == (255, 4)
        # Unchanged without the flag: 30 is AMS unit 7, slot 2 on other printers.
        assert _global_tray_id_to_ams_slot(30) == (7, 2)

    def test_assignment_keys_and_labels(self):
        assert _global_tray_from_assignment(32, 3) == 31
        assert _global_tray_from_assignment(255, 2) == 247
        assert _global_tray_from_assignment(255, 1) == 255
        assert _global_tray_from_assignment(1, 2) == 6
        assert _slot_label_from_global_tray(31, ams3h=True) == "3H-4"
        assert _slot_label_from_global_tray(247, ams3h=True) == "Ext-9"
        assert _slot_label_from_global_tray(255, ams3h=True) == "Ext-1"
        assert _slot_label_from_global_tray(255) == "Ext-R"
        assert _slot_label_from_global_tray(6) == "B3"


# ---------------------------------------------------------------------------
# Spoolman slot CHECK migration (SQLite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spoolman_slot_check_widening_keeps_rows_and_admits_h3c_slots():
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import create_async_engine

    from backend.app.core import database

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE printers (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("INSERT INTO printers (id) VALUES (1)"))
            # The table as the previous release created it.
            await conn.execute(
                text(
                    "CREATE TABLE spoolman_slot_assignments ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE CASCADE, "
                    "ams_id INTEGER NOT NULL CHECK ((ams_id >= 0 AND ams_id <= 7) OR (ams_id >= 128 AND ams_id <= 191) "
                    "OR ams_id = 255), "
                    "tray_id INTEGER NOT NULL CHECK (tray_id >= 0 AND tray_id <= 3), "
                    "spoolman_spool_id INTEGER NOT NULL, "
                    "assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                    "CONSTRAINT uq_slot_assignment UNIQUE(printer_id, ams_id, tray_id))"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO spoolman_slot_assignments (printer_id, ams_id, tray_id, spoolman_spool_id) VALUES (1, 0, 2, 7)"
                )
            )

        async with engine.begin() as conn:
            original_is_sqlite = database.is_sqlite
            database.is_sqlite = lambda: True
            try:
                await database._migrate_widen_spoolman_slot_ams_id_range(conn)
                # A second start changes nothing.
                await database._migrate_widen_spoolman_slot_ams_id_range(conn)
            finally:
                database.is_sqlite = original_is_sqlite

        async with engine.begin() as conn:
            rows = (
                await conn.execute(text("SELECT ams_id, tray_id, spoolman_spool_id FROM spoolman_slot_assignments"))
            ).all()
            assert [tuple(r) for r in rows] == [(0, 2, 7)]
            # AMS 3H slot 9 and the H3C's Ext-9 (255, 2) are admitted now.
            await conn.execute(
                text(
                    "INSERT INTO spoolman_slot_assignments (printer_id, ams_id, tray_id, spoolman_spool_id) VALUES (1, 32, 8, 8)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO spoolman_slot_assignments (printer_id, ams_id, tray_id, spoolman_spool_id) VALUES (1, 255, 2, 9)"
                )
            )

        # Slot 4+ on a regular AMS is still refused.
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO spoolman_slot_assignments (printer_id, ams_id, tray_id, spoolman_spool_id) "
                        "VALUES (1, 1, 4, 10)"
                    )
                )
    finally:
        await engine.dispose()


def test_h3c_maintenance_types_apply_only_to_h3c():
    from backend.app.api.routes.maintenance import _should_apply_to_printer

    assert _should_apply_to_printer("Oil SwapTek Rack (H3C)", "H3C")
    assert _should_apply_to_printer("Oil SwapTek Rack (H3C)", "N10")
    assert not _should_apply_to_printer("Oil SwapTek Rack (H3C)", "H2C")
    # The H3C's own tasks replace these generic ones there.
    assert not _should_apply_to_printer("Lubricate Linear Rails", "H3C")
    assert _should_apply_to_printer("Lubricate Linear Rails", "H2C")
    assert _should_apply_to_printer("Check Belt Tension", "H3C")
