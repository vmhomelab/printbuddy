from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app import main


class _AsyncSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _four_nozzle_state(*, nozzle_4: float, nozzle_4_target: float = 210.0) -> SimpleNamespace:
    return SimpleNamespace(
        connected=True,
        state="IDLE",
        progress=0,
        layer_num=0,
        temperatures={
            "nozzle": 25.0,
            "nozzle_target": 200.0,
            "nozzle_2": 26.0,
            "nozzle_2_target": 205.0,
            "nozzle_3": 27.0,
            "nozzle_3_target": 208.0,
            "nozzle_4": nozzle_4,
            "nozzle_4_target": nozzle_4_target,
        },
        stg_cur=0,
        cooling_fan_speed=None,
        big_fan1_speed=None,
        big_fan2_speed=None,
        chamber_light=None,
        active_extruder=3,
        tray_now=255,
        door_open=None,
        raw_data={"ams": []},
    )


@pytest.mark.asyncio
async def test_four_nozzle_changes_and_targets_are_broadcast_and_persisted(monkeypatch):
    """A U1-style fourth nozzle must not be invisible to live state consumers."""

    printer_id = 411
    main._last_status_broadcast.pop(printer_id, None)
    main._nozzle_count_updated.discard(printer_id)

    printer = SimpleNamespace(nozzle_count=1)
    result = MagicMock()
    result.scalar_one_or_none.return_value = printer
    db = AsyncMock()
    db.execute.return_value = result

    with (
        patch.object(main, "async_session", return_value=_AsyncSessionContext(db)),
        patch.object(main, "mqtt_relay") as mqtt_relay,
        patch.object(main, "printer_manager") as printer_manager,
        patch.object(main, "notification_service") as notification_service,
        patch.object(main, "smart_plug_manager") as smart_plug_manager,
        patch.object(main.ws_manager, "send_printer_status", new_callable=AsyncMock) as send_status,
        patch.object(main, "printer_state_to_dict", return_value={"connected": True}),
    ):
        mqtt_relay.on_printer_status = AsyncMock()
        printer_manager.get_printer.return_value = None
        notification_service.on_print_progress = AsyncMock()
        smart_plug_manager.handle_print_state_change = AsyncMock()

        await main.on_printer_status_change(printer_id, _four_nozzle_state(nozzle_4=28.0, nozzle_4_target=210.0))
        await main.on_printer_status_change(printer_id, _four_nozzle_state(nozzle_4=28.0, nozzle_4_target=220.0))
        await main.on_printer_status_change(printer_id, _four_nozzle_state(nozzle_4=120.0, nozzle_4_target=220.0))

    assert printer.nozzle_count == 4
    assert db.commit.await_count == 1
    assert send_status.await_count == 3


@pytest.mark.asyncio
async def test_nozzle_count_persistence_retries_after_database_failure():
    """A transient database failure must not disable later capability detection."""

    printer_id = 412
    main._last_status_broadcast.pop(printer_id, None)
    main._nozzle_count_updated.discard(printer_id)

    printer = SimpleNamespace(nozzle_count=1)
    result = MagicMock()
    result.scalar_one_or_none.return_value = printer
    db = AsyncMock()
    db.execute.side_effect = [RuntimeError("database unavailable"), result]

    with (
        patch.object(main, "async_session", return_value=_AsyncSessionContext(db)),
        patch.object(main, "mqtt_relay") as mqtt_relay,
        patch.object(main, "printer_manager") as printer_manager,
        patch.object(main, "notification_service") as notification_service,
        patch.object(main, "smart_plug_manager") as smart_plug_manager,
        patch.object(main.ws_manager, "send_printer_status", new_callable=AsyncMock) as send_status,
        patch.object(main, "printer_state_to_dict", return_value={"connected": True}),
        # With a cold settings cache this would read the DB through the same
        # mocked session and use up db.execute's side effects.
        patch.object(main, "_get_progress_milestone_mode", new_callable=AsyncMock, return_value="layers"),
    ):
        mqtt_relay.on_printer_status = AsyncMock()
        printer_manager.get_printer.return_value = None
        notification_service.on_print_progress = AsyncMock()
        smart_plug_manager.handle_print_state_change = AsyncMock()

        await main.on_printer_status_change(printer_id, _four_nozzle_state(nozzle_4=28.0))
        assert printer_id not in main._nozzle_count_updated

        await main.on_printer_status_change(printer_id, _four_nozzle_state(nozzle_4=29.0))

    assert printer.nozzle_count == 4
    assert db.commit.await_count == 1
    assert send_status.await_count == 2
    assert printer_id in main._nozzle_count_updated
