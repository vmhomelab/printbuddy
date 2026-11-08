"""Printbuddy's Spoolman extra keys: the slicer-preset keys moved off ``bambu_*``.

- Reads take ``printbuddy_slicer_filament[_name]`` and fall back to the old
  ``bambu_*`` key only when the spool has no new one.
- ``migrate_legacy_extra_fields`` copies old values over, blanks them, deletes
  the old definitions, and touches nothing else: ``tag``, native tags and the
  keys other tools such as SpoolmanScale keep (``nfc_id``, ``card_uids``,
  ``last_dried``) stay exactly as they were.
- Printbuddy's fields get readable names; a field the user named keeps its name.
"""

import copy
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.api.routes._spoolman_helpers import _extract_extra_str
from backend.app.services.spoolman import SpoolmanClient
from backend.app.services.spoolman_extra_keys import (
    FIELD_NAMES,
    LEGACY_KEYS,
    SLICER_FILAMENT_KEY,
    SLICER_FILAMENT_NAME_KEY,
    extra_raw,
    legacy_values_to_move,
    migrate_legacy_extra_fields,
)

OLD = "bambu_slicer_filament"
OLD_NAME = "bambu_slicer_filament_name"
FOREIGN = {
    "tag": json.dumps("04A1B2C3D4E5F6"),
    "nfc_id": json.dumps("04:A1:B2:C3"),
    "card_uids": json.dumps("04A1B2C3,04FFEE"),
    "last_dried": json.dumps("2026-11-01"),
    "bambu_color_name": json.dumps("Jade White"),
}


def test_only_the_two_slicer_keys_are_renamed():
    assert LEGACY_KEYS == {SLICER_FILAMENT_KEY: OLD, SLICER_FILAMENT_NAME_KEY: OLD_NAME}
    assert FIELD_NAMES["tag"] == "RFID tag"
    assert FIELD_NAMES[SLICER_FILAMENT_KEY] == "Slicer filament"
    assert FIELD_NAMES[SLICER_FILAMENT_NAME_KEY] == "Slicer filament name"
    assert FIELD_NAMES["printbuddy_slot"] == "Slot"
    assert "printbuddy_prev_location" not in FIELD_NAMES


@pytest.mark.asyncio
async def test_the_retired_previous_location_field_is_deleted_once():
    client = FakeSpoolman(_spools())
    client.fields.add("printbuddy_prev_location")
    client.spools[4]["extra"]["printbuddy_prev_location"] = json.dumps("Box")

    result = await migrate_legacy_extra_fields(client)

    assert "printbuddy_prev_location" in client.deleted
    assert result["fields_deleted"] == 3
    assert "printbuddy_prev_location" not in client.spools[4]["extra"]
    assert {"tag", "nfc_id", "card_uids", "last_dried", "bambu_color_name"} <= client.fields
    again = await migrate_legacy_extra_fields(client)
    assert again["fields_deleted"] == 0


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({OLD: json.dumps("GFL99")}, "GFL99"),  # not migrated yet
        ({SLICER_FILAMENT_KEY: json.dumps("GFA00"), OLD: json.dumps("GFL99")}, "GFA00"),
        ({SLICER_FILAMENT_KEY: json.dumps(""), OLD: json.dumps("GFL99")}, ""),  # cleared stays cleared
        ({}, ""),
    ],
)
def test_reads_fall_back_to_the_old_key_only_when_the_new_one_is_absent(extra, expected):
    assert _extract_extra_str(extra, SLICER_FILAMENT_KEY) == expected


def test_extra_raw_does_not_fall_back_for_keys_without_an_old_name():
    assert extra_raw({"bambu_tag": "x"}, "tag") is None


def test_the_move_copies_and_blanks_and_keeps_a_newer_value():
    extra = {OLD: json.dumps("GFL99"), OLD_NAME: json.dumps("Old"), SLICER_FILAMENT_NAME_KEY: json.dumps("New")}
    assert legacy_values_to_move(extra) == {
        SLICER_FILAMENT_KEY: json.dumps("GFL99"),
        OLD: json.dumps(""),
        OLD_NAME: json.dumps(""),
    }
    assert legacy_values_to_move({OLD: json.dumps("")}) == {}
    assert legacy_values_to_move(FOREIGN) == {}


class FakeSpoolman:
    """Merges extra on PATCH and deletes field definitions with their values, as Spoolman does."""

    def __init__(self, spools):
        self.spools = {s["id"]: s for s in copy.deepcopy(spools)}
        self.fields = {OLD, OLD_NAME, "tag", "nfc_id", "card_uids", "last_dried", "bambu_color_name"}
        self.patches: list[tuple[int, dict]] = []
        self.deleted: list[str] = []
        self.fail_ids: set[int] = set()
        self.name_default_named_fields = AsyncMock(return_value=0)

    async def get_all_spools(self, allow_archived=False):
        assert allow_archived is True
        return copy.deepcopy(list(self.spools.values()))

    async def update_spool_full(self, spool_id, *, extra=None, **kwargs):
        assert not kwargs, "the migration writes extra only"
        if spool_id in self.fail_ids:
            raise RuntimeError("Spoolman refused")
        self.patches.append((spool_id, dict(extra)))
        self.spools[spool_id]["extra"].update(extra)
        return copy.deepcopy(self.spools[spool_id])

    async def delete_extra_field(self, key):
        if key not in self.fields:
            return False
        self.fields.discard(key)
        self.deleted.append(key)
        for spool in self.spools.values():
            spool["extra"].pop(key, None)
        return True


