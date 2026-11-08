"""Spoolman location follows Printbuddy's slot assignments (setting spoolman_sync_location).

While a spool is assigned, its Spoolman location is the printer's name and
extra.printbuddy_slot the slot's label; the location it had before is kept in
extra.printbuddy_prev_location and restored once no slot holds it.
"""

import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from backend.app.models.settings import Settings
from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment
from backend.app.services.spoolman import SpoolmanNotFoundError
from backend.app.services.spoolman_extra_keys import FIELD_NAMES
from backend.app.services.spoolman_location_sync import (
    PREV_LOCATION_KEY,
    SLOT_KEY,
    backfill_spool_locations,
    is_printer_location,
    printer_location,
    slot_label,
    sync_spool_locations,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class FakeSpoolman:
    """Just enough of SpoolmanClient: PATCH merges extra keys, as Spoolman does."""

    base_url = "http://spoolman.invalid:7912"

    def __init__(self, **locations):
        self.spools = {
            int(sid[1:]): {"id": int(sid[1:]), "location": loc, "extra": {}, "archived": False, **_FILAMENT}
            for sid, loc in locations.items()
        }
        self.fields: dict[str, str | None] = {}
        self.writes: list[dict] = []
        self.renames: list[tuple[str, str]] = []
        self.fail = False

    async def health_check(self):
        return True

    async def get_spool(self, spool_id):
        if spool_id not in self.spools:
            raise SpoolmanNotFoundError(f"Spool {spool_id} not found")
        return copy.deepcopy(self.spools[spool_id])

    async def get_spools(self):
        return [copy.deepcopy(s) for s in self.spools.values()]

    async def merge_spool_extra(self, spool_id, fields):
        self.spools[spool_id]["extra"].update(fields)
        return copy.deepcopy(self.spools[spool_id])

    async def ensure_extra_field(self, name, field_type="text", display_name=None):
        self.fields[name] = display_name
        return True

    async def update_spool_full(self, spool_id, *, location=None, clear_location=False, extra=None, **_):
        if self.fail:
            raise RuntimeError("Spoolman is down")
        spool = self.spools[spool_id]
        if clear_location:
            spool["location"] = None
        elif location is not None:
            spool["location"] = location
        if extra:
            spool["extra"].update(extra)
        self.writes.append({"id": spool_id, "location": location, "clear": clear_location, "extra": extra})
        return copy.deepcopy(spool)

    async def rename_location(self, current_name, new_name):
        self.renames.append((current_name, new_name))
        for spool in self.spools.values():
            if spool["location"] == current_name:
                spool["location"] = new_name
        return 0

    def location(self, spool_id):
        return self.spools[spool_id]["location"]

    def extra(self, spool_id, key):
        raw = self.spools[spool_id]["extra"].get(key)
        return None if raw is None else json.loads(raw)


_FILAMENT = {
    "filament": {"id": 1, "name": "PLA Basic", "material": "PLA", "color_hex": "FF0000", "weight": 1000},
    "remaining_weight": 800.0,
    "used_weight": 200.0,
    "registered": "2024-01-01T00:00:00+00:00",
}


async def _settings(db, **values):
    for key, value in {"spoolman_enabled": "true", "spoolman_url": "http://spoolman.invalid:7912", **values}.items():
        db.add(Settings(key=key, value=value))
    await db.commit()


async def _assign(db, printer_id, spool_id, ams_id=0, tray_id=0):
    db.add(SpoolmanSlotAssignment(printer_id=printer_id, ams_id=ams_id, tray_id=tray_id, spoolman_spool_id=spool_id))
    await db.commit()


async def _unassign(db, spool_id, printer_id=None):
    stmt = delete(SpoolmanSlotAssignment).where(SpoolmanSlotAssignment.spoolman_spool_id == spool_id)
    if printer_id is not None:
        stmt = stmt.where(SpoolmanSlotAssignment.printer_id == printer_id)
    await db.execute(stmt)
    await db.commit()


# --- formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    ("ams_id", "tray_id", "label"),
    [
        (0, 0, "AMS 1 · Slot 1"),
        (0, 2, "AMS 1 · Slot 3"),
        (3, 1, "AMS 4 · Slot 2"),
        (128, 0, "AMS HT 1"),
        (129, 0, "AMS HT 2"),
        (255, 0, "External"),
        (255, 1, "External 2"),
        (-1, 2, "Slot 3"),
    ],
)
async def test_bambu_slot_label(ams_id, tray_id, label):
    assert slot_label(ams_id, tray_id) == label
    assert slot_label(ams_id, tray_id, provider="bambu") == label


