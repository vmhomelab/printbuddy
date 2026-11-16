"""The Printbuddy mobile app registers itself for push notifications."""

import json

import pytest
from httpx import AsyncClient

TOKEN = "ExponentPushToken[abcdefghij1234567890]"
BASE = "/api/v1/notifications/app-devices"


@pytest.mark.asyncio
@pytest.mark.integration
class TestAppDevicesAPI:
    async def test_register_creates_printbuddy_app_provider(self, async_client: AsyncClient):
        resp = await async_client.post(
            BASE, json={"push_token": TOKEN, "device_name": "iPhone", "platform": "ios", "on_print_stopped": True}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["provider_type"] == "printbuddy_app"
        assert body["name"] == "Printbuddy App (iPhone)"
        assert body["enabled"] is True
        assert body["on_print_complete"] is True
        assert body["on_print_failed"] is True
        assert body["on_print_stopped"] is True
        assert body["on_printer_error"] is True
        config = body["config"] if isinstance(body["config"], dict) else json.loads(body["config"])
        assert config == {"push_token": TOKEN, "device_name": "iPhone", "platform": "ios"}

    async def test_register_is_idempotent_and_updates_toggles(self, async_client: AsyncClient):
        first = (await async_client.post(BASE, json={"push_token": TOKEN})).json()
        second = (
            await async_client.post(BASE, json={"push_token": TOKEN, "device_name": "Pixel", "on_printer_error": False})
        ).json()
        assert first["id"] == second["id"]
        assert second["name"] == "Printbuddy App (Pixel)"
        assert second["on_printer_error"] is False
        providers = (await async_client.get("/api/v1/notifications/")).json()
        assert sum(p["provider_type"] == "printbuddy_app" for p in providers) == 1

    async def test_lookup_and_unregister(self, async_client: AsyncClient):
        assert (await async_client.post(f"{BASE}/lookup", json={"push_token": TOKEN})).status_code == 404
        created = (await async_client.post(BASE, json={"push_token": TOKEN})).json()
        found = await async_client.post(f"{BASE}/lookup", json={"push_token": TOKEN})
        assert found.status_code == 200 and found.json()["id"] == created["id"]

        gone = await async_client.post(f"{BASE}/unregister", json={"push_token": TOKEN})
        assert gone.json() == {"deleted": True}
        again = await async_client.post(f"{BASE}/unregister", json={"push_token": TOKEN})
        assert again.json() == {"deleted": False}
        assert (await async_client.post(f"{BASE}/lookup", json={"push_token": TOKEN})).status_code == 404

    async def test_rejects_tokens_that_are_not_expo_tokens(self, async_client: AsyncClient):
        for bad in ["", "abc", "ExponentPushToken[]", "https://evil.example/push", "ExponentPushToken[a b]"]:
            resp = await async_client.post(BASE, json={"push_token": bad})
            assert resp.status_code == 422, bad

    async def test_existing_routes_still_work_next_to_app_devices(self, async_client: AsyncClient):
        # /app-devices sits next to /{provider_id}; numeric ids must keep resolving.
        created = (await async_client.post(BASE, json={"push_token": TOKEN})).json()
        resp = await async_client.get(f"/api/v1/notifications/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["provider_type"] == "printbuddy_app"

    async def test_requires_auth_when_enabled(self, async_client: AsyncClient, db_session):
        from backend.app.models.settings import Settings

        db_session.add(Settings(key="auth_enabled", value="true"))
        await db_session.commit()
        resp = await async_client.post(BASE, json={"push_token": TOKEN})
        assert resp.status_code == 401
