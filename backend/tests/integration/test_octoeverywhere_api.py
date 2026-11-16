"""Integration tests for the OctoEverywhere failure-detection API (PB-35)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from backend.app.models.settings import Settings

BASE = "/api/v1/octoeverywhere"


class TestOctoEverywhereSettings:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_defaults(self, async_client: AsyncClient):
        response = await async_client.get(f"{BASE}/settings")
        assert response.status_code == 200
        assert response.json() == {
            "enabled": False,
            "has_api_key": False,
            "sensitivity": "medium",
            "action": "notify",
            "poll_interval": 0,
            "enabled_printers": None,
            "notify_on_warning": True,
        }

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_roundtrip(self, async_client: AsyncClient):
        response = await async_client.put(
            f"{BASE}/settings",
            json={
                "enabled": True,
                "sensitivity": "high",
                "action": "pause_and_off",
                "poll_interval": 30,
                "enabled_printers": [3, 1, 3],
                "notify_on_warning": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["sensitivity"] == "high"
        assert data["action"] == "pause_and_off"
        assert data["poll_interval"] == 30
        assert data["enabled_printers"] == [1, 3]
        assert data["notify_on_warning"] is False

        response = await async_client.put(f"{BASE}/settings", json={"all_printers": True})
        assert response.json()["enabled_printers"] is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_api_key_is_stored_but_never_returned(self, async_client: AsyncClient, db_session):
        response = await async_client.put(f"{BASE}/settings", json={"api_key": "  prod_SECRET123  "})
        assert response.status_code == 200
        assert response.json()["has_api_key"] is True
        assert "prod_SECRET123" not in response.text

        for path in (f"{BASE}/settings", f"{BASE}/status", "/api/v1/settings/"):
            r = await async_client.get(path)
            assert r.status_code == 200
            assert "prod_SECRET123" not in r.text

        row = (await db_session.execute(select(Settings).where(Settings.key == "octoeverywhere_api_key"))).scalar_one()
        from backend.app.core.encryption import mfa_decrypt

        assert mfa_decrypt(row.value) == "prod_SECRET123"

        response = await async_client.put(f"{BASE}/settings", json={"api_key": ""})
        assert response.json()["has_api_key"] is False

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.parametrize(
        "body",
        [
            {"sensitivity": "extreme"},
            {"action": "cancel"},
            {"poll_interval": 3},
            {"poll_interval": 121},
            {"enabled_printers": ["1"]},
        ],
    )
    async def test_validation(self, async_client: AsyncClient, body):
        response = await async_client.put(f"{BASE}/settings", json=body)
        assert response.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_obico_settings_untouched(self, async_client: AsyncClient):
        before = (await async_client.get("/api/v1/settings/")).json()
        await async_client.put(f"{BASE}/settings", json={"enabled": True, "sensitivity": "high", "action": "pause"})
        after = (await async_client.get("/api/v1/settings/")).json()
        assert {k: v for k, v in after.items() if k.startswith("obico_")} == {
            k: v for k, v in before.items() if k.startswith("obico_")
        }


class TestOctoEverywhereStatusAndTest:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_shape(self, async_client: AsyncClient):
        response = await async_client.get(f"{BASE}/status")
        assert response.status_code == 200
        data = response.json()
        for key in ("is_running", "last_error", "account_error", "per_printer", "history", "enabled", "has_api_key"):
            assert key in data

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_connection_uses_stored_key(self, async_client: AsyncClient):
        await async_client.put(f"{BASE}/settings", json={"api_key": "prod_STORED"})
        with patch(
            "backend.app.api.routes.octoeverywhere.octoeverywhere_detection_service.test_connection",
            new=AsyncMock(return_value={"ok": True, "error_type": None, "error": None}),
        ) as test_conn:
            response = await async_client.post(f"{BASE}/test-connection", json={})
        assert response.status_code == 200
        assert response.json()["ok"] is True
        test_conn.assert_awaited_once_with("prod_STORED")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_connection_prefers_given_key(self, async_client: AsyncClient):
        with patch(
            "backend.app.api.routes.octoeverywhere.octoeverywhere_detection_service.test_connection",
            new=AsyncMock(return_value={"ok": False, "error_type": "OE_INVALID_API_KEY", "error": "bad"}),
        ) as test_conn:
            response = await async_client.post(f"{BASE}/test-connection", json={"api_key": " prod_NEW "})
        assert response.json() == {"ok": False, "error_type": "OE_INVALID_API_KEY", "error": "bad"}
        test_conn.assert_awaited_once_with("prod_NEW")


class TestOctoEverywherePermissions:
    @pytest.fixture
    async def tokens(self, async_client: AsyncClient):
        await async_client.post(
            "/api/v1/auth/setup",
            json={"auth_enabled": True, "admin_username": "octoadmin", "admin_password": "AdminPass1!"},
        )
        admin = (
            await async_client.post("/api/v1/auth/login", json={"username": "octoadmin", "password": "AdminPass1!"})
        ).json()["access_token"]
        groups = (await async_client.get("/api/v1/groups/", headers={"Authorization": f"Bearer {admin}"})).json()
        viewers = next(g for g in groups if g["name"] == "Viewers")
        await async_client.post(
            "/api/v1/users/",
            headers={"Authorization": f"Bearer {admin}"},
            json={"username": "octoviewer", "password": "Viewerpass1!", "group_ids": [viewers["id"]]},
        )
        viewer = (
            await async_client.post("/api/v1/auth/login", json={"username": "octoviewer", "password": "Viewerpass1!"})
        ).json()["access_token"]
        return {"admin": admin, "viewer": viewer}

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unauthenticated_is_rejected(self, async_client: AsyncClient, tokens):
        assert (await async_client.get(f"{BASE}/settings")).status_code == 401
        assert (await async_client.get(f"{BASE}/status")).status_code == 401
        assert (await async_client.put(f"{BASE}/settings", json={"enabled": True})).status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_viewer_can_read_but_not_change(self, async_client: AsyncClient, tokens):
        headers = {"Authorization": f"Bearer {tokens['viewer']}"}
        assert (await async_client.get(f"{BASE}/settings", headers=headers)).status_code == 200
        assert (await async_client.get(f"{BASE}/status", headers=headers)).status_code == 200
        r = await async_client.put(f"{BASE}/settings", headers=headers, json={"api_key": "prod_X"})
        assert r.status_code == 403
        r = await async_client.post(f"{BASE}/test-connection", headers=headers, json={"api_key": "prod_X"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_admin_can_change(self, async_client: AsyncClient, tokens):
        headers = {"Authorization": f"Bearer {tokens['admin']}"}
        r = await async_client.put(f"{BASE}/settings", headers=headers, json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True