@pytest.mark.parametrize(
    ("ams_id", "tray_id", "unit", "tray", "label"),
    [
        (-1, 0, None, None, "T0"),  # generic multi-tool Klipper
        (-1, 3, None, None, "T3"),
        (255, 0, None, None, "Loaded spool"),
        (1, 2, {"id": 1, "name": "CFS T2"}, {"id": 2, "slot": "T2C"}, "CFS T2C"),
        (0, 1, {"id": 0, "name": "CFS T1"}, None, "CFS T1B"),
        (0, 2, {"id": 0, "name": "Snapmaker U1 Feeders", "module_type": "snapmaker_u1"}, {"id": 2}, "T2"),
        (0, 1, {"id": 0, "name": "Box Turtle"}, {"id": 1}, "Box Turtle · Lane 2"),
        (0, 1, None, None, "Slot 2"),  # printer offline: nothing to go by
        (2, 3, {"id": 2}, None, "Slot 12"),
    ],
)
async def test_other_provider_slot_label(ams_id, tray_id, unit, tray, label):
    assert slot_label(ams_id, tray_id, provider="klipper", unit=unit, tray=tray) == label


async def test_a_non_bambu_slot_is_labelled_from_the_live_units(db_session, printer_factory):
    from types import SimpleNamespace

    await _settings(db_session)
    printer = await printer_factory(name="K2 Plus", provider="klipper")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1, ams_id=1, tray_id=0)
    state = SimpleNamespace(raw_data={"ams": [{"id": 1, "name": "CFS T2", "tray": [{"id": 0, "slot": "T2A"}]}]})

    with patch("backend.app.services.printer_manager.printer_manager.get_status", return_value=state):
        await sync_spool_locations([1], db=db_session, client=client)

    assert client.location(1) == "K2 Plus"
    assert client.extra(1, SLOT_KEY) == "K2 Plus · CFS T2A"


async def test_printer_location_is_the_trimmed_printer_name():
    assert printer_location("  3DP-039-006 ") == "3DP-039-006"
    assert printer_location(None) == ""


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("3DP-039-006", True),
        ("impresore", True),
        ("IMPRESORE", True),
        ("3DP-039-006 - AMS A1", True),  # written by an older tool
        ("Dry Box", False),
        ("", False),
        (None, False),
    ],
)
async def test_is_printer_location(location, expected):
    assert is_printer_location(location, ["3DP-039-006", "impresore"]) is expected


# --- assign / unassign -------------------------------------------------------


async def test_assign_sets_printer_name_and_slot_and_keeps_previous(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1, ams_id=0, tray_id=1)

    await sync_spool_locations([1], db=db_session, client=client)

    assert client.location(1) == "3DP-039-006"
    assert client.extra(1, PREV_LOCATION_KEY) == "Dry Box"
    assert client.extra(1, SLOT_KEY) == "3DP-039-006 · AMS 1 · Slot 2"
    assert FIELD_NAMES[SLOT_KEY] == "Slot"

    await _unassign(db_session, 1)
    await sync_spool_locations([1], db=db_session, client=client)

    assert client.location(1) == "Dry Box"
    assert client.extra(1, PREV_LOCATION_KEY) == ""
    assert client.extra(1, SLOT_KEY) == ""


