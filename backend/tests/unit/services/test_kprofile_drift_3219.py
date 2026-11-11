"""A slot that loses its K-profile selection gets the stored one back (#3219).

An X1 Carbon power-cycled mid-print came back with every AMS slot on
``cali_idx: -1`` while tags, spools and remain% were unchanged. ``on_ams_change``
never fired, so nothing restored the selections, and two queued jobs printed
on the default K.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services import kprofile_drift
from backend.app.services.slot_kprofile import SlotKProfile

PRINTER = 7


def _tray(tray_id, cali_idx=-1, tray_type="PLA"):
    return {"id": str(tray_id), "tray_type": tray_type, "cali_idx": cali_idx, "tray_info_idx": "GFA00"}


def _state(trays, *, state="IDLE", connected=True, vt_tray=None, model_nozzles=1):
    raw = {"ams": {"ams": [{"id": "0", "tray": trays}]}}
    if vt_tray is not None:
        raw["vt_tray"] = vt_tray
    nozzles = [SimpleNamespace(nozzle_diameter="0.4", nozzle_type="") for _ in range(model_nozzles)]
    return SimpleNamespace(
        raw_data=raw,
        connected=connected,
        state=state,
        nozzles=nozzles,
        ams_extruder_map=None,
        ams_switch_inlet=None,
    )


def _profile(cali_idx, name="PLA Basic 0.025"):
    return SlotKProfile(cali_idx=cali_idx, k_value=0.025, name=name, extruder=0, filament_id="GFA00")


@pytest.fixture(autouse=True)
def _clean_bookkeeping():
    kprofile_drift._watches.clear()
    kprofile_drift._default_chosen.clear()
    kprofile_drift._running.clear()
    yield
    kprofile_drift._watches.clear()
    kprofile_drift._default_chosen.clear()
    kprofile_drift._running.clear()


@pytest.fixture
def env():
    """Patch the printer, the database and the stored-profile lookup."""
    client = MagicMock()
    stored: dict[tuple[int, int], SlotKProfile] = {}
    holder = SimpleNamespace(state=None, client=client, stored=stored, model="X1C")

    async def lookup(_db, _printer_id, ams_id, tray_id, *_args, **_kwargs):
        return stored.get((ams_id, tray_id))

    @asynccontextmanager
    async def session():
        yield MagicMock()

    pm = MagicMock()
    pm.get_status.side_effect = lambda _pid: holder.state
    pm.get_client.side_effect = lambda _pid: holder.client
    pm.get_model.side_effect = lambda _pid: holder.model

    with (
        patch.object(kprofile_drift, "printer_manager", pm),
        patch.object(kprofile_drift, "async_session", session),
        patch.object(kprofile_drift, "find_slot_kprofile_for_extruder", AsyncMock(side_effect=lookup)) as finder,
    ):
        holder.finder = finder
        yield holder


def _selected(client):
    return [
        (c.kwargs["ams_id"], c.kwargs["tray_id"], c.kwargs["cali_idx"])
        for c in client.extrusion_cali_sel.call_args_list
    ]


@pytest.mark.asyncio
async def test_lost_selection_is_restored(env):
    env.state = _state([_tray(0), _tray(1)])
    env.stored[(0, 0)] = _profile(9354)
    env.stored[(0, 1)] = _profile(3175)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 2

    assert sorted(_selected(env.client)) == [(0, 0, 9354), (0, 1, 3175)]
    call = env.client.extrusion_cali_sel.call_args_list[0]
    assert call.kwargs["filament_id"] == "GFA00"
    assert call.kwargs["nozzle_diameter"] == "0.4"


@pytest.mark.asyncio
async def test_missing_cali_idx_counts_as_lost(env):
    tray = _tray(0)
    del tray["cali_idx"]
    env.state = _state([tray])
    env.stored[(0, 0)] = _profile(9354)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1


@pytest.mark.asyncio
async def test_a_different_real_profile_is_left_alone(env):
    # Picked on purpose, in Bambu Studio or Printbuddy's Configure Slot dialog.
    env.state = _state([_tray(0, cali_idx=5)])
    env.stored[(0, 0)] = _profile(9354)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0
    env.client.extrusion_cali_sel.assert_not_called()


@pytest.mark.asyncio
async def test_slot_without_stored_profile_is_left_on_default(env):
    env.state = _state([_tray(0)])

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0
    env.client.extrusion_cali_sel.assert_not_called()


@pytest.mark.asyncio
async def test_empty_slot_is_skipped(env):
    env.state = _state([_tray(0, tray_type="")])
    env.stored[(0, 0)] = _profile(9354)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0
    env.finder.assert_not_called()


@pytest.mark.asyncio
async def test_deliberate_default_pick_is_respected(env):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)
    kprofile_drift.note_slot_configured(PRINTER, 0, 0, -1)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0

    # Picking a real profile again in the dialog lifts it.
    kprofile_drift.note_slot_configured(PRINTER, 0, 0, 9354)
    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1


@pytest.mark.asyncio
async def test_default_pick_survives_the_push_that_still_shows_the_old_profile(env):
    env.stored[(0, 0)] = _profile(9354)
    kprofile_drift.note_slot_configured(PRINTER, 0, 0, -1)

    # The push right after the pick can still carry the previous selection.
    env.state = _state([_tray(0, cali_idx=9354)])
    await kprofile_drift.reapply_lost_kprofiles(PRINTER)
    env.state = _state([_tray(0)])

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0


@pytest.mark.asyncio
async def test_emptying_the_slot_clears_a_default_pick(env):
    env.stored[(0, 0)] = _profile(9354)
    kprofile_drift.note_slot_configured(PRINTER, 0, 0, -1)

    env.state = _state([_tray(0, tray_type="")])
    await kprofile_drift.reapply_lost_kprofiles(PRINTER)
    env.state = _state([_tray(0)])

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1


@pytest.mark.asyncio
async def test_retries_are_spaced_and_capped(env):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)
    clock = [1000.0]

    with patch.object(kprofile_drift.time, "monotonic", side_effect=lambda: clock[0]):
        assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1
        # The next push, before the printer has applied it: no resend.
        assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0

        for _ in range(kprofile_drift.MAX_ATTEMPTS + 2):
            clock[0] += kprofile_drift.RETRY_INTERVAL_S
            await kprofile_drift.reapply_lost_kprofiles(PRINTER)

    assert len(_selected(env.client)) == kprofile_drift.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_a_selection_that_sticks_resets_the_retry_count(env):
    env.stored[(0, 0)] = _profile(9354)
    env.state = _state([_tray(0)])
    await kprofile_drift.reapply_lost_kprofiles(PRINTER)

    env.state = _state([_tray(0, cali_idx=9354)])
    await kprofile_drift.reapply_lost_kprofiles(PRINTER)
    # Lost again later, e.g. the next power cycle: restored at once.
    env.state = _state([_tray(0)])

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1


@pytest.mark.asyncio
async def test_disconnect_forgets_retries(env):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)
    await kprofile_drift.reapply_lost_kprofiles(PRINTER)

    kprofile_drift.forget_printer(PRINTER)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1


@pytest.mark.asyncio
async def test_dispatch_guard_ignores_the_retry_interval(env):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)
    await kprofile_drift.reapply_lost_kprofiles(PRINTER)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER, throttle=False) == 1


@pytest.mark.asyncio
async def test_dispatch_guard_runs_while_an_idle_pass_is_in_flight(env):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)
    kprofile_drift._running.add(PRINTER)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0
    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER, throttle=False) == 1


@pytest.mark.asyncio
async def test_dispatch_guard_only_touches_the_trays_the_job_uses(env):
    env.state = _state([_tray(0), _tray(1), _tray(2)])
    for tray_id in range(3):
        env.stored[(0, tray_id)] = _profile(100 + tray_id)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER, {2}, throttle=False) == 1
    assert _selected(env.client) == [(0, 2, 102)]


@pytest.mark.asyncio
async def test_external_spool_is_covered(env):
    env.state = _state([], vt_tray=[{"id": "254", "tray_type": "PETG", "cali_idx": -1}])
    env.stored[(255, 0)] = _profile(42)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER, {254}, throttle=False) == 1
    assert _selected(env.client) == [(255, 0, 42)]


@pytest.mark.asyncio
async def test_dual_nozzle_with_unknown_routing_is_not_guessed(env):
    env.model = "H2D"
    env.state = _state([_tray(0)], model_nozzles=2)
    env.stored[(0, 0)] = _profile(9354)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0
    env.finder.assert_not_called()


@pytest.mark.asyncio
async def test_disconnected_printer_is_skipped(env):
    env.state = _state([_tray(0)], connected=False)
    env.stored[(0, 0)] = _profile(9354)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 0


@pytest.mark.asyncio
async def test_single_nozzle_external_spool_finds_a_profile_under_either_extruder(env):
    """X1C external holder: slot_extruder says 1, the spool form stores 0."""
    env.state = _state([], vt_tray=[{"id": "254", "tray_type": "PETG", "cali_idx": -1}])
    seen = []

    async def lookup(_db, _pid, ams_id, tray_id, extruder, *_a, **_k):
        seen.append(extruder)
        return _profile(42) if extruder == 1 else None

    env.finder.side_effect = lookup

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1
    assert seen == [0, 1]


@pytest.mark.asyncio
async def test_single_nozzle_ams_slot_asks_for_extruder_zero_only(env):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)

    await kprofile_drift.reapply_lost_kprofiles(PRINTER)

    assert [c.args[4] for c in env.finder.await_args_list] == [0]


@pytest.mark.asyncio
async def test_dual_nozzle_uses_only_the_slot_nozzle(env):
    env.model = "H2D"
    env.state = _state([_tray(0)], model_nozzles=2)
    env.state.ams_extruder_map = {"0": 1}
    env.stored[(0, 0)] = _profile(9354)

    assert await kprofile_drift.reapply_lost_kprofiles(PRINTER) == 1
    assert [c.args[4] for c in env.finder.await_args_list] == [1]


@pytest.mark.asyncio
async def test_slot_with_nothing_stored_is_looked_up_rarely(env):
    env.state = _state([_tray(0)])
    clock = [1000.0]

    with patch.object(kprofile_drift.time, "monotonic", side_effect=lambda: clock[0]):
        await kprofile_drift.reapply_lost_kprofiles(PRINTER)
        clock[0] += kprofile_drift.RETRY_INTERVAL_S * 2
        assert kprofile_drift.needs_check(PRINTER, env.state) is False
        clock[0] += kprofile_drift.NO_PROFILE_RECHECK_S
        assert kprofile_drift.needs_check(PRINTER, env.state) is True

    assert env.finder.await_count == 1


@pytest.mark.asyncio
async def test_giving_up_is_logged_once_after_the_last_attempt_had_time_to_land(env, caplog):
    env.state = _state([_tray(0)])
    env.stored[(0, 0)] = _profile(9354)
    clock = [1000.0]

    with patch.object(kprofile_drift.time, "monotonic", side_effect=lambda: clock[0]):
        for _ in range(kprofile_drift.MAX_ATTEMPTS):
            await kprofile_drift.reapply_lost_kprofiles(PRINTER)
            # Not yet: the last send may still stick.
            assert "giving up" not in caplog.text
            clock[0] += kprofile_drift.RETRY_INTERVAL_S
        for _ in range(3):
            kprofile_drift.needs_check(PRINTER, env.state)
            clock[0] += kprofile_drift.RETRY_INTERVAL_S

    assert caplog.text.count("giving up") == 1


class TestNeedsCheck:
    def test_idle_with_a_lost_slot(self):
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0)])) is True

    @pytest.mark.parametrize("gcode_state", ["RUNNING", "PAUSE", "PREPARE", "SLICING", "unknown"])
    def test_never_while_a_print_may_be_running(self, gcode_state):
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0)], state=gcode_state)) is False

    @pytest.mark.parametrize("gcode_state", ["IDLE", "FINISH", "FAILED"])
    def test_idle_states(self, gcode_state):
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0)], state=gcode_state)) is True

    def test_not_when_every_slot_has_a_profile(self):
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0, cali_idx=3)])) is False

    def test_not_while_disconnected(self):
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0)], connected=False)) is False

    def test_not_while_a_pass_is_running(self):
        kprofile_drift._running.add(PRINTER)
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0)])) is False

    def test_not_again_within_the_retry_interval(self):
        kprofile_drift._watches[(PRINTER, 0, 0)] = kprofile_drift._SlotWatch(
            next_check=kprofile_drift.time.monotonic() + 30
        )
        assert kprofile_drift.needs_check(PRINTER, _state([_tray(0)])) is False


@pytest.mark.asyncio
async def test_status_handler_spawns_the_check_and_forgets_on_disconnect():
    """The #3219 trigger lives in on_printer_status_change: every push, idle only."""
    from backend.app import main

    spawned = []

    def fake_spawn(coro, name=None):
        spawned.append(name)
        coro.close()

    with (
        patch.object(main, "spawn_background_task", side_effect=fake_spawn),
        patch.object(main.kprofile_drift, "needs_check", return_value=True) as needs_check,
        patch.object(main.kprofile_drift, "forget_printer") as forget,
        patch.object(main, "ws_manager") as ws,
    ):
        ws.send_printer_status = AsyncMock()
        state = MagicMock()
        state.connected = True
        state.state = "IDLE"
        state.nozzles = []
        try:
            await main.on_printer_status_change(PRINTER, state)
        except Exception:
            pass  # Later parts of the handler need more of a real state.
        assert f"reapply-kprofiles-{PRINTER}" in spawned
        needs_check.assert_called_once_with(PRINTER, state)

        spawned.clear()
        state.connected = False
        try:
            await main.on_printer_status_change(PRINTER, state)
        except Exception:
            pass
        assert f"reapply-kprofiles-{PRINTER}" not in spawned
        forget.assert_called_with(PRINTER)


@pytest.mark.asyncio
async def test_a_failing_check_does_not_stop_the_status_broadcast():
    from backend.app import main

    with (
        patch.object(main.kprofile_drift, "needs_check", side_effect=RuntimeError("boom")),
        patch.object(main, "ws_manager") as ws,
        patch.object(main, "spawn_background_task", side_effect=lambda coro, name=None: coro.close()),
    ):
        ws.send_printer_status = AsyncMock()
        state = MagicMock()
        state.connected = True
        state.state = "IDLE"
        state.nozzles = []
        try:
            await main.on_printer_status_change(PRINTER, state)
        except RuntimeError as exc:
            pytest.fail(f"K-profile check escaped the status handler: {exc}")
        except Exception:
            pass  # Later parts of the handler need more of a real state.