def _spools():
    return [
        {"id": 1, "extra": {OLD: json.dumps("GFL99"), OLD_NAME: json.dumps("Bambu PLA Basic"), **FOREIGN}},
        {"id": 2, "extra": {**FOREIGN}, "tags": [{"uid": "04A1B2C3D4E5F6"}]},
        {"id": 3, "extra": {OLD: json.dumps("GFA00"), SLICER_FILAMENT_KEY: json.dumps("GFL05")}},
        {"id": 4, "extra": {}},
    ]


@pytest.mark.asyncio
async def test_migration_moves_values_and_deletes_the_old_definitions():
    client = FakeSpoolman(_spools())

    result = await migrate_legacy_extra_fields(client)

    assert result["spools_moved"] == 2 and result["spools_failed"] == 0 and result["fields_deleted"] == 2
    assert json.loads(client.spools[1]["extra"][SLICER_FILAMENT_KEY]) == "GFL99"
    assert json.loads(client.spools[1]["extra"][SLICER_FILAMENT_NAME_KEY]) == "Bambu PLA Basic"
    assert json.loads(client.spools[3]["extra"][SLICER_FILAMENT_KEY]) == "GFL05"  # the newer value stays
    assert set(client.deleted) == {OLD, OLD_NAME}
    assert all(OLD not in s["extra"] and OLD_NAME not in s["extra"] for s in client.spools.values())
    client.name_default_named_fields.assert_awaited_once()


@pytest.mark.asyncio
async def test_migration_leaves_fields_it_does_not_own_untouched():
    client = FakeSpoolman(_spools())

    await migrate_legacy_extra_fields(client)

    for spool_id in (1, 2):
        for key, value in FOREIGN.items():
            assert client.spools[spool_id]["extra"][key] == value
    assert client.spools[2]["tags"] == [{"uid": "04A1B2C3D4E5F6"}]
    assert all(set(patch) <= {OLD, OLD_NAME, *LEGACY_KEYS} for _, patch in client.patches)
    assert {"tag", "nfc_id", "card_uids", "last_dried", "bambu_color_name"} <= client.fields


@pytest.mark.asyncio
async def test_migration_is_idempotent():
    client = FakeSpoolman(_spools())
    await migrate_legacy_extra_fields(client)
    patches = len(client.patches)

    again = await migrate_legacy_extra_fields(client)

    assert again["spools_moved"] == 0 and again["fields_deleted"] == 0
    assert len(client.patches) == patches


@pytest.mark.asyncio
async def test_a_failed_spool_keeps_the_old_definitions():
    client = FakeSpoolman(_spools())
    client.fail_ids = {1}

    result = await migrate_legacy_extra_fields(client)

    assert result["spools_failed"] == 1
    assert client.deleted == []  # spool 1's values would go with them
    assert json.loads(client.spools[1]["extra"][OLD]) == "GFL99"


# --- field names, through the real client -----------------------------------


def _response(status: int, payload=None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    r.text = json.dumps(payload)
    return r


def _client(listing):
    http = MagicMock()
    http.get = AsyncMock(return_value=_response(200, listing))
    http.post = AsyncMock(return_value=_response(200, {}))
    http.delete = AsyncMock(return_value=_response(200, {}))
    client = SpoolmanClient("http://spoolman.test")
    client._get_client = AsyncMock(return_value=http)
    return client, http


@pytest.mark.asyncio
async def test_default_named_fields_get_a_readable_name_with_their_definition_unchanged():
    tag = {"key": "tag", "name": "tag", "field_type": "text", "order": 0, "default_value": None}
    user_named = {"key": SLICER_FILAMENT_KEY, "name": "My preset", "field_type": "text", "order": 1}
    foreign = {"key": "nfc_id", "name": "nfc_id", "field_type": "text", "order": 2}
    client, http = _client([tag, user_named, foreign])

    assert await client.name_default_named_fields() == 1

    http.post.assert_awaited_once()
    (url,), kwargs = http.post.call_args
    assert url == "http://spoolman.test/api/v1/field/spool/tag"
    assert kwargs["json"] == {"name": "RFID tag", "field_type": "text", "order": 0}


@pytest.mark.asyncio
async def test_a_field_without_a_known_type_is_not_renamed():
    client, http = _client([{"key": "tag", "name": "tag"}])
    assert await client.name_default_named_fields() == 0
    http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_extra_field_only_deletes_a_listed_field():
    client, http = _client([{"key": OLD, "name": OLD, "field_type": "text"}])

    assert await client.delete_extra_field("bambu_not_there") is False
    http.delete.assert_not_awaited()
    assert await client.delete_extra_field(OLD) is True
    (url,), _ = http.delete.call_args
    assert url == f"http://spoolman.test/api/v1/field/spool/{OLD}"


@pytest.mark.asyncio
async def test_a_created_field_gets_its_readable_name():
    client, http = _client([])
    assert await client.ensure_extra_field(SLICER_FILAMENT_KEY) is True
    (_url,), kwargs = http.post.call_args
    assert kwargs["json"]["name"] == "Slicer filament"
