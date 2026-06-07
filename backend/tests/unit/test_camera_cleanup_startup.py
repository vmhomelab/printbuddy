"""Regression tests for camera cleanup startup wiring."""

from unittest.mock import MagicMock


def test_camera_cleanup_startup_creates_background_task(monkeypatch):
    """Application startup must not fail because camera cleanup globals are missing."""
    from backend.app import main

    created = []
    fake_task = MagicMock()

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return fake_task

    monkeypatch.setattr(main.asyncio, "create_task", fake_create_task)
    if hasattr(main, "_camera_cleanup_task"):
        monkeypatch.setattr(main, "_camera_cleanup_task", None)

    main.start_camera_cleanup()

    assert created, "camera cleanup coroutine was not scheduled"
    assert main._camera_cleanup_task is fake_task

    main.stop_camera_cleanup()

    fake_task.cancel.assert_called_once_with()
    assert main._camera_cleanup_task is None
