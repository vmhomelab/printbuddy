"""Progress milestones count from the first layer, not from the start of preparation (#3211).

An A1 mini (firmware 01.07.01.00) reports ``mc_percent`` 85 in the first frame
of a print, while still preheating the bed at layer 0. Through its calibration
the value then reads 3, 7, 40 and 44, and the first real layer starts at 45.
Read as progress, the 85 sent the 75% notification together with Print
Started -- with "Unknown" remaining time, since that frame reports 0 -- and
with 75 then on record, 25 and 50 could never fire.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app import main as main_module

pytestmark = pytest.mark.unit

PRINTER = 1


@pytest.fixture(autouse=True)
def _clean_milestones():
    main_module._last_progress_milestone.clear()
    yield
    main_module._last_progress_milestone.clear()


def _frame(progress: float, layer_num: int, total_layers: int = 128, stg_cur: int = 0) -> SimpleNamespace:
    return SimpleNamespace(progress=progress, layer_num=layer_num, total_layers=total_layers, stg_cur=stg_cur)


def _run(frames) -> list[int]:
    sent = []
    for progress, layer, *rest in frames:
        milestone = main_module._progress_milestone_to_notify(PRINTER, _frame(progress, layer, *rest))
        if milestone is not None:
            sent.append(milestone)
    return sent


# The reporter's print, frame by frame from the support bundle: preparation at
# layer 0, then the print proper from layer 1.
A1_MINI_PRINT = [
    (85, 0),
    (3, 0),
    (7, 0),
    (40, 0),
    (44, 0),
    (45, 1),
    (50, 1),
    (52, 2),
    (75, 30),
    (97, 120),
    (100, 128),
]


def test_the_reported_print_sends_each_milestone_once_and_none_at_the_start():
    assert _run(A1_MINI_PRINT) == [25, 50, 75]


def test_nothing_is_sent_during_preparation():
    assert _run(A1_MINI_PRINT[:5]) == []
    assert main_module._last_progress_milestone.get(PRINTER, 0) == 0


def test_the_first_layer_catches_up_to_the_milestone_already_passed():
    """The print proper starts at 45 here, so 25 goes out at 45 -- once."""
    assert _run([(85, 0), (45, 1), (46, 1)]) == [25]


def test_a_printer_without_layer_data_keeps_the_old_behaviour():
    """No layer count means nothing to gate on; never notifying would be worse."""
    assert _run([(10, 0, 0), (30, 0, 0), (60, 0, 0), (80, 0, 0)]) == [25, 50, 75]


def test_without_a_layer_count_the_preparation_stage_holds_it_back():
    """A first frame with no total_layer_num leaves nothing to gate on by layers.

    The A1 mini's preparation stages, from the bundle: 2 (bed preheating),
    4, 14 and 1, then 0 from the first layer. Until the pushall brings the
    total, the stage is what tells preparation from printing.
    """
    frames = [(85, 0, 0, 2), (3, 0, 0, 4), (40, 0, 0, 14), (44, 0, 0, 1), (45, 1, 128, 0), (50, 2, 128, 0)]
    assert _run(frames) == [25, 50]


@pytest.mark.parametrize("no_stage", [-1, 255])
def test_no_stage_at_all_is_not_preparation(no_stage):
    assert _run([(30, 0, 0, no_stage)]) == [25]


def test_a_normal_print_is_unchanged():
    frames = [(1, 1), (24, 10), (25, 11), (49, 20), (50, 21), (74, 30), (75, 31), (100, 40)]
    assert _run(frames) == [25, 50, 75]


@pytest.mark.asyncio
async def test_a_new_print_starts_its_milestones_from_zero():
    """A printer can go from FINISH at 100% straight into the next print.

    The status path only resets on progress below 5 while not printing, which
    that never shows, so the previous print's 75 would block every milestone
    of the next one. The print-start callback resets it.
    """
    assert _run(A1_MINI_PRINT) == [25, 50, 75]

    class _Stop(Exception):
        pass

    # The reset is one of the first things on_print_start does; the rest of it
    # (archiving, usage tracking, notifications) is not under test here, so the
    # call is stopped at the next statement.
    stop_here = SimpleNamespace(pop=MagicMock(side_effect=_Stop))
    with patch.object(main_module, "_kill_switch_notification_tasks", stop_here), pytest.raises(_Stop):
        await main_module.on_print_start(PRINTER, {})

    assert main_module._last_progress_milestone[PRINTER] == 0
    assert _run(A1_MINI_PRINT) == [25, 50, 75]
