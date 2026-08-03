"""Tests for database engine operational tuning."""

from types import SimpleNamespace
from unittest.mock import patch


def test_postgres_engine_uses_configurable_pool_settings():
    from backend.app.core import database

    fake_settings = SimpleNamespace(
        database_url="postgresql+asyncpg://user:pass@db/printbuddy",
        debug=False,
        db_pool_size=33,
        db_max_overflow=44,
        db_pool_timeout=12,
        db_pool_recycle=345,
    )

    with (
        patch.object(database, "settings", fake_settings),
        patch.object(database, "is_sqlite", return_value=False),
        patch.object(database, "create_async_engine") as create_engine,
        patch.object(database.event, "listens_for", lambda *args, **kwargs: (lambda fn: fn)),
    ):
        engine = database._create_engine()

    assert engine == create_engine.return_value
    create_engine.assert_called_once_with(
        fake_settings.database_url,
        echo=False,
        pool_size=33,
        max_overflow=44,
        pool_timeout=12,
        pool_recycle=345,
    )


def test_sqlite_engine_keeps_sqlite_specific_pool_defaults():
    from backend.app.core import database

    fake_settings = SimpleNamespace(
        database_url="sqlite+aiosqlite:///tmp/printbuddy.db",
        debug=True,
        db_pool_size=33,
        db_max_overflow=44,
        db_pool_timeout=12,
        db_pool_recycle=345,
    )

    with (
        patch.object(database, "settings", fake_settings),
        patch.object(database, "is_sqlite", return_value=True),
        patch.object(database, "create_async_engine") as create_engine,
        patch.object(database.event, "listen") as listen,
    ):
        engine = database._create_engine()

    assert engine == create_engine.return_value
    create_engine.assert_called_once_with(
        fake_settings.database_url,
        echo=True,
        pool_size=20,
        max_overflow=200,
    )
    listen.assert_called_once()
