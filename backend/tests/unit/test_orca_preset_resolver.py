"""Regression tests for resolving read-only Orca Cloud profiles for slicing."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.schemas.slicer import PresetRef
from backend.app.services import preset_resolver as resolver


class _OrcaAuthorizedUser:
    id = 42

    @staticmethod
    def has_permission(permission: str) -> bool:
        return permission == "orca_cloud:auth"


@pytest.mark.asyncio
async def test_orca_cloud_profile_resolves_to_slot_safe_slicer_json():
    """An Orca source reference fetches profile content via the paired service,
    preserving content but normalising the CLI-only type/from fields."""
    service = MagicMock()
    service.get_profile = AsyncMock(
        return_value={
            "id": "orca-profile",
            "content": {"type": "printer", "from": "User", "name": "My printer"},
        }
    )
    service.close = AsyncMock()

    with patch.object(resolver, "_build_orca_service", AsyncMock(return_value=service)):
        payload = await resolver.resolve_preset_ref(
            MagicMock(),
            _OrcaAuthorizedUser(),
            PresetRef(source="orca_cloud", id="orca-profile"),
            "printer",
        )

    assert json.loads(payload) == {
        "type": "machine",
        "from": "system",
        "name": "My printer",
    }
    service.close.assert_awaited_once()
