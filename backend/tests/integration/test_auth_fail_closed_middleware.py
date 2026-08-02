"""Regression coverage for the global auth middleware fail-closed contract."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auth_middleware_returns_503_when_auth_state_probe_fails(async_client: AsyncClient):
    """If the middleware cannot determine whether auth is enabled, it must deny.

    Returning the protected endpoint would fail open: a database outage in the
    auth probe cannot be interpreted as "auth disabled".
    """

    with patch("backend.app.core.auth.is_auth_enabled", side_effect=OSError("db unavailable")):
        response = await async_client.get("/api/v1/filament-catalog/")

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication state unavailable"
