"""Regression tests for the print almost-done notification threshold."""


def test_print_almost_done_threshold_is_97_percent():
    from backend.app.main import PRINT_ALMOST_DONE_PROGRESS_THRESHOLD

    assert PRINT_ALMOST_DONE_PROGRESS_THRESHOLD == 97