async def test_unassign_without_previous_location_clears_it(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="impresore")
    client = FakeSpoolman(s2=None)
    await _assign(db_session, printer.id, 2, ams_id=255, tray_id=0)
    await sync_spool_locations([2], db=db_session, client=client)
    assert client.location(2) == "impresore"
    assert client.extra(2, SLOT_KEY) == "impresore · External"

    await _unassign(db_session, 2)
    await sync_spool_locations([2], db=db_session, client=client)

    assert client.location(2) is None
    assert client.extra(2, PREV_LOCATION_KEY) == ""


async def test_sync_is_idempotent(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1)
    await sync_spool_locations([1], db=db_session, client=client)
    writes = len(client.writes)

    await sync_spool_locations([1], db=db_session, client=client)

    assert len(client.writes) == writes


async def test_move_between_printers_keeps_the_original_location(db_session, printer_factory):
    await _settings(db_session)
    a = await printer_factory(name="3DP-039-006")
    b = await printer_factory(name="impresore")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, a.id, 1, ams_id=0, tray_id=0)
    await sync_spool_locations([1], db=db_session, client=client)

    await db_session.execute(
        update(SpoolmanSlotAssignment)
        .where(SpoolmanSlotAssignment.spoolman_spool_id == 1)
        .values(printer_id=b.id, ams_id=255, tray_id=0)
    )
    await db_session.commit()
    await sync_spool_locations([1], db=db_session, client=client)

    assert client.location(1) == "impresore"
    assert client.extra(1, PREV_LOCATION_KEY) == "Dry Box"
    assert client.extra(1, SLOT_KEY) == "impresore · External"

    await _unassign(db_session, 1)
    await sync_spool_locations([1], db=db_session, client=client)
    assert client.location(1) == "Dry Box"


async def test_another_slot_of_the_same_printer_keeps_the_location(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1, ams_id=0, tray_id=0)
    await _assign(db_session, printer.id, 1, ams_id=0, tray_id=1)
    await sync_spool_locations([1], db=db_session, client=client)

    await db_session.execute(
        delete(SpoolmanSlotAssignment).where(SpoolmanSlotAssignment.tray_id == 1, SpoolmanSlotAssignment.ams_id == 0)
    )
    await db_session.commit()
    await sync_spool_locations([1], db=db_session, client=client)

    assert client.location(1) == "3DP-039-006"
    assert client.extra(1, PREV_LOCATION_KEY) == "Dry Box"
    assert client.extra(1, SLOT_KEY) == "3DP-039-006 · AMS 1 · Slot 1"


async def test_an_older_slot_marker_is_not_kept_as_previous_location(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="3DP-039-006 - AMS A1")
    await _assign(db_session, printer.id, 1)
    await sync_spool_locations([1], db=db_session, client=client)
    assert client.location(1) == "3DP-039-006"
    assert client.extra(1, PREV_LOCATION_KEY) is None

    await _unassign(db_session, 1)
    await sync_spool_locations([1], db=db_session, client=client)
    assert client.location(1) is None


async def test_a_location_changed_by_hand_while_loaded_is_kept(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1)
    await sync_spool_locations([1], db=db_session, client=client)
    client.spools[1]["location"] = "Shelf 2"

    await _unassign(db_session, 1)
    await sync_spool_locations([1], db=db_session, client=client)

    assert client.location(1) == "Shelf 2"
    assert client.extra(1, PREV_LOCATION_KEY) == ""


@pytest.mark.parametrize(
    "settings",
    [{"spoolman_sync_location": "false"}, {"spoolman_enabled": "false"}],
    ids=["setting-off", "built-in-inventory"],
)
async def test_nothing_is_written_when_disabled(db_session, printer_factory, settings):
    await _settings(db_session, **settings)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1)

    assert await sync_spool_locations([1], db=db_session, client=client) == {}
    assert client.writes == []
    assert client.location(1) == "Dry Box"


