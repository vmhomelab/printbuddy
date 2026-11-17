"""A notification must never be sent while holding the SQLite write lock (#2770).

The reporter's bundle has two "database is locked" failures, and both sit inside
a Discord connect timeout::

    17:36:55  Sending humidity alarm ... 15.0% > 14.0%
    17:37:12  WARNING  Printer sensor history recording failed: database is locked
    17:37:25  ERROR    httpx.ConnectTimeout          <- exactly 30.000s later

The mechanism is not contention from writing too much. The AMS sensor loop does
``db.add(history)`` and only commits *after* the alarms have been dispatched, so
the first SELECT inside the notification path used to autoflush that pending
INSERT — opening a write transaction — and the provider was then contacted over
the network with that transaction still open. SQLite allows one writer, and the
30 s connect timeout comfortably outlived the 15 s ``busy_timeout``, so unrelated
background tasks failed.

These tests pin the two reads that run before the network call. They assert the
caller's pending row is still unflushed afterwards, which is the same thing as
"no write transaction was opened on its behalf" and holds on any dialect.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.app.models  # noqa: F401 - populate Base.metadata
from backend.app.core.database import Base
from backend.app.models.notification import NotificationProvider
from backend.app.models.notification_template import NotificationTemplate
from backend.app.services.notification_service import NotificationService


@pytest.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'notify-lock.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _pending_row() -> NotificationProvider:
    """A row the caller has added but not committed — the sensor loop's position."""
    return NotificationProvider(name="pending", provider_type="discord", config="{}", enabled=False)


@pytest.mark.asyncio
async def test_provider_lookup_does_not_flush_the_callers_pending_writes(session):
    service = NotificationService()
    session.add(NotificationProvider(name="Discord", provider_type="discord", config="{}", enabled=True))
    await session.commit()

    pending = _pending_row()
    session.add(pending)

    providers = await service._get_providers_for_event(session, "on_ams_drying_suspended")

    assert [p.name for p in providers] == ["Discord"]
    assert pending in session.new, "the caller's pending INSERT was flushed, taking the SQLite write lock"


@pytest.mark.asyncio
async def test_template_lookup_does_not_flush_the_callers_pending_writes(session):
    service = NotificationService()
    session.add(
        NotificationTemplate(
            event_type="ams_drying_suspended",
            name="Auto-Drying Suspended",
            title_template="t",
            body_template="b",
            is_default=True,
        )
    )
    await session.commit()

    pending = _pending_row()
    session.add(pending)

    template = await service._get_template(session, "ams_drying_suspended")

    assert template is not None
    assert pending in session.new, "the caller's pending INSERT was flushed, taking the SQLite write lock"


@pytest.mark.asyncio
async def test_connect_timeout_stays_under_the_sqlite_busy_timeout():
    """15 s is the ``busy_timeout`` set in database.py. A connect timeout at or
    above it guarantees the "database is locked" failure whenever a site's
    internet is down, whatever else is fixed."""
    service = NotificationService()
    client = await service._get_client()
    try:
        assert client.timeout.connect is not None
        assert client.timeout.connect < 15.0
        # The body still gets the generous budget — image uploads on a slow
        # uplink must not start failing.
        assert client.timeout.read == 30.0
        assert client.timeout.write == 30.0
    finally:
        await service.close()
