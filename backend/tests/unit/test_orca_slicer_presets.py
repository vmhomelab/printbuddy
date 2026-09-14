"""Tests for Orca Cloud profiles in the unified slicer preset listing."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.api.routes import slicer_presets as presets


class _OrcaAuthorizedUser:
    id = 7
    orca_cloud_token = "access-token"
    orca_cloud_refresh_token = "refresh-token"
    orca_cloud_expires_at = datetime.now(timezone.utc) + timedelta(hours=12)
    orca_cloud_email = None
    orca_cloud_user_id = "user-7"
    orca_cloud_pending_verifier = None
    orca_cloud_pending_state = None
    orca_cloud_pending_at = None

    @staticmethod
    def has_permission(permission: str) -> bool:
        return permission == "orca_cloud:auth"


@pytest.mark.asyncio
async def test_orca_cloud_profiles_are_grouped_and_keep_inline_metadata():
    service = MagicMock()
    service.list_profiles = AsyncMock(
        return_value=[
            {
                "id": "filament-1",
                "name": "My PLA",
                "content": {
                    "type": "filament",
                    "filament_type": ["PLA"],
                    "default_filament_colour": ["FF0000"],
                    "compatible_printers": ["Bambu Lab P1S 0.4 nozzle"],
                },
            },
            {"id": "print-1", "name": "Fine", "content": {"type": "print"}},
            {"id": "printer-1", "name": "P1S", "content": {"type": "printer"}},
        ]
    )
    service.close = AsyncMock()

    with patch.object(presets, "_build_orca_service", AsyncMock(return_value=service)):
        slots, status = await presets._fetch_orca_cloud_presets(MagicMock(), _OrcaAuthorizedUser(), refresh=True)

    assert status == "ok"
    assert [item.id for item in slots["filament"]] == ["filament-1"]
    assert slots["filament"][0].source == "orca_cloud"
    assert slots["filament"][0].filament_type == "PLA"
    assert slots["filament"][0].filament_colour == "FF0000"
    assert slots["filament"][0].compatible_printers == ["Bambu Lab P1S 0.4 nozzle"]
    assert [item.id for item in slots["process"]] == ["print-1"]
    assert [item.id for item in slots["printer"]] == ["printer-1"]
    service.close.assert_awaited_once()
