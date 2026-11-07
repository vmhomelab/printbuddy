"""A failed upload must not eat the queue (#3210).

The reporter queued 20 jobs for "any P2S". One P2S's file service was out of
connection slots -- it answered port 990 with ``421 There are too many
connections from your internet address`` -- so every upload to it failed. Each
failure marked the item ``failed``, which left that printer idle, so the next
pass handed it the next item. One item died about every nine seconds: 43 jobs
gone in ten minutes, none printed on that printer.

Two changes, pinned here:

* An upload whose file never reached the printer (handshake refused, cool-off,
  timeout, dropped connection) puts the item back in the queue. Failures that
  would repeat on every retry -- a rejected access code, a full card -- still
  fail it.
* The printer is out of dispatch for a backoff window, so nothing else is
  sent to it, and the item that was put back waits there with a reason.
"""

import asyncio
import time
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.app.models  # noqa: F401 - populate Base.metadata
import backend.app.services.archive as archive_module
import backend.app.services.print_scheduler as scheduler_module
from backend.app.core.database import Base
from backend.app.models.archive import PrintArchive
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.services.bambu_ftp import BambuFTPClient, FtpFailure, FtpFailureKind, UploadCancelled
from backend.app.services.print_scheduler import (
    UPLOAD_FAILURE_BACKOFF_MAX_SECONDS,
    UPLOAD_FAILURE_BACKOFF_SECONDS,
    PrintScheduler,
)

pytestmark = pytest.mark.unit

REFUSING_IP = "10.0.0.8"
HEALTHY_IP = "10.0.0.9"


