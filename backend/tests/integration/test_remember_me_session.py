"""Integration tests for the extended "Remember Me" session lifetime.

By default every session JWT lives 24 h. When the admin enables the
``remember_me_extended_session`` setting, logins with ``remember_me=true``
receive a 30-day token. The client flag alone must never extend the lifetime.
"""

import jwt
import pytest
from httpx import AsyncClient

from backend.app.core.auth import ALGORITHM, SECRET_KEY

DAY = 24 * 60 * 60


def _ttl_seconds(token: str) -> int:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return int(payload["exp"]) - int(payload["iat"])


class TestRememberMeSession:
    @pytest.fixture
    async def admin_token(self, async_client: AsyncClient) -> str:
        await async_client.post(
            "/api/v1/auth/setup",
            json={
                "auth_enabled": True,
                "admin_username": "rememberadmin",
                "admin_password": "AdminPass1!",
            },
        )
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "rememberadmin", "password": "AdminPass1!"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    async def _login(self, async_client: AsyncClient, remember_me: bool) -> str:
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "rememberadmin", "password": "AdminPass1!", "remember_me": remember_me},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    async def _set_extended(self, async_client: AsyncClient, token: str, enabled: bool) -> None:
        resp = await async_client.put(
            "/api/v1/settings/",
            headers={"Authorization": f"Bearer {token}"},
            json={"remember_me_extended_session": enabled},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["remember_me_extended_session"] is enabled

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_default_ttl_is_24h(self, async_client: AsyncClient, admin_token: str):
        assert _ttl_seconds(admin_token) == DAY

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_remember_me_ignored_when_setting_disabled(self, async_client: AsyncClient, admin_token: str):
        token = await self._login(async_client, remember_me=True)
        assert _ttl_seconds(token) == DAY

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_remember_me_gives_30_days_when_enabled(self, async_client: AsyncClient, admin_token: str):
        await self._set_extended(async_client, admin_token, True)

        assert _ttl_seconds(await self._login(async_client, remember_me=True)) == 30 * DAY
        # Without Remember Me the default still applies.
        assert _ttl_seconds(await self._login(async_client, remember_me=False)) == DAY

        await self._set_extended(async_client, admin_token, False)
        assert _ttl_seconds(await self._login(async_client, remember_me=True)) == DAY

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_setting_defaults_to_false(self, async_client: AsyncClient, admin_token: str):
        resp = await async_client.get("/api/v1/settings/", headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 200
        assert resp.json()["remember_me_extended_session"] is False
