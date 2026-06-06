"""Regression tests for reconnecting saved printers during app startup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.printer_manager import init_printer_connections


@pytest.mark.asyncio
async def test_startup_keeps_running_when_saved_printer_is_unreachable(caplog):
    """A powered-off or unreachable saved printer must not crash the whole app.

    Home Assistant add-on startup hit this path with a saved Moonraker printer
    whose host returned ``httpx.ConnectError: [Errno 113] No route to host``.
    The app should mark/log that one printer as failed and continue trying the
    remaining active printers instead of letting Uvicorn lifespan fail.
    """
    unreachable = SimpleNamespace(id=1, name="Neptune 4 Pro")
    reachable = SimpleNamespace(id=2, name="P1S")

    result = MagicMock()
    result.scalars.return_value.all.return_value = [unreachable, reachable]
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    async def connect(printer):
        if printer is unreachable:
            raise RuntimeError("No route to host")
        return True

    with patch(
        "backend.app.services.printer_manager.printer_manager.connect_printer", side_effect=connect
    ) as connect_mock:
        await init_printer_connections(db)

    assert [call.args[0] for call in connect_mock.call_args_list] == [unreachable, reachable]
    assert "Skipping saved printer Neptune 4 Pro during startup" in caplog.text
    assert "No route to host" in caplog.text
