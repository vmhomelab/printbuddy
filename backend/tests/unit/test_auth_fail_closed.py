"""Regression tests for fail-closed authentication-state probing.

The auth-state probe must not treat database errors as "auth disabled". If the
settings row is absent, auth is legitimately unconfigured and returns False. Any
actual database/probe exception must propagate so callers deny the request.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.core.auth import is_auth_enabled


@pytest.mark.asyncio
async def test_is_auth_enabled_propagates_db_exception_instead_of_failing_open():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OSError("simulated file-descriptor exhaustion"))

    with pytest.raises(OSError, match="simulated file-descriptor exhaustion"):
        await is_auth_enabled(db)


@pytest.mark.asyncio
async def test_is_auth_enabled_returns_false_when_settings_row_absent():
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await is_auth_enabled(db) is False


@pytest.mark.asyncio
async def test_is_auth_enabled_returns_true_when_setting_value_is_true():
    setting = MagicMock()
    setting.value = "true"
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=setting)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await is_auth_enabled(db) is True


@pytest.mark.asyncio
async def test_is_auth_enabled_returns_false_when_setting_value_is_false():
    setting = MagicMock()
    setting.value = "false"
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=setting)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await is_auth_enabled(db) is False