@pytest.fixture
async def farm(tmp_path):
    """Two printers -- one whose file service refuses everything -- and an item factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    base_dir = tmp_path / "farm"
    (base_dir / "archives").mkdir(parents=True, exist_ok=True)

    async with session_maker() as db:
        refusing = Printer(
            name="P2S-8", serial_number="S8", ip_address=REFUSING_IP, access_code="12345678", model="P2S"
        )
        healthy = Printer(name="P2S-9", serial_number="S9", ip_address=HEALTHY_IP, access_code="12345678", model="P2S")
        db.add_all([refusing, healthy])
        await db.commit()
        ids = SimpleNamespace(refusing=refusing.id, healthy=healthy.id)

    counter = iter(range(1000))

    async def add_item(*, printer_id: int | None = None, target_model: str | None = None) -> int:
        n = next(counter)
        async with session_maker() as db:
            archive_rel = Path("archives") / f"job-{n}.3mf"
            (base_dir / archive_rel).write_bytes(b"archive payload")
            archive = PrintArchive(
                printer_id=printer_id,
                filename=f"job-{n}.3mf",
                file_path=str(archive_rel),
                file_size=15,
                status="completed",
            )
            db.add(archive)
            await db.flush()
            item = PrintQueueItem(
                printer_id=printer_id,
                target_model=target_model,
                archive_id=archive.id,
                status="pending",
                position=n,
            )
            db.add(item)
            await db.commit()
            return item.id

    try:
        yield SimpleNamespace(session_maker=session_maker, base_dir=base_dir, ids=ids, add_item=add_item)
    finally:
        await engine.dispose()


def _upload_refused_by(ip: str, failure: FtpFailure):
    """An upload that fails with *failure* on *ip* and succeeds everywhere else."""

    async def _upload(ip_address, *_args, **kwargs):
        if ip_address != ip:
            return True
        if kwargs.get("failure") is not None:
            kwargs["failure"].failure = failure
        return False

    return _upload


@asynccontextmanager
async def _scheduler(
    ctx,
    upload,
    *,
    busy: set[int] | None = None,
    scheduler: PrintScheduler | None = None,
    waiting_notify: AsyncMock | None = None,
):
    """A scheduler wired to *ctx*'s database, with every printer idle unless in *busy*.

    Pass the same *waiting_notify* to several passes to count notifications
    across them.
    """
    scheduler = scheduler or PrintScheduler()
    busy = busy if busy is not None else set()
    failed_notify = AsyncMock()
    waiting_notify = waiting_notify or AsyncMock()

    def _real_spawn(coro, *, name=None):
        return asyncio.create_task(coro, name=name)

    patches = [
        patch.object(scheduler_module.settings, "base_dir", ctx.base_dir),
        patch.object(archive_module.settings, "base_dir", ctx.base_dir),
        patch.object(archive_module.settings, "archive_dir", ctx.base_dir / "archive"),
        patch("backend.app.services.print_scheduler.async_session", ctx.session_maker),
        patch("backend.app.core.database.async_session", ctx.session_maker),
        patch("backend.app.services.print_scheduler.printer_manager.is_connected", MagicMock(return_value=True)),
        patch(
            "backend.app.services.print_scheduler.printer_manager.get_status",
            MagicMock(return_value=SimpleNamespace(state="IDLE", subtask_id=None, gcode_file=None, raw_data={})),
        ),
        patch(
            "backend.app.services.print_scheduler.printer_manager.is_awaiting_plate_clear",
            MagicMock(return_value=False),
        ),
        patch("backend.app.services.print_scheduler.printer_manager.start_print", MagicMock(return_value=True)),
        patch("backend.app.services.print_scheduler.printer_manager.set_awaiting_plate_clear", MagicMock()),
        patch("backend.app.services.print_scheduler.upload_file_async", upload),
        patch("backend.app.services.print_scheduler.delete_file_async", AsyncMock(return_value=True)),
        patch(
            "backend.app.services.print_scheduler.get_ftp_retry_settings",
            AsyncMock(return_value=(False, 0, 0, 1.0)),
        ),
        patch("backend.app.services.print_scheduler.cache_3mf_download", MagicMock()),
        patch("backend.app.services.print_scheduler.spawn_background_task", _real_spawn),
        patch("backend.app.services.notification_service.notification_service.on_queue_job_started", AsyncMock()),
        patch("backend.app.services.notification_service.notification_service.on_queue_job_failed", failed_notify),
        patch("backend.app.services.notification_service.notification_service.on_queue_job_assigned", AsyncMock()),
        patch("backend.app.services.notification_service.notification_service.on_queue_job_waiting", waiting_notify),
        patch("backend.app.services.mqtt_relay.mqtt_relay.on_queue_job_started", AsyncMock()),
        patch.object(scheduler, "_is_printer_idle", MagicMock(side_effect=lambda pid, *_a, **_k: pid not in busy)),
        patch.object(scheduler, "_ensure_ams_mapping", AsyncMock(return_value=None)),
        patch.object(scheduler, "_block_on_filament_deficit", AsyncMock(return_value=False)),
        patch.object(scheduler, "_propagate_owner_to_printer_manager", AsyncMock()),
        patch.object(scheduler, "_power_off_if_needed", AsyncMock()),
        patch.object(scheduler, "_preheat_and_soak", AsyncMock()),
        patch.object(scheduler, "_check_auto_drying", AsyncMock()),
        patch.object(scheduler, "_watchdog_print_start", AsyncMock()),
    ]
    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        scheduler.failed_notify = failed_notify
        yield scheduler
        tasks = [task for (task, _pid) in scheduler._inflight.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def _item(ctx, item_id: int) -> PrintQueueItem:
    async with ctx.session_maker() as db:
        return await db.get(PrintQueueItem, item_id)


HANDSHAKE = FtpFailure(FtpFailureKind.HANDSHAKE, "WRONG_VERSION_NUMBER (printer answered in cleartext: 421 ...)")


# ---------------------------------------------------------------------------
# What one failed upload does to its item
# ---------------------------------------------------------------------------
class TestOneFailedUpload:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kind",
        [FtpFailureKind.HANDSHAKE, FtpFailureKind.COOLOFF, FtpFailureKind.TIMEOUT, FtpFailureKind.NETWORK],
    )
    async def test_a_file_that_never_arrived_keeps_the_item(self, farm, kind):
        item_id = await farm.add_item(printer_id=farm.ids.refusing)
        upload = _upload_refused_by(REFUSING_IP, FtpFailure(kind, "detail"))

        async with _scheduler(farm, upload) as scheduler:
            await scheduler.check_queue()

        item = await _item(farm, item_id)
        assert item.status == "pending"
        assert item.printer_id == farm.ids.refusing
        assert item.error_message is None
        assert item.dispatch_attempts == 0, "the start-watchdog budget is for a printer that took the file"
        scheduler.failed_notify.assert_not_awaited()
        assert farm.ids.refusing in scheduler._upload_backoff

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure",
        [
            FtpFailure(FtpFailureKind.AUTH, "530 Login incorrect.", "530"),
            FtpFailure(FtpFailureKind.STORAGE, "553 Could not create file.", "553"),
            FtpFailure(FtpFailureKind.NOT_FOUND, "550 Permission denied.", "550"),
            FtpFailure(FtpFailureKind.UNKNOWN, "500 what"),
            None,
        ],
        ids=["auth", "storage", "not_found", "unknown", "unreported"],
    )
    async def test_a_failure_that_would_repeat_still_fails_the_item(self, farm, failure):
        """Retrying a wrong access code or a full card every five minutes helps no one."""
        item_id = await farm.add_item(printer_id=farm.ids.refusing)

        async def upload(*_args, **kwargs):
            if failure is not None:
                kwargs["failure"].failure = failure
            return False

        async with _scheduler(farm, upload) as scheduler:
            await scheduler.check_queue()

        item = await _item(farm, item_id)
        assert item.status == "failed"
        assert item.error_message
        scheduler.failed_notify.assert_awaited_once()
        assert farm.ids.refusing not in scheduler._upload_backoff

    @pytest.mark.asyncio
    async def test_an_upload_that_overran_its_deadline_still_fails(self, farm):
        """A link too slow to finish would be just as slow next time (#2529)."""
        item_id = await farm.add_item(printer_id=farm.ids.refusing)

        async def upload(*_args, **kwargs):
            kwargs["failure"].failure = FtpFailure(FtpFailureKind.TIMEOUT, "deadline")
            raise UploadCancelled("too slow")

        async with _scheduler(farm, upload) as scheduler:
            await scheduler.check_queue()

        assert (await _item(farm, item_id)).status == "failed"

    @pytest.mark.asyncio
    async def test_a_cancel_during_the_upload_is_not_undone(self, farm):
        """The row is never written back to pending, so a cancel that won stays won."""
        item_id = await farm.add_item(printer_id=farm.ids.refusing)

        async def upload(*_args, **kwargs):
            async with farm.session_maker() as other:
                row = await other.get(PrintQueueItem, item_id)
                row.status = "cancelled"
                await other.commit()
            kwargs["failure"].failure = HANDSHAKE
            return False

        async with _scheduler(farm, upload) as scheduler:
            await scheduler.check_queue()

        assert (await _item(farm, item_id)).status == "cancelled"


# ---------------------------------------------------------------------------
# The report: a refusing printer must not drain the queue
# ---------------------------------------------------------------------------
class TestTheQueueIsNotDrained:
    @pytest.mark.asyncio
    async def test_any_model_items_stop_going_to_the_refusing_printer(self, farm):
        """#3210's shape: "any P2S" items, one P2S refusing every upload.

        Pass 1 sends one item to each printer; the refusing one keeps its item.
        Pass 2 has the healthy printer busy printing and the refusing one in
        backoff, so the rest wait instead of being fed to it one by one.
        """
        ids = [await farm.add_item(target_model="P2S") for _ in range(5)]
        upload = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()

        async with _scheduler(farm, upload, scheduler=scheduler):
            await scheduler.check_queue()
        async with _scheduler(farm, upload, scheduler=scheduler, busy={farm.ids.healthy}):
            for _ in range(3):
                await scheduler.check_queue()

        items = [await _item(farm, i) for i in ids]
        assert [i.status for i in items].count("failed") == 0, [(i.id, i.status, i.error_message) for i in items]
        assert [i.status for i in items].count("printing") == 1
        held = [i for i in items if i.printer_id == farm.ids.refusing]
        assert len(held) == 1, "exactly one item waits on the refusing printer"
        assert held[0].status == "pending"
        waiting = [i for i in items if i.status == "pending" and i.printer_id is None]
        assert len(waiting) == 3, "the rest stay unassigned, free for any printer that comes free"

    @pytest.mark.asyncio
    async def test_the_item_kept_on_the_printer_says_why(self, farm):
        item_id = await farm.add_item(printer_id=farm.ids.refusing)
        upload = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()

        async with _scheduler(farm, upload, scheduler=scheduler):
            await scheduler.check_queue()
        async with _scheduler(farm, upload, scheduler=scheduler):
            await scheduler.check_queue()

        item = await _item(farm, item_id)
        assert item.status == "pending"
        assert item.waiting_reason == "P2S-8 is not accepting files — Printbuddy will retry automatically"

    @pytest.mark.asyncio
    async def test_the_printer_is_tried_again_once_the_backoff_ends(self, farm):
        item_id = await farm.add_item(printer_id=farm.ids.refusing)
        scheduler = PrintScheduler()

        async with _scheduler(farm, _upload_refused_by(REFUSING_IP, HANDSHAKE), scheduler=scheduler):
            await scheduler.check_queue()

        retry_at = scheduler._upload_backoff[farm.ids.refusing]
        assert retry_at - time.monotonic() == pytest.approx(UPLOAD_FAILURE_BACKOFF_SECONDS, abs=5)

        # The printer recovered and the window has passed.
        scheduler._upload_backoff[farm.ids.refusing] = time.monotonic() - 1
        async with _scheduler(farm, AsyncMock(return_value=True), scheduler=scheduler):
            await scheduler.check_queue()

        assert (await _item(farm, item_id)).status == "printing"
        assert farm.ids.refusing not in scheduler._upload_backoff


# ---------------------------------------------------------------------------
# A printer that stays broken: retries thin out, and say so once
# ---------------------------------------------------------------------------
def _expire_backoff(scheduler: PrintScheduler, printer_id: int) -> None:
    """Jump past the printer's backoff window, as if the time had passed."""
    scheduler._upload_backoff[printer_id] = time.monotonic() - 1


def _remaining(scheduler: PrintScheduler, printer_id: int) -> float:
    return scheduler._upload_backoff[printer_id] - time.monotonic()


async def _finish(ctx, scheduler: PrintScheduler, item_id: int) -> None:
    """Mark a dispatched item's print done, so its printer can take the next one."""
    async with ctx.session_maker() as db:
        row = await db.get(PrintQueueItem, item_id)
        assert row.status == "printing"
        row.status = "completed"
        await db.commit()
        scheduler._release_dispatch_hold(row.printer_id)


class TestAPrinterThatStaysBroken:
    @pytest.mark.asyncio
    async def test_each_refusal_in_a_row_doubles_the_wait_up_to_the_cap(self, farm):
        """#3210's printer refused for about 40 hours.

        At a flat five minutes that is ~480 retries, each one a preheat cycle
        where preheat is on, five connection attempts and a page of log.
        """
        await farm.add_item(printer_id=farm.ids.refusing)
        upload = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()

        waits = []
        for _ in range(6):
            async with _scheduler(farm, upload, scheduler=scheduler):
                await scheduler.check_queue()
            waits.append(_remaining(scheduler, farm.ids.refusing))
            _expire_backoff(scheduler, farm.ids.refusing)

        expected = [300, 600, 1200, 2400, 3600, 3600]
        assert expected[0] == UPLOAD_FAILURE_BACKOFF_SECONDS
        assert expected[-1] == UPLOAD_FAILURE_BACKOFF_MAX_SECONDS
        assert waits == [pytest.approx(w, abs=5) for w in expected]

    @pytest.mark.asyncio
    async def test_a_successful_upload_resets_the_wait(self, farm):
        first = await farm.add_item(printer_id=farm.ids.refusing)
        refused = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()

        for _ in range(3):
            async with _scheduler(farm, refused, scheduler=scheduler):
                await scheduler.check_queue()
            _expire_backoff(scheduler, farm.ids.refusing)
        async with _scheduler(farm, AsyncMock(return_value=True), scheduler=scheduler):
            await scheduler.check_queue()
        assert farm.ids.refusing not in scheduler._upload_refusals
        await _finish(farm, scheduler, first)

        # It breaks again later: back to the first window, not the fourth.
        await farm.add_item(printer_id=farm.ids.refusing)
        async with _scheduler(farm, refused, scheduler=scheduler, busy=set()):
            await scheduler.check_queue()
        assert _remaining(scheduler, farm.ids.refusing) == pytest.approx(UPLOAD_FAILURE_BACKOFF_SECONDS, abs=5)

    @pytest.mark.asyncio
    async def test_one_outage_sends_one_waiting_notification(self, farm):
        """Every retry clears the waiting reason and the next refusal sets it again.

        `hold_item` reads that as a new reason each time, and "Job Waiting" is
        on by default -- so without a guard a 40-hour outage notifies ~480 times.
        """
        await farm.add_item(printer_id=farm.ids.refusing)
        upload = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()
        waiting = AsyncMock()

        for _ in range(4):
            # The pass that dispatches and is refused...
            async with _scheduler(farm, upload, scheduler=scheduler, waiting_notify=waiting):
                await scheduler.check_queue()
            # ...and the pass that holds the item while the printer waits.
            async with _scheduler(farm, upload, scheduler=scheduler, waiting_notify=waiting):
                await scheduler.check_queue()
            _expire_backoff(scheduler, farm.ids.refusing)

        assert waiting.await_count == 1
        assert "not accepting files" in waiting.await_args.kwargs["waiting_reason"]

    @pytest.mark.asyncio
    async def test_a_new_outage_after_a_recovery_notifies_again(self, farm):
        first = await farm.add_item(printer_id=farm.ids.refusing)
        refused = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()
        waiting = AsyncMock()

        async def outage():
            async with _scheduler(farm, refused, scheduler=scheduler, waiting_notify=waiting):
                await scheduler.check_queue()
            async with _scheduler(farm, refused, scheduler=scheduler, waiting_notify=waiting):
                await scheduler.check_queue()
            _expire_backoff(scheduler, farm.ids.refusing)

        await outage()
        async with _scheduler(farm, AsyncMock(return_value=True), scheduler=scheduler, waiting_notify=waiting):
            await scheduler.check_queue()
        await _finish(farm, scheduler, first)
        await farm.add_item(printer_id=farm.ids.refusing)
        await outage()

        assert waiting.await_count == 2

    @pytest.mark.asyncio
    async def test_keep_warm_does_not_hold_a_bed_for_a_printer_in_backoff(self, farm):
        """There is no print coming to keep the bed warm for.

        The printer is in busy_printers and has a pending item, which is
        exactly what keep-warm looks for -- and each retry would restart its
        time cap, so the bed could stay hot for the whole outage.
        """
        await farm.add_item(printer_id=farm.ids.refusing)
        upload = _upload_refused_by(REFUSING_IP, HANDSHAKE)
        scheduler = PrintScheduler()

        async with _scheduler(farm, upload, scheduler=scheduler):
            await scheduler.check_queue()
        keep_warm = AsyncMock()
        async with _scheduler(farm, upload, scheduler=scheduler):
            with patch.object(scheduler, "_apply_keep_warm", keep_warm):
                await scheduler.check_queue()

        busy_seen = keep_warm.await_args.args[3]
        assert farm.ids.refusing not in busy_seen


# ---------------------------------------------------------------------------
# 452 is the card, not the network
# ---------------------------------------------------------------------------
class TestA452IsAStorageReply:
    def _upload_raising(self, error, tmp_path):
        local = tmp_path / "job.3mf"
        local.write_bytes(b"x" * 16)
        client = BambuFTPClient(REFUSING_IP, "12345678")
        client._ftp = MagicMock()
        client._ftp.transfercmd.side_effect = error
        assert client.upload_file(local, "/job.3mf") is False
        return client.last_failure

    def test_452_is_storage(self, tmp_path):
        """ftplib raises it as error_temp, but it says the card is full.

        Read as NETWORK it would be retried forever instead of failing with
        the advice to check the card.
        """
        import ftplib  # nosec B402 -- tests construct real ftplib error types

        failure = self._upload_raising(ftplib.error_temp("452 Insufficient storage space."), tmp_path)
        assert failure.kind is FtpFailureKind.STORAGE
        assert failure.code == "452"

    def test_other_transient_replies_are_still_network(self, tmp_path):
        import ftplib  # nosec B402 -- tests construct real ftplib error types

        failure = self._upload_raising(ftplib.error_temp("421 There are too many connections."), tmp_path)
        assert failure.kind is FtpFailureKind.NETWORK

    def test_a_socket_error_is_never_read_as_a_reply_code(self, tmp_path):
        failure = self._upload_raising(OSError("452 looks like a code but is not a reply"), tmp_path)
        assert failure.kind is FtpFailureKind.NETWORK
