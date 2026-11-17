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
    assert response.json()["detail"] == "Authentication service temporarily unavailable"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_route_errors_are_not_reported_as_auth_state_failures(async_client: AsyncClient):
    """With auth disabled, an exception raised by the route itself must not be
    swallowed by the auth probe's handler and misreported as a 503
    "Authentication service temporarily unavailable" (it hid a sidecar JSON error once)."""

    with patch("backend.app.api.routes.settings.SlicerApiService") as service:
        service.return_value.__aenter__.side_effect = RuntimeError("route failure")
        try:
            response = await async_client.post("/api/v1/settings/test-slicer-connection")
        except RuntimeError:
            return  # Transport re-raised the route error: not masked.

    assert response.status_code != 503
    assert response.json().get("detail") != "Authentication service temporarily unavailable"
