"""Tests for native Notify Live Activity lifecycle management."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app.models.notification import NotificationProvider
from backend.app.models.notification_live_activity import NotificationLiveActivity
from backend.app.models.printer import Printer
from backend.app.services.notify_live_activity_client import NotifyLiveActivityError
from backend.app.services.notify_live_activity_service import NotifyLiveActivityService


@pytest.fixture
def live_config():
    return {
        "device_id": "DEVICE123",
        "device_token": "token",
        "base_url": "https://push.getnotifyapp.com",
        "live_activities_enabled": True,
        "live_activity_end_keep_for_seconds": 300,
    }


@pytest.fixture
async def notify_provider(db_session, live_config):
    provider = NotificationProvider(
        name="Notify",
        provider_type="notify",
        enabled=True,
        config=json.dumps(live_config),
        on_print_start=False,
        on_print_complete=True,
        on_print_failed=True,
        on_print_stopped=True,
        on_print_progress=False,
    )
    db_session.add(provider)
    await db_session.commit()
    await db_session.refresh(provider)
    return provider


@pytest.mark.asyncio
async def test_print_start_creates_live_activity_row(db_session, notify_provider):
    client = AsyncMock()
    client.start = AsyncMock(return_value="activity-123")
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_start(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        data={"filename": "dragon.3mf", "subtask_id": "task-1", "remaining_time": 5400},
    )

    client.start.assert_awaited_once()
    activity = await db_session.scalar(select(NotificationLiveActivity))
    assert activity is not None
    assert activity.provider_id == notify_provider.id
    assert activity.printer_id == 7
    assert activity.activity_id == "activity-123"
    assert activity.subtask_id == "task-1"
    assert activity.filename == "dragon.3mf"
    assert activity.state == "active"


@pytest.mark.asyncio
async def test_duplicate_print_start_ends_existing_activity_first(db_session, notify_provider):
    existing = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="old-activity",
        subtask_id="old-task",
        filename="old.3mf",
        state="active",
    )
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.start = AsyncMock(return_value="new-activity")
    client.end = AsyncMock(return_value=None)
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_start(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        data={"filename": "new.3mf", "subtask_id": "new-task"},
    )

    client.end.assert_awaited_once()
    activities = (await db_session.scalars(select(NotificationLiveActivity).order_by(NotificationLiveActivity.id))).all()
    assert [activity.state for activity in activities] == ["ended", "active"]
    assert activities[-1].activity_id == "new-activity"


@pytest.mark.asyncio
async def test_print_progress_updates_existing_activity(db_session, notify_provider):
    activity = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="activity-123",
        subtask_id="task-1",
        filename="dragon.3mf",
        state="active",
    )
    db_session.add(activity)
    await db_session.commit()

    client = AsyncMock()
    client.update = AsyncMock(return_value=None)
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_progress(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=62,
        remaining_time=1800,
        subtask_id="task-1",
    )

    client.update.assert_awaited_once()
    await db_session.refresh(activity)
    assert activity.last_progress == 62
    assert activity.last_remaining_time == 1800


@pytest.mark.asyncio
async def test_print_progress_creates_missing_activity_for_running_print(db_session, notify_provider):
    client = AsyncMock()
    client.start = AsyncMock(return_value="activity-created-by-progress")
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_progress(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=5.36,
        remaining_time=360,
        subtask_id="task-1",
        layer_num=3,
        total_layers=56,
    )

    client.start.assert_awaited_once()
    payload = client.start.await_args.args[0]
    assert payload["body"] == "5% · Layer 3 / 56"
    assert payload["progress"] == 5.36
    activity = await db_session.scalar(select(NotificationLiveActivity))
    assert activity is not None
    assert activity.provider_id == notify_provider.id
    assert activity.printer_id == 7
    assert activity.activity_id == "activity-created-by-progress"
    assert activity.subtask_id == "task-1"
    assert activity.last_progress == 5.36
    assert activity.last_layer_num == 3
    assert activity.last_total_layers == 56


@pytest.mark.asyncio
async def test_print_progress_replaces_gone_activity(db_session, notify_provider):
    activity = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="overdue-activity",
        subtask_id="task-1",
        filename="dragon.3mf",
        state="active",
    )
    db_session.add(activity)
    await db_session.commit()

    client = AsyncMock()
    client.update = AsyncMock(
        side_effect=NotifyLiveActivityError(
            'Notify Live Activity request failed with HTTP 410: {"error":"Gone"}',
            status_code=410,
            retryable=False,
        )
    )
    client.start = AsyncMock(return_value="replacement-activity")
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_progress(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=50,
        remaining_time=900,
        subtask_id="task-1",
        layer_num=1,
        total_layers=56,
    )

    client.update.assert_awaited_once()
    client.start.assert_awaited_once()
    activities = (await db_session.scalars(select(NotificationLiveActivity).order_by(NotificationLiveActivity.id))).all()
    assert [row.state for row in activities] == ["ended", "active"]
    assert activities[-1].activity_id == "replacement-activity"
    assert activities[-1].last_progress == 50
    assert activities[-1].last_remaining_time == 900


@pytest.mark.asyncio
async def test_print_start_replaces_gone_existing_activity(db_session, notify_provider):
    existing = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="overdue-activity",
        subtask_id="old-task",
        filename="old.3mf",
        state="active",
    )
    db_session.add(existing)
    await db_session.commit()

    client = AsyncMock()
    client.end = AsyncMock(
        side_effect=NotifyLiveActivityError(
            'Notify Live Activity request failed with HTTP 410: {"error":"Gone"}',
            status_code=410,
            retryable=False,
        )
    )
    client.start = AsyncMock(return_value="new-activity")
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_start(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        data={"filename": "new.3mf", "subtask_id": "new-task", "progress": 0},
    )

    client.end.assert_awaited_once()
    client.start.assert_awaited_once()
    activities = (await db_session.scalars(select(NotificationLiveActivity).order_by(NotificationLiveActivity.id))).all()
    assert [row.state for row in activities] == ["ended", "active"]
    assert activities[-1].activity_id == "new-activity"


@pytest.mark.asyncio
async def test_print_complete_ends_activity_and_marks_row_ended(db_session, notify_provider):
    activity = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="activity-123",
        subtask_id="task-1",
        filename="dragon.3mf",
        state="active",
    )
    db_session.add(activity)
    await db_session.commit()

    client = AsyncMock()
    client.end = AsyncMock(return_value=None)
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_end(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        status="completed",
        data={"filename": "dragon.3mf", "subtask_id": "task-1"},
    )

    client.end.assert_awaited_once()
    await db_session.refresh(activity)
    assert activity.state == "ended"
    assert activity.ended_at is not None


@pytest.mark.asyncio
async def test_keepalive_updates_active_activity_from_current_printer_state(db_session, notify_provider):
    activity = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="activity-123",
        subtask_id="task-1",
        filename="dragon.3mf",
        state="active",
    )
    db_session.add(activity)
    await db_session.commit()

    printer_state = type(
        "PrinterState",
        (),
        {
            "connected": True,
            "state": "RUNNING",
            "current_print": "dragon.3mf",
            "subtask_name": "dragon.3mf",
            "subtask_id": "task-1",
            "progress": 64,
            "remaining_time": 45,
            "layer_num": 32,
            "total_layers": 100,
        },
    )()
    client = AsyncMock()
    client.update = AsyncMock(return_value=None)
    service = NotifyLiveActivityService(
        client_factory=lambda config: client,
        status_getter=lambda printer_id: printer_state,
        printer_name_getter=lambda printer_id: "Workshop P1S",
    )

    await service.keepalive_once(db_session)

    client.update.assert_awaited_once()
    payload = client.update.await_args.args[1]
    assert payload["progress"] == 32
    assert payload["endsIn"] == 2700
    await db_session.refresh(activity)
    assert activity.last_progress == 32
    assert activity.last_remaining_time == 2700


@pytest.mark.asyncio
async def test_keepalive_creates_missing_activity_for_running_printer(db_session, notify_provider):
    printer = Printer(
        id=7,
        name="Workshop P1S",
        serial_number="SERIAL7",
        ip_address="10.0.0.7",
        access_code="12345678",
        provider="bambu",
        model="P1S",
        location="Workshop",
    )
    db_session.add(printer)
    await db_session.commit()

    printer_state = type(
        "PrinterState",
        (),
        {
            "connected": True,
            "state": "RUNNING",
            "current_print": "dragon.3mf",
            "subtask_name": "dragon.3mf",
            "subtask_id": "task-1",
            "progress": 35,
            "remaining_time": 11,
            "layer_num": 1,
            "total_layers": 128,
        },
    )()
    client = AsyncMock()
    client.start = AsyncMock(return_value="activity-created-by-keepalive")
    service = NotifyLiveActivityService(
        client_factory=lambda config: client,
        status_getter=lambda printer_id: printer_state,
        printer_name_getter=lambda printer_id: "Workshop P1S",
    )

    await service.keepalive_once(db_session)

    client.start.assert_awaited_once()
    payload = client.start.await_args.args[0]
    assert payload["title"] == "Workshop P1S"
    assert payload["progress"] == 0.78
    activity = await db_session.scalar(select(NotificationLiveActivity))
    assert activity is not None
    assert activity.provider_id == notify_provider.id
    assert activity.printer_id == 7
    assert activity.activity_id == "activity-created-by-keepalive"
    assert activity.state == "active"


@pytest.mark.asyncio
async def test_keepalive_ends_activity_when_printer_is_no_longer_running(db_session, notify_provider):
    activity = NotificationLiveActivity(
        provider_id=notify_provider.id,
        printer_id=7,
        activity_id="activity-123",
        subtask_id="task-1",
        filename="dragon.3mf",
        state="active",
    )
    db_session.add(activity)
    await db_session.commit()

    printer_state = type("PrinterState", (), {"connected": True, "state": "IDLE"})()
    client = AsyncMock()
    client.end = AsyncMock(return_value=None)
    service = NotifyLiveActivityService(
        client_factory=lambda config: client,
        status_getter=lambda printer_id: printer_state,
        printer_name_getter=lambda printer_id: "Workshop P1S",
    )

    await service.keepalive_once(db_session)

    client.end.assert_awaited_once()
    await db_session.refresh(activity)
    assert activity.state == "ended"


@pytest.mark.asyncio
async def test_string_true_live_activity_config_enables_activity(db_session, notify_provider):
    notify_provider.config = json.dumps({"device_id": "DEVICE123", "device_token": "token", "live_activities_enabled": "true"})
    await db_session.commit()

    client = AsyncMock()
    client.start = AsyncMock(return_value="activity-123")
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_start(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        data={"filename": "dragon.3mf"},
    )

    client.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_disabled_live_activity_config_does_not_call_notify(db_session, notify_provider):
    notify_provider.config = json.dumps({"device_id": "DEVICE123", "device_token": "token", "live_activities_enabled": False})
    await db_session.commit()

    client = AsyncMock()
    service = NotifyLiveActivityService(client_factory=lambda config: client)

    await service.on_print_start(
        db_session,
        printer_id=7,
        printer_name="Workshop P1S",
        data={"filename": "dragon.3mf"},
    )

    client.start.assert_not_called()
    activity = await db_session.scalar(select(NotificationLiveActivity))
    assert activity is None
