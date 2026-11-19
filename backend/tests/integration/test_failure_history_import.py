"""Tests for taking Printbuddy's failure history over into "Report failed print"."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from backend.app.models.custom_failure_report import CustomFailureReason, CustomFailureReport
from backend.app.models.print_log import PrintLogEntry
from backend.app.services import failure_reason_mapping as mapping
from backend.app.services.failure_history_import import run_failure_history_sync, sync_failure_history
from backend.app.services.hms_errors import HMS_ERROR_DESCRIPTIONS

API = "/api/v1/custom-failure-reports"


@pytest.fixture(autouse=True)
async def _seed_default_reasons(db_session):
    """The app seeds the default reasons at startup (init_db), which the test client skips."""
    from backend.app.services.custom_failure_reasons import ensure_default_reasons

    await ensure_default_reasons(db_session)


START = datetime(2026, 10, 5, 8, 0)


class _SyncingClient:
    """Runs the history sync before every GET, as startup / a finished print / an archive edit would."""

    def __init__(self, client, db):
        self._client = client
        self._db = db

    async def get(self, *args, **kwargs):
        await sync_failure_history(self._db)
        return await self._client.get(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)


@pytest.fixture
def async_client(async_client, db_session):
    return _SyncingClient(async_client, db_session)


def _printer_status(state: str = "IDLE", hms: list[tuple[int, str]] | None = None):
    errors = [SimpleNamespace(attr=module << 16, code=code) for module, code in (hms or [])]
    return patch(
        "backend.app.api.routes.custom_failure_reports.printer_manager.get_status",
        return_value=SimpleNamespace(state=state, hms_errors=errors),
    )


async def _failed(archive_factory, printer_id: int, hours: int, **kwargs):
    defaults = {
        "status": "failed",
        "started_at": START + timedelta(hours=hours),
        "completed_at": START + timedelta(hours=hours, minutes=30),
    }
    defaults.update(kwargs)
    return await archive_factory(printer_id, **defaults)


async def _stats(client, **params) -> dict:
    response = await client.get(f"{API}/stats", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _counts(stats: dict) -> dict:
    return {r["reason"]: r["count"] for r in stats["reasons"] if r["count"]}


class TestMapping:
    def test_manual_labels_in_every_language(self):
        assert mapping.reason_for_text("Verstopfte Düse") == mapping.R01_CLOGGED_NOZZLE
        assert mapping.reason_for_text("Défaut d'adhésion") == mapping.R02_WARPING
        assert mapping.reason_for_text("拉丝") == mapping.R10_POOR_QUALITY  # zh-CN "stringing"
        assert mapping.reason_for_text("拉丝 / 脱落") == mapping.R12_SPAGHETTI  # zh-CN "spaghetti / detached"
        assert mapping.reason_for_text("  stromausfall ") == mapping.R07_EXTERNAL
        assert mapping.reason_for_text("Sonstiges") == mapping.R11_OTHER

    def test_cancel_and_stale_are_not_failure_causes(self):
        assert mapping.reason_for_text("User cancelled") == mapping.SKIP
        assert mapping.reason_for_text("Vom Benutzer abgebrochen") == mapping.SKIP
        assert mapping.reason_for_text("Stale - print likely cancelled or failed without status update") == mapping.SKIP

    def test_unknown_or_empty_text(self):
        assert mapping.reason_for_text("Katze auf dem Drucker") is None
        assert mapping.reason_for_text(None) is None
        assert mapping.reason_for_text("  ") is None

    def test_every_known_hms_code_has_a_decision(self):
        undecided = [code for code in HMS_ERROR_DESCRIPTIONS if mapping.reason_for_hms(code) is None]
        assert undecided == []

    def test_hms_unit_variants_share_a_rule(self):
        assert mapping.reason_for_hms("0703_8011") == mapping.R05_RUN_OUT  # AMS D runs out
        assert mapping.reason_for_hms("1805_800A") == mapping.R13_FEEDING  # AMS-HT F PTFE tube
        assert mapping.reason_for_hms("07FF_8010") == mapping.R08_TANGLED  # external spool stuck
        assert mapping.reason_for_hms("0300_8001") == mapping.SKIP  # paused by the user
        assert mapping.reason_for_hms("nonsense") is None

    def test_severe_code_wins_over_info(self):
        reason, code = mapping.reason_for_hms_list(["0C00_C004", "0300_4006"])
        assert (reason, code) == (mapping.R01_CLOGGED_NOZZLE, "0300_4006")
        assert mapping.reason_for_hms_list(["0300_8001"]) == (None, None)

    def test_codes_in_queue_error_message(self):
        text = "[0300_4006] The nozzle is clogged.; [0700_8010]"
        assert mapping.hms_codes_in_text(text) == ["0300_4006", "0700_8010"]


class TestHistoryImport:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_imports_failed_runs_and_never_touches_printbuddy_data(
        self, async_client, printer_factory, archive_factory, db_session
    ):
        printer = await printer_factory(name="P1S Links")
        await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")  # automatic text
        await _failed(archive_factory, printer.id, 2, failure_reason="Fadenziehen")  # picked in Edit Archive
        await _failed(archive_factory, printer.id, 3, status="aborted", failure_reason="User cancelled")
        await _failed(archive_factory, printer.id, 4)  # failed, no reason
        await _failed(archive_factory, printer.id, 5, failure_reason="Mein eigener Text")
        await _failed(archive_factory, printer.id, 6, status="completed")
        await _failed(archive_factory, printer.id, 7, status="cancelled", failure_reason="User cancelled")
        before = [
            (e.id, e.status, e.failure_reason) for e in (await db_session.execute(select(PrintLogEntry))).scalars()
        ]

        stats = await _stats(async_client)
        assert stats["total"] == 4
        assert stats["automatic_total"] == 2
        assert _counts(stats) == {"fail_reason_01": 1, "fail_reason_10": 1, "unassigned": 2}

        reports = {r["original_reason"]: r for r in (await async_client.get(f"{API}/")).json()}
        assert reports["Clogged nozzle"]["source"] == "auto"
        assert reports["Fadenziehen"]["source"] == "imported"
        assert reports["Mein eigener Text"]["custom_failure_reason"] == "unassigned"
        assert reports[None]["source"] == "auto"
        assert reports["Clogged nozzle"]["print_name"] == "Test Print"  # snapshot from log + archive
        assert reports["Clogged nozzle"]["print_time_seconds"] == 3600

        # Running again creates nothing new; Printbuddy's log is unchanged.
        assert (await _stats(async_client))["total"] == 4
        db_session.expire_all()
        after = [
            (e.id, e.status, e.failure_reason) for e in (await db_session.execute(select(PrintLogEntry))).scalars()
        ]
        assert after == before

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_person_report_wins_and_remembers_printbuddy_text(
        self, async_client, printer_factory, archive_factory
    ):
        printer = await printer_factory(name="X1C")
        archive = await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")
        response = await async_client.post(
            f"{API}/",
            json={"printer_id": printer.id, "archive_id": archive.id, "custom_failure_reason": "fail_reason_03"},
        )
        assert response.status_code == 200

        stats = await _stats(async_client)
        assert _counts(stats) == {"fail_reason_03": 1}
        report = (await async_client.get(f"{API}/")).json()[0]
        assert report["source"] == "manual"
        assert report["original_reason"] == "Clogged nozzle"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_follows_later_edit_archive_changes(self, async_client, printer_factory, archive_factory, db_session):
        printer = await printer_factory(name="A1")
        await _failed(archive_factory, printer.id, 1)
        assert _counts(await _stats(async_client)) == {"unassigned": 1}

        entry = (await db_session.execute(select(PrintLogEntry))).scalar_one()
        entry.failure_reason = "Verformung"
        await db_session.commit()
        assert _counts(await _stats(async_client)) == {"fail_reason_02": 1}
        assert (await async_client.get(f"{API}/")).json()[0]["source"] == "imported"

        entry.failure_reason = "Vom Benutzer abgebrochen"
        await db_session.commit()
        assert (await _stats(async_client))["total"] == 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_corrected_report_is_not_overwritten(
        self, async_client, printer_factory, archive_factory, db_session
    ):
        printer = await printer_factory(name="A1 mini")
        await _failed(archive_factory, printer.id, 1, failure_reason="Layer shift")
        report = (await async_client.get(f"{API}/")).json()[0]
        response = await async_client.patch(f"{API}/{report['id']}", json={"custom_failure_reason": "fail_reason_07"})
        assert response.json()["source"] == "manual"

        entry = (await db_session.execute(select(PrintLogEntry))).scalar_one()
        entry.failure_reason = "Clogged nozzle"
        await db_session.commit()
        report = (await async_client.get(f"{API}/")).json()[0]
        assert report["custom_failure_reason"] == "fail_reason_07"
        assert report["original_reason"] == "Clogged nozzle"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_withdrawn_import_stays_away_until_reported_again(
        self, async_client, printer_factory, archive_factory
    ):
        printer = await printer_factory(name="P1P")
        archive = await _failed(archive_factory, printer.id, 1, failure_reason="Filament runout")
        report = (await async_client.get(f"{API}/")).json()[0]
        assert (await async_client.delete(f"{API}/{report['id']}")).status_code == 200
        assert (await _stats(async_client))["total"] == 0
        assert (await _stats(async_client))["total"] == 0  # the sync doesn't bring it back

        with _printer_status():
            target = (await async_client.get(f"{API}/printers/{printer.id}/target")).json()
        assert target["existing_report"] is None
        response = await async_client.post(
            f"{API}/",
            json={"printer_id": printer.id, "archive_id": archive.id, "custom_failure_reason": "fail_reason_05"},
        )
        assert response.json()["id"] == report["id"]  # the marker is reused, no duplicate
        assert _counts(await _stats(async_client)) == {"fail_reason_05": 1}

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_source_filter(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="Filter")
        await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")
        await _failed(archive_factory, printer.id, 2, failure_reason="Warping")
        manual = await archive_factory(printer.id, started_at=START + timedelta(hours=3))
        await async_client.post(
            f"{API}/",
            json={"printer_id": printer.id, "archive_id": manual.id, "custom_failure_reason": "fail_reason_09"},
        )

        assert _counts(await _stats(async_client, source="automatic")) == {"fail_reason_01": 1}
        assert _counts(await _stats(async_client, source="person")) == {"fail_reason_02": 1, "fail_reason_09": 1}
        listed = (await async_client.get(f"{API}/", params={"source": "automatic"})).json()
        assert [r["original_reason"] for r in listed] == ["Clogged nozzle"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_hms_code_from_queue_item(self, async_client, printer_factory, archive_factory, db_session):
        from backend.app.models.print_queue import PrintQueueItem

        printer = await printer_factory(name="H2D")
        archive = await _failed(archive_factory, printer.id, 1)
        db_session.add(
            PrintQueueItem(
                printer_id=printer.id,
                archive_id=archive.id,
                status="failed",
                completed_at=archive.completed_at,
                error_message="[0700_8010] The AMS assist motor is overloaded.",
            )
        )
        await db_session.commit()

        report = (await async_client.get(f"{API}/")).json()[0]
        assert report["custom_failure_reason"] == "fail_reason_08"
        assert report["hms_code"] == "0700_8010"
        assert "assist motor" in report["hms_description"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_stale_log_link_is_not_reused(self, async_client, printer_factory, archive_factory, db_session):
        printer = await printer_factory(name="Reuse")
        archive = await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")
        entry = (await db_session.execute(select(PrintLogEntry))).scalar_one()
        # An old report still points at this id, but belongs to a different run (log was cleared).
        db_session.add(
            CustomFailureReport(
                custom_failure_reason="fail_reason_04",
                source="manual",
                print_log_entry_id=entry.id,
                print_started_at=archive.started_at - timedelta(days=30),
            )
        )
        await db_session.commit()

        assert _counts(await _stats(async_client)) == {"fail_reason_01": 1, "fail_reason_04": 1}


class TestSuggestion:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pop_up_suggests_reason_from_live_hms_error(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="P1S Rechts")
        await archive_factory(printer.id, status="printing", started_at=START)

        with _printer_status("PAUSE", hms=[(0x0300, "0x8001"), (0x0300, "0x4006")]):
            target = (await async_client.get(f"{API}/printers/{printer.id}/target")).json()
        assert target["suggestion"]["reason"] == "fail_reason_01"
        assert target["suggestion"]["hms_code"] == "0300_4006"

        with _printer_status("PAUSE", hms=[(0x0300, "0x8001")]):  # only "paused by user"
            target = (await async_client.get(f"{API}/printers/{printer.id}/target")).json()
        assert target["suggestion"] is None


class TestNewDefaults:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_upgrade_puts_new_defaults_before_other(self, async_client, db_session):
        # Simulate an installation from before: 11 defaults, a custom reason after "Other".
        await async_client.get(f"{API}/reasons/")
        for code in ("fail_reason_12", "fail_reason_13", "fail_reason_14"):
            reason = (
                await db_session.execute(select(CustomFailureReason).where(CustomFailureReason.code == code))
            ).scalar_one()
            await db_session.delete(reason)
        await db_session.commit()
        reasons = (await db_session.execute(select(CustomFailureReason))).scalars().all()
        for index, reason in enumerate(sorted(reasons, key=lambda r: r.code), start=1):
            reason.sort_order = index
        db_session.add(CustomFailureReason(code="custom_abc", title="Eigener", is_system=False, sort_order=12))
        await db_session.commit()

        # Restart: init_db seeds the missing defaults.
        from backend.app.services.custom_failure_reasons import ensure_default_reasons

        await ensure_default_reasons(db_session)
        codes = [r["code"] for r in (await async_client.get(f"{API}/reasons/")).json()]
        assert codes[-5:] == ["fail_reason_12", "fail_reason_13", "fail_reason_14", "fail_reason_11", "custom_abc"]


class TestStoppedAtProgress:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_progress_recorded_at_print_end_reaches_imported_report(
        self, async_client, printer_factory, archive_factory, db_session
    ):
        from backend.app.services.failure_progress import record_run_progress

        printer = await printer_factory(name="P1S Links")
        archive = await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")
        old = await _failed(archive_factory, printer.id, 2)  # ended before this feature existed
        with patch("backend.app.services.printer_manager.printer_manager.get_status", return_value=None):
            # Bambu sends the last valid progress before the firmware resets it.
            await record_run_progress(db_session, printer.id, archive.id, {"status": "failed", "last_progress": 37})
            # Completed prints are not recorded.
            await record_run_progress(db_session, printer.id, old.id, {"status": "completed", "progress": 100})

        reports = {r["archive_id"]: r for r in (await async_client.get(f"{API}/")).json()}
        assert reports[archive.id]["progress_percent"] == 37.0
        assert reports[old.id]["progress_percent"] is None  # unknown -> shown as "–"

    def test_klipper_progress_and_live_fallback(self):
        from backend.app.services.failure_progress import progress_from_completion

        assert progress_from_completion({"progress": 62.46})[0] == 62.5
        live = SimpleNamespace(progress=12, layer_num=30, total_layers=200)
        assert progress_from_completion({"last_progress": 0}, live) == (12.0, 30, 200)
        assert progress_from_completion({"progress": "nonsense"})[0] is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_manual_report_progress(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="X1C")
        finished = await archive_factory(printer.id, status="completed", started_at=START)
        response = await async_client.post(
            f"{API}/",
            json={"printer_id": printer.id, "archive_id": finished.id, "custom_failure_reason": "fail_reason_10"},
        )
        assert response.json()["progress_percent"] == 100.0  # ran to the end, but looks bad

        running = await archive_factory(printer.id, status="printing", started_at=START + timedelta(hours=5))
        with patch(
            "backend.app.api.routes.custom_failure_reports.printer_manager.get_status",
            return_value=SimpleNamespace(state="RUNNING", progress=48, hms_errors=[]),
        ):
            response = await async_client.post(
                f"{API}/",
                json={"printer_id": printer.id, "archive_id": running.id, "custom_failure_reason": "fail_reason_12"},
            )
        assert response.json()["progress_percent"] == 48.0


class TestPrinterFilter:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_statistics_and_list_for_one_printer(self, async_client, printer_factory, archive_factory):
        left = await printer_factory(name="P1S Links")
        right = await printer_factory(name="P1S Rechts")
        await _failed(archive_factory, left.id, 1, failure_reason="Clogged nozzle")
        await _failed(archive_factory, left.id, 2, failure_reason="Warping")
        await _failed(archive_factory, right.id, 3, failure_reason="Clogged nozzle")

        assert _counts(await _stats(async_client)) == {"fail_reason_01": 2, "fail_reason_02": 1}
        stats = await _stats(async_client, printer_id=left.id)
        assert _counts(stats) == {"fail_reason_01": 1, "fail_reason_02": 1}
        assert stats["automatic_total"] == 1  # follows the printer filter too
        listed = (await async_client.get(f"{API}/", params={"printer_id": right.id})).json()
        assert [r["printer_name"] for r in listed] == ["P1S Rechts"]


class TestSyncTriggers:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_reads_do_not_import(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="Read only")
        await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")
        # Bypass the syncing wrapper: a plain read must not write anything.
        response = await async_client._client.get(f"{API}/stats")
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_editing_the_archive_reason_schedules_a_sync(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="Edit")
        archive = await _failed(archive_factory, printer.id, 1)
        with patch("backend.app.services.failure_history_import.schedule_failure_history_sync") as schedule:
            response = await async_client.patch(f"/api/v1/archives/{archive.id}", json={"failure_reason": "Warping"})
        assert response.status_code == 200, response.text
        schedule.assert_called_once_with("archive edited")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_background_sync_never_raises(self):
        with patch(
            "backend.app.services.failure_history_import.sync_failure_history", side_effect=RuntimeError("boom")
        ):
            await run_failure_history_sync("test")  # logged, not raised

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_one_report_per_log_entry_is_enforced_by_the_database(
        self, async_client, printer_factory, archive_factory, db_session
    ):
        from sqlalchemy.exc import IntegrityError

        printer = await printer_factory(name="Unique")
        await _failed(archive_factory, printer.id, 1, failure_reason="Clogged nozzle")
        await sync_failure_history(db_session)
        entry = (await db_session.execute(select(PrintLogEntry))).scalar_one()
        db_session.add(CustomFailureReport(custom_failure_reason="fail_reason_01", print_log_entry_id=entry.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()