async def test_spoolman_failures_are_swallowed(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    client.fail = True
    await _assign(db_session, printer.id, 1)

    assert await sync_spool_locations([1, 99], db=db_session, client=client) == {}


async def test_backfill_writes_each_assigned_spool_once(db_session, printer_factory):
    await _settings(db_session)
    a = await printer_factory(name="3DP-039-006")
    b = await printer_factory(name="impresore")
    client = FakeSpoolman(s1="Dry Box", s2="3DP-039-006 - AMS B1", s3="Box")
    await _assign(db_session, a.id, 1, ams_id=0, tray_id=0)
    await _assign(db_session, a.id, 2, ams_id=0, tray_id=1)
    await _assign(db_session, b.id, 3, ams_id=255, tray_id=0)

    assert await backfill_spool_locations(db=db_session, client=client) == 3
    assert [client.location(i) for i in (1, 2, 3)] == ["3DP-039-006", "3DP-039-006", "impresore"]
    assert [client.extra(i, PREV_LOCATION_KEY) for i in (1, 2, 3)] == ["Dry Box", None, "Box"]
    assert client.extra(2, SLOT_KEY) == "3DP-039-006 · AMS 1 · Slot 2"

    assert await backfill_spool_locations(db=db_session, client=client) == 0


async def test_backfill_rewrites_slot_values_without_the_printer_name(db_session, printer_factory):
    await _settings(db_session)
    printer = await printer_factory(name="voron", provider="klipper")
    client = FakeSpoolman(s1="voron")
    client.spools[1]["extra"] = {SLOT_KEY: json.dumps("AMS 1 · Slot 1"), PREV_LOCATION_KEY: json.dumps("Box")}
    await _assign(db_session, printer.id, 1, ams_id=0, tray_id=0)

    assert await backfill_spool_locations(db=db_session, client=client) == 1
    assert client.extra(1, SLOT_KEY) == "voron · Slot 1"  # offline Klipper: no unit to name it
    assert client.extra(1, PREV_LOCATION_KEY) == "Box"
    assert await backfill_spool_locations(db=db_session, client=client) == 0


# --- automatic paths -------------------------------------------------------


async def test_the_ams_sync_unlinking_an_emptied_slot_restores_the_location(db_session, printer_factory):
    from backend.app.services.spoolman_slot_sync import write_slot_results

    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box", s2="Box")
    await _assign(db_session, printer.id, 1)
    await sync_spool_locations([1], db=db_session, client=client)

    slot = (printer.id, 0, 0)
    with patch("backend.app.services.spoolman.get_spoolman_client", AsyncMock(return_value=client)):
        # A swap: spool 2 replaces spool 1 in the slot.
        await write_slot_results(db_session, {slot: 1}, [(*slot, 2)], [])
        assert client.location(1) == "Dry Box"
        assert client.location(2) == "3DP-039-006"
        # Then the slot is emptied.
        await write_slot_results(db_session, {slot: 2}, [], [slot])

    assert client.location(2) == "Box"
    assert client.extra(2, SLOT_KEY) == ""


async def test_a_grace_expired_unlink_restores_the_location(db_session, printer_factory, async_client):
    from backend.app import main

    await _settings(db_session, spoolman_sync_mode="auto")
    printer = await printer_factory(name="3DP-039-006")
    client = FakeSpoolman(s1="Dry Box")
    await _assign(db_session, printer.id, 1)
    await sync_spool_locations([1], db=db_session, client=client)

    ams = [{"id": 0, "tray": [{"id": 0, "tray_type": "", "tray_color": ""}]}]
    with (
        patch("backend.app.services.spoolman.get_spoolman_client", AsyncMock(return_value=client)),
        patch.object(main.slot_unlink_grace, "removal_confirmed", return_value=True),
    ):
        await main._expire_spoolman_empty_slots(printer.id, ams, False)

    assert client.location(1) == "Dry Box"


# --- routes ------------------------------------------------------------------


@pytest.fixture
def route_client():
    client = FakeSpoolman(s10="Dry Box", s11="Box")
    with (
        patch("backend.app.api.routes.spoolman_inventory._get_client", AsyncMock(return_value=client)),
        patch("backend.app.services.spoolman.get_spoolman_client", AsyncMock(return_value=client)),
    ):
        yield client


async def test_assign_and_unassign_routes(async_client: AsyncClient, db_session, printer_factory, route_client):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")

    response = await async_client.post(
        "/api/v1/spoolman/inventory/slot-assignments",
        json={"spoolman_spool_id": 10, "printer_id": printer.id, "ams_id": 0, "tray_id": 2},
    )
    assert response.status_code == 200
    assert response.json()["storage_location"] == "3DP-039-006"
    assert route_client.extra(10, SLOT_KEY) == "3DP-039-006 · AMS 1 · Slot 3"

    # Another spool takes the slot: the first one goes back to its box.
    response = await async_client.post(
        "/api/v1/spoolman/inventory/slot-assignments",
        json={"spoolman_spool_id": 11, "printer_id": printer.id, "ams_id": 0, "tray_id": 2},
    )
    assert response.status_code == 200
    assert route_client.location(10) == "Dry Box"
    assert route_client.location(11) == "3DP-039-006"

    response = await async_client.delete("/api/v1/spoolman/inventory/slot-assignments/11")
    assert response.status_code == 200
    assert route_client.location(11) == "Box"
    assert response.json()["storage_location"] == "Box"


async def test_assign_route_with_setting_off_leaves_location(
    async_client: AsyncClient, db_session, printer_factory, route_client
):
    await _settings(db_session, spoolman_sync_location="false")
    printer = await printer_factory(name="3DP-039-006")

    response = await async_client.post(
        "/api/v1/spoolman/inventory/slot-assignments",
        json={"spoolman_spool_id": 10, "printer_id": printer.id, "ams_id": 0, "tray_id": 0},
    )

    assert response.status_code == 200
    assert route_client.writes == []
    assert route_client.location(10) == "Dry Box"


async def test_deleting_a_printer_restores_its_spools(
    async_client: AsyncClient, db_session, printer_factory, route_client
):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    await _assign(db_session, printer.id, 10)
    await sync_spool_locations([10], db=db_session, client=route_client)
    assert route_client.location(10) == "3DP-039-006"

    response = await async_client.delete(f"/api/v1/printers/{printer.id}")

    assert response.status_code == 200
    assert route_client.location(10) == "Dry Box"


async def test_renaming_a_printer_renames_the_spoolman_location(
    async_client: AsyncClient, db_session, printer_factory, route_client
):
    await _settings(db_session)
    printer = await printer_factory(name="3DP-039-006")
    await _assign(db_session, printer.id, 10)
    await sync_spool_locations([10], db=db_session, client=route_client)

    response = await async_client.patch(f"/api/v1/printers/{printer.id}", json={"name": "3DP-039-007"})

    assert response.status_code == 200
    assert route_client.renames == [("3DP-039-006", "3DP-039-007")]
    assert route_client.location(10) == "3DP-039-007"
    assert route_client.extra(10, SLOT_KEY) == "3DP-039-007 · AMS 1 · Slot 1"
    assert route_client.extra(10, PREV_LOCATION_KEY) == "Dry Box"
    assert route_client.location(11) == "Box"


async def test_renaming_a_printer_with_setting_off_leaves_spoolman_alone(
    async_client: AsyncClient, db_session, printer_factory, route_client
):
    await _settings(db_session, spoolman_sync_location="false")
    printer = await printer_factory(name="3DP-039-006")

    response = await async_client.patch(f"/api/v1/printers/{printer.id}", json={"name": "3DP-039-007"})

    assert response.status_code == 200
    assert route_client.renames == []


async def test_printer_names_are_not_imported_as_storage_locations(db_session, printer_factory):
    from backend.app.models.location import Location
    from backend.app.services.location_service import sync_locations_from_spoolman

    await printer_factory(name="3DP-039-006")

    class Locations:
        async def get_distinct_locations(self):
            return ["3DP-039-006", "Dry Box"]

    assert await sync_locations_from_spoolman(db_session, Locations()) is True
    await db_session.commit()
    names = set((await db_session.execute(select(Location.name))).scalars())
    assert names == {"Dry Box"}
