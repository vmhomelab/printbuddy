"""The "Check printer firmware" setting is enforced by the API, not only the UI.

The printers page asked before its settings had loaded, so with the check
switched off Printbuddy still went out to bambulab.com once per printer on every
page load. Off has to mean no request at all.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.app.models.settings import Settings

UPDATE = {
    "update_available": True,
    "latest_version": "01.09.00.00",
    "download_url": "https://example.com/fw.bin",
    "release_notes": None,
    "available_versions": [],
}


def _service() -> MagicMock:
    service = MagicMock()
    service.check_for_update = AsyncMock(return_value=UPDATE)
    return service


async def _switch_off(db) -> None:
    db.add(Settings(key="check_printer_firmware", value="false"))
    await db.commit()


@pytest.mark.integration
class TestFirmwareCheckSetting:
    @pytest.mark.asyncio
    async def test_on_by_default(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory()
        service = _service()
        with patch("backend.app.api.routes.firmware.get_firmware_service", return_value=service):
            r = await async_client.get(f"/api/v1/firmware/updates/{printer.id}")
        assert r.status_code == 200, r.text
        assert r.json()["update_available"] is True
        service.check_for_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_off_asks_nobody(self, async_client: AsyncClient, db_session, printer_factory):
        printer = await printer_factory(name="Garage")
        await _switch_off(db_session)
        service = _service()
        with patch("backend.app.api.routes.firmware.get_firmware_service", return_value=service):
            r = await async_client.get(f"/api/v1/firmware/updates/{printer.id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["printer_id"] == printer.id and body["printer_name"] == "Garage"
        assert body["update_available"] is False and body["latest_version"] is None
        service.check_for_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_off_still_404s_an_unknown_printer(self, async_client: AsyncClient, db_session):
        await _switch_off(db_session)
        assert (await async_client.get("/api/v1/firmware/updates/9999")).status_code == 404

    @pytest.mark.asyncio
    async def test_off_covers_the_all_printers_check(self, async_client: AsyncClient, db_session, printer_factory):
        await printer_factory()
        await printer_factory()
        await _switch_off(db_session)
        service = _service()
        with patch("backend.app.api.routes.firmware.get_firmware_service", return_value=service):
            r = await async_client.get("/api/v1/firmware/updates")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updates_available"] == 0
        assert len(body["updates"]) == 2
        assert all(u["update_available"] is False for u in body["updates"])
        service.check_for_update.assert_not_called()
