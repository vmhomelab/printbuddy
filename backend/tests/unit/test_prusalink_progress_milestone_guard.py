"""Regression tests for PrusaLink progress milestone notification guarding."""

from __future__ import annotations

import logging

from backend.app import main


def setup_function():
    printer_id = 3
    main._last_progress_milestone.pop(printer_id, None)
    main._progress_job_key.pop(printer_id, None)
    main._last_progress_value.pop(printer_id, None)
    main._pending_progress_milestone.pop(printer_id, None)


def test_prusalink_requires_second_sample_before_progress_milestone():
    logger = logging.getLogger(__name__)

    first = main._should_send_progress_milestone(
        3,
        provider="prusalink",
        progress=75.0,
        current_milestone=75,
        last_milestone=0,
        logger=logger,
    )

    assert first is False
    assert main._pending_progress_milestone[3] == 75

    second = main._should_send_progress_milestone(
        3,
        provider="prusalink",
        progress=76.0,
        current_milestone=75,
        last_milestone=0,
        logger=logger,
    )

    assert second is True
    assert 3 not in main._pending_progress_milestone


def test_prusalink_low_progress_reset_discards_pending_milestone():
    logger = logging.getLogger(__name__)

    assert (
        main._should_send_progress_milestone(
            3,
            provider="prusalink",
            progress=75.0,
            current_milestone=75,
            last_milestone=0,
            logger=logger,
        )
        is False
    )
    assert main._pending_progress_milestone[3] == 75

    main._reset_progress_notification_tracking(3)

    assert main._last_progress_milestone[3] == 0
    assert 3 not in main._pending_progress_milestone
    assert 3 not in main._last_progress_value


def test_non_prusalink_keeps_single_sample_milestone_behavior():
    assert (
        main._should_send_progress_milestone(
            3,
            provider="bambu",
            progress=75.0,
            current_milestone=75,
            last_milestone=0,
            logger=logging.getLogger(__name__),
        )
        is True
    )
