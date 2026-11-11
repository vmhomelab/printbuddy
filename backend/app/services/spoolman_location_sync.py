"""Mirror Printbuddy's Spoolman slot assignments into Spoolman's ``location``.

A Printbuddy addition, on by default (setting ``spoolman_sync_location``) and
only in Spoolman mode. While a spool is assigned to a slot, its Spoolman
location is the name of that slot's printer, so Spoolman shows which printer a
spool is loaded in, and its ``extra.printbuddy_slot`` names the printer and
slot ("3DP-039-006 · AMS 1 · Slot 2", so Spoolman can group by it). Once no
slot holds the spool, both are cleared: the spool has no location until the
user gives it one. Nothing remembers where it was before.

Callers do not say what changed, only which spools a write touched, after the
write is committed: ``sync_spool_locations`` reads each spool's slots as they
are now and brings Spoolman in line with them. That makes every call
idempotent, so the manual routes, the AMS sync, the unlink passes and the
backfill all share it, and two calls for one spool cannot leave a stale result.

Rules, per spool:

- Assigned (to any slot; the most recently assigned one wins): the location
  becomes that printer's name and ``printbuddy_slot`` "<printer> · <slot>".
- Not assigned: when the location is still a printer location, it is cleared.
  A location the user changed by hand meanwhile is left alone. The slot label
  is cleared either way.

A "printer location" is the name of any printer in Printbuddy, or a slot marker
such as "<printer> - AMS A1" that older tools wrote (``is_ams_slot_location``).
A printer renamed in Printbuddy takes its spools' location along
(``rename_printer_location``).

Best effort throughout: a failure talking to Spoolman is logged and never
undoes or fails the assignment itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import Iterable

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.printer import Printer
from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment
from backend.app.services.spoolman_extra_keys import SLOT_KEY

logger = logging.getLogger(__name__)

SETTING_KEY = "spoolman_sync_location"

Slot = tuple[int, int, int]  # (printer_id, ams_id, tray_id)

_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()


def printer_location(printer_name: str | None) -> str:
    """The Spoolman location of a spool loaded in a printer: the printer's name."""
    return (printer_name or "").strip()


def _bambu_slot_label(ams_id: int, tray_id: int) -> str | None:
    if 0 <= ams_id <= 7 and 0 <= tray_id <= 3:
        return f"AMS {ams_id + 1} · Slot {tray_id + 1}"
    if 128 <= ams_id <= 191:
        return f"AMS HT {ams_id - 127}"
    if ams_id == 255:
        return "External" if tray_id <= 0 else f"External {tray_id + 1}"
    return None


def _other_slot_label(ams_id: int, tray_id: int, unit: dict | None, tray: dict | None) -> str | None:
    """Non-Bambu providers, in the terms their printer cards use."""
    if ams_id < 0:
        return f"T{tray_id}"  # a generic multi-tool Klipper tool
    if ams_id == 255:
        return "Loaded spool"  # the single spool of a printer without slots
    unit = unit or {}
    unit_name = str(unit.get("name") or "").strip()
    tray_slot = str((tray or {}).get("slot") or "").strip()
    if unit.get("module_type") == "snapmaker_u1":
        return f"T{tray_id}"  # one feeder per toolhead
    if unit_name.upper().startswith("CFS") or unit.get("module_type") == "cfs":
        # Creality names a CFS slot by unit and letter: T1A ... T4D.
        return f"CFS {tray_slot}" if tray_slot else f"CFS T{ams_id + 1}{chr(ord('A') + tray_id)}"
    if unit_name:
        return f"{unit_name} · Lane {tray_id + 1}"  # a multi-material unit with lanes
    return None


def slot_label(
    ams_id: int,
    tray_id: int,
    *,
    provider: str | None = "bambu",
    unit: dict | None = None,
    tray: dict | None = None,
) -> str:
    """A slot as the printer's card names it; ``slot_value`` prefixes the printer.

    Bambu: "AMS 1 · Slot 2", "AMS HT 1", "External", "External 2". Other
    providers by their own terms, read from the unit and tray they report
    (``unit``/``tray``, the live ``raw_data["ams"]`` entries): "T0" for a tool,
    "CFS T1A" for a Creality CFS slot, "<unit> · Lane n" for a unit with lanes.
    "Slot n" when nothing better is known. One branch per provider family: a
    new kind of unit is a new branch here.
    """
    if (provider or "bambu").lower() == "bambu":
        label = _bambu_slot_label(ams_id, tray_id)
    else:
        label = _other_slot_label(ams_id, tray_id, unit, tray)
    return label or f"Slot {(max(ams_id, 0) * 4) + tray_id + 1}"


def slot_value(printer_name: str | None, label: str) -> str:
    """The stored ``printbuddy_slot``: "<printer> · <slot label>", so slots group across printers."""
    return f"{printer_location(printer_name)} · {label}"


