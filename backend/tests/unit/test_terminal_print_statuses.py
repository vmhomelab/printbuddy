"""PB-2: a "stopped" print is terminal like "aborted"."""

from backend.app.main import TERMINAL_PRINT_STATUSES


def test_stopped_is_a_terminal_print_status():
    # Gets an archive completed_at (duration in notifications) and raises the
    # plate-clear gate so the next queued print does not start on a used bed.
    assert "stopped" in TERMINAL_PRINT_STATUSES


def test_terminal_print_statuses_keep_existing_statuses():
    assert set(TERMINAL_PRINT_STATUSES) >= {"completed", "failed", "aborted", "cancelled"}
