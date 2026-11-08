"""The Spoolman spool ``extra`` keys Printbuddy owns, and their older names.

Printbuddy keeps its own per-spool data in Spoolman's custom ("extra") fields.
The two slicer-preset keys used to be ``bambu_slicer_filament[_name]``; they
are ``printbuddy_slicer_filament[_name]`` now. Writes go to the new keys only. Reads take a new key when the spool has it and fall
back to the old key only when the new one is absent, so a spool not migrated
yet reads the same, and a value cleared under the new key (written as "")
stays cleared. ``migrate_legacy_extra_fields`` moves old values over once.

Only those two keys are migrated. ``tag`` is not renamed and its values are
never rewritten here: other Spoolman and NFC tools (SpoolmanScale among them)
read and write it, as they do ``nfc_id``, ``card_uids`` and ``last_dried``,
which Printbuddy does not own and never touches. The remaining ``bambu_*`` keys
(colour name, consumed baseline, last drying) keep their names.

Every field Printbuddy creates in Spoolman gets a readable name (``FIELD_NAMES``).
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

TAG_KEY = "tag"
SLICER_FILAMENT_KEY = "printbuddy_slicer_filament"
SLICER_FILAMENT_NAME_KEY = "printbuddy_slicer_filament_name"
COLOR_NAME_KEY = "bambu_color_name"
WEIGHT_USED_BASELINE_KEY = "bambu_weight_used_baseline"
LAST_DRIED_AT_KEY = "bambu_last_dried_at"
LAST_DRIED_TEMP_KEY = "bambu_last_dried_temp"
LAST_DRIED_HOURS_KEY = "bambu_last_dried_hours"
SLOT_KEY = "printbuddy_slot"
PREV_LOCATION_KEY = "printbuddy_prev_location"

# New key -> the key the same value was stored under before. The migration
# reads, moves and deletes these old keys and nothing else.
LEGACY_KEYS: dict[str, str] = {
    SLICER_FILAMENT_KEY: "bambu_slicer_filament",
    SLICER_FILAMENT_NAME_KEY: "bambu_slicer_filament_name",
}

# The names Spoolman shows for the fields Printbuddy creates.
FIELD_NAMES: dict[str, str] = {
    TAG_KEY: "RFID tag",
    SLICER_FILAMENT_KEY: "Slicer filament",
    SLICER_FILAMENT_NAME_KEY: "Slicer filament name",
    COLOR_NAME_KEY: "Color name",
    WEIGHT_USED_BASELINE_KEY: "Consumed baseline",
    LAST_DRIED_AT_KEY: "Last dried",
    LAST_DRIED_TEMP_KEY: "Last drying temperature",
    LAST_DRIED_HOURS_KEY: "Last drying hours",
    SLOT_KEY: "Slot",
    PREV_LOCATION_KEY: "Previous location",
}


def extra_raw(extra: dict | None, key: str):
    """The raw extra value for ``key``, from its old key when the spool has no new one."""
    if not isinstance(extra, dict):
        return None
    if key in extra:
        return extra[key]
    legacy = LEGACY_KEYS.get(key)
    return extra.get(legacy) if legacy else None


def _has_value(raw) -> bool:
    """A stored value that is not empty (Spoolman stores "" JSON-encoded as '""')."""
    if raw is None:
        return False
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except ValueError:
            return bool(raw.strip())
        return decoded not in (None, "")
    return True


def legacy_values_to_move(extra: dict | None) -> dict[str, str]:
    """The extra patch that moves a spool off its old keys; empty when there is nothing to move.

    An old value goes to its new key unless the new key already has one, and
    the old key is blanked either way, as Spoolman merges extra on PATCH and
    has no way to drop a key from one spool.
    """
    patch: dict[str, str] = {}
    if not isinstance(extra, dict):
        return patch
    for new, old in LEGACY_KEYS.items():
        if not _has_value(extra.get(old)):
            continue
        if not _has_value(extra.get(new)):
            patch[new] = extra[old]
        patch[old] = json.dumps("")
    return patch


async def migrate_legacy_extra_fields(client) -> dict[str, int]:
    """Move every spool's values off the old slicer keys, drop their definitions, name Printbuddy's fields.

    Idempotent: a second run finds nothing to move, and definitions already
    gone are skipped. A definition is only deleted when every spool that had a
    value under it was moved; a failure leaves it, for the next run. Returns
    counts: spools moved, spools failed, definitions deleted.
    """
    moved = failed = 0
    blocked: set[str] = set()
    try:
        spools = await client.get_all_spools(allow_archived=True)
    except Exception as e:  # noqa: BLE001 — try again on the next start
        logger.warning("Could not list Spoolman spools to migrate their extra keys: %s", e)
        return {"spools_moved": 0, "spools_failed": 0, "fields_deleted": 0, "fields_named": 0}
    for spool in spools:
        patch = legacy_values_to_move(spool.get("extra"))
        if not patch:
            continue
        try:
            # update_spool_full registers the new keys (with their names) first.
            await client.update_spool_full(spool["id"], extra=patch)
            moved += 1
        except Exception as e:  # noqa: BLE001 — one spool must not stop the rest
            failed += 1
            blocked |= {key for key in patch if key not in LEGACY_KEYS}  # the old keys
            logger.warning("Could not move Spoolman spool %s to the new extra keys: %s", spool.get("id"), e)
    deleted = 0
    for old in LEGACY_KEYS.values():
        if old in blocked:
            continue
        try:
            if await client.delete_extra_field(old):
                deleted += 1
        except Exception as e:  # noqa: BLE001 — the definition stays; values are already moved
            logger.warning("Could not delete the old Spoolman extra field %r: %s", old, e)
    try:
        named = await client.name_default_named_fields()
    except Exception as e:  # noqa: BLE001 — labels only
        logger.debug("Could not name Printbuddy's Spoolman extra fields: %s", e)
        named = 0
    if moved or failed or deleted:
        logger.info(
            "Spoolman extra keys migrated: %d spool(s) moved, %d failed, %d old field(s) deleted",
            moved,
            failed,
            deleted,
        )
    return {"spools_moved": moved, "spools_failed": failed, "fields_deleted": deleted, "fields_named": named}