def _live_unit_tray(printer_id: int, ams_id: int, tray_id: int) -> tuple[dict | None, dict | None]:
    """The unit and tray the printer reports for a slot right now, as far as it does."""
    try:
        from backend.app.services.printer_manager import printer_manager

        state = printer_manager.get_status(printer_id)
        raw = getattr(state, "raw_data", None) if state is not None else None
        if not isinstance(raw, dict):
            return None, None
        units = raw.get("ams") or []
        if isinstance(units, dict):
            units = units.get("ams") or []
        for unit in units if isinstance(units, list) else []:
            if isinstance(unit, dict) and str(unit.get("id")) == str(ams_id):
                trays = [t for t in unit.get("tray") or [] if isinstance(t, dict)]
                return unit, next((t for t in trays if str(t.get("id")) == str(tray_id)), None)
    except Exception as e:  # noqa: BLE001 — a label falls back to "Slot n"
        logger.debug("Could not read printer %s's units for a slot label: %s", printer_id, e)
    return None, None


def is_printer_location(location: str | None, printer_names: Iterable[str]) -> bool:
    """True when ``location`` names a printer (or an older slot marker), not a storage place."""
    from backend.app.services.location_service import is_ams_slot_location

    value = (location or "").strip()
    if not value:
        return False
    names = {printer_location(name).casefold() for name in printer_names if printer_location(name)}
    return value.casefold() in names or is_ams_slot_location(value)


def _decode_extra(raw) -> str:
    """An extra value as text: Spoolman stores them JSON-encoded."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except ValueError:
            return raw.strip()
        return decoded.strip() if isinstance(decoded, str) else ""
    return ""


def _lock(spool_id: int) -> asyncio.Lock:
    lock = _locks.get(spool_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[spool_id] = lock
    return lock


async def _ensure_fields(client, extra: dict) -> None:
    """Register the extra fields a write carries (named from ``FIELD_NAMES``)."""
    for key in extra:
        await client.ensure_extra_field(key)


async def is_enabled(db: AsyncSession) -> bool:
    """Spoolman mode with the setting on (the default)."""
    from backend.app.api.routes.settings import get_setting
    from backend.app.services.inventory_mode import spoolman_owns_assignments

    if not await spoolman_owns_assignments(db):
        return False
    value = (await get_setting(db, SETTING_KEY) or "").strip().lower()
    return value not in ("false", "0", "no", "off")


async def spools_in_slots(db: AsyncSession, slots: Iterable[Slot]) -> set[int]:
    """The spools assigned to ``slots`` right now; read before a write replaces them."""
    wanted = list(dict.fromkeys(slots))
    if not wanted:
        return set()
    try:
        columns = tuple_(
            SpoolmanSlotAssignment.printer_id, SpoolmanSlotAssignment.ams_id, SpoolmanSlotAssignment.tray_id
        )
        rows = await db.execute(select(SpoolmanSlotAssignment.spoolman_spool_id).where(columns.in_(wanted)))
        return set(rows.scalars())
    except Exception as e:  # noqa: BLE001 — a location hint must not fail the write it precedes
        logger.warning("Could not read the spools in slots %s: %s", wanted, e)
        return set()


async def _target(db: AsyncSession, spool_id: int) -> tuple[str, str] | None:
    """(location, slot label) of the spool's most recent slot, or None when it has none."""
    row = (
        await db.execute(
            select(
                Printer.name,
                Printer.provider,
                Printer.id,
                SpoolmanSlotAssignment.ams_id,
                SpoolmanSlotAssignment.tray_id,
            )
            .join(SpoolmanSlotAssignment, SpoolmanSlotAssignment.printer_id == Printer.id)
            .where(SpoolmanSlotAssignment.spoolman_spool_id == spool_id)
            .order_by(SpoolmanSlotAssignment.assigned_at.desc(), SpoolmanSlotAssignment.id.desc())
            .limit(1)
        )
    ).first()
    if row is None or not printer_location(row[0]):
        return None
    name, provider, printer_id, ams_id, tray_id = row
    unit, tray = (
        (None, None) if (provider or "bambu").lower() == "bambu" else _live_unit_tray(printer_id, ams_id, tray_id)
    )
    label = slot_label(ams_id, tray_id, provider=provider, unit=unit, tray=tray)
    return printer_location(name), slot_value(name, label)


async def _sync_one(client, db: AsyncSession, spool_id: int, printer_names: list[str]) -> dict | None:
    """Bring one spool's location in line with its slots; returns the updated spool, if written."""
    target = await _target(db, spool_id)
    spool = await client.get_spool(spool_id)
    current = (spool.get("location") or "").strip()
    extra = spool.get("extra") if isinstance(spool.get("extra"), dict) else {}
    current_slot = _decode_extra(extra.get(SLOT_KEY))
    at_printer = is_printer_location(current, printer_names)

    # Spoolman merges extra keys on PATCH, so only the keys written here change,
    # and a key is cleared by writing an empty value, as the tag is.
    new_extra: dict[str, str] = {}
    kwargs: dict = {}
    if target is not None:
        location, label = target
        if current != location:
            kwargs["location"] = location
        if current_slot != label:
            new_extra[SLOT_KEY] = json.dumps(label)
    else:
        if at_printer:
            kwargs["clear_location"] = True
        if current_slot:
            new_extra[SLOT_KEY] = json.dumps("")
    if not kwargs and not new_extra:
        return None
    if new_extra:
        await _ensure_fields(client, new_extra)
        kwargs["extra"] = new_extra
    updated = await client.update_spool_full(spool_id, **kwargs)
    if "location" in kwargs or "clear_location" in kwargs:
        logger.info(
            "Spoolman spool %s location %r -> %r (%s)",
            spool_id,
            current or None,
            kwargs.get("location"),
            f"loaded, {target[1]}" if target else "unloaded",
        )
    return updated if isinstance(updated, dict) else None


async def _run(db: AsyncSession, ids: list[int], client, also_printer_names: Iterable[str]) -> dict[int, dict]:
    from backend.app.services.spoolman import SpoolmanNotFoundError, get_spoolman_client

    if not await is_enabled(db):
        return {}
    client = client or await get_spoolman_client()
    if client is None:
        return {}
    printer_names = [name for name in (await db.execute(select(Printer.name))).scalars() if name]
    printer_names += [name for name in also_printer_names if name]
    updated: dict[int, dict] = {}
    for spool_id in ids:
        try:
            async with _lock(spool_id):
                result = await _sync_one(client, db, spool_id, printer_names)
            if result is not None:
                updated[spool_id] = result
        except SpoolmanNotFoundError:
            logger.debug("Spoolman spool %s is gone; no location to sync", spool_id)
        except Exception as e:  # noqa: BLE001 — never fails the assignment
            logger.warning("Could not sync the Spoolman location of spool %s: %s", spool_id, e)
    return updated


async def sync_spool_locations(
    spool_ids: Iterable[int | None],
    *,
    db: AsyncSession | None = None,
    client=None,
    also_printer_names: Iterable[str] = (),
) -> dict[int, dict]:
    """Sync the Spoolman location of each spool to its slots; call after committing.

    ``also_printer_names`` counts as printer locations besides the printers in
    the database: a deleted printer's name, whose spools are to be put back.
    Returns the spools Spoolman answered with, by id, for those it wrote, so a
    route can answer with the new location. Never raises.
    """
    ids = sorted({int(spool_id) for spool_id in spool_ids if spool_id is not None})
    if not ids:
        return {}
    try:
        if db is not None:
            return await _run(db, ids, client, also_printer_names)
        from backend.app.core.database import async_session

        async with async_session() as own_db:
            return await _run(own_db, ids, client, also_printer_names)
    except Exception as e:  # noqa: BLE001 — never fails the assignment
        logger.warning("Could not sync Spoolman locations of spools %s: %s", ids, e)
        return {}


async def backfill_spool_locations(*, db: AsyncSession | None = None, client=None) -> int:
    """Sync every currently assigned spool once; returns how many Spoolman spools were written.

    Idempotent: a spool already at its printer, with its slot, is left as is.
    """
    from backend.app.core.database import async_session

    async def _assigned(session: AsyncSession) -> set[int]:
        return set((await session.execute(select(SpoolmanSlotAssignment.spoolman_spool_id).distinct())).scalars())

    if db is not None:
        return len(await sync_spool_locations(await _assigned(db), db=db, client=client))
    async with async_session() as own_db:
        return len(await sync_spool_locations(await _assigned(own_db), db=own_db, client=client))


async def rename_printer_location(
    printer_id: int, old_name: str | None, new_name: str | None, *, db: AsyncSession, client=None
) -> None:
    """Follow a printer rename in Spoolman. Never raises.

    Spools whose location is the old name get the new one (Spoolman's bulk
    location rename), and the spools assigned to the printer get their slot
    value rewritten, as it starts with the printer's name.
    """
    old, new = printer_location(old_name), printer_location(new_name)
    if not old or not new or old == new:
        return
    try:
        if not await is_enabled(db):
            return
        if client is None:
            from backend.app.services.spoolman import get_spoolman_client

            client = await get_spoolman_client()
        if client is None:
            return
        try:
            await client.rename_location(old, new)
            logger.info("Renamed Spoolman location %r to %r after the printer was renamed", old, new)
        except Exception as e:  # noqa: BLE001 — the per-spool sync below still moves the loaded ones
            logger.warning("Could not rename Spoolman location %r to %r: %s", old, new, e)
        loaded = (
            await db.execute(
                select(SpoolmanSlotAssignment.spoolman_spool_id).where(SpoolmanSlotAssignment.printer_id == printer_id)
            )
        ).scalars()
        await sync_spool_locations(set(loaded), db=db, client=client, also_printer_names=[old])
    except Exception as e:  # noqa: BLE001 — the rename itself is already saved
        logger.warning("Could not follow the rename of printer %s in Spoolman: %s", printer_id, e)
