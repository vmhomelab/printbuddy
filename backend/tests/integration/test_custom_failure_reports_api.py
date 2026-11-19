"""Integration tests for user-reported failure reasons ("Report failed print")."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient

API = "/api/v1/custom-failure-reports"


@pytest.fixture(autouse=True)
async def _seed_default_reasons(db_session):
    """The app seeds the default reasons at startup (init_db), which the test client skips."""
    from backend.app.services.custom_failure_reasons import ensure_default_reasons

    await ensure_default_reasons(db_session)


def _printer_state(state: str | None):
    """Patch the live printer state the target lookup sees (RUNNING, IDLE, ...)."""
    status = SimpleNamespace(state=state) if state else None
    return patch(
        "backend.app.api.routes.custom_failure_reports.printer_manager.get_status",
        return_value=status,
    )


async def _report(client: AsyncClient, printer_id: int, archive_id: int, reason: str, **extra):
    response = await client.post(
        f"{API}/",
        json={"printer_id": printer_id, "archive_id": archive_id, "custom_failure_reason": reason, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestReportTarget:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_default_reasons_exist_with_other_last(self, async_client: AsyncClient):
        response = await async_client.get(f"{API}/reasons/")
        assert response.status_code == 200
        codes = [r["code"] for r in response.json()]
        assert codes == [f"fail_reason_{i:02d}" for i in (*range(1, 11), 12, 13, 14, 11)]
        assert all(r["is_system"] and r["title"] is None for r in response.json())
        assert response.json()[0]["icon"] == "Ban"  # default icon comes from code until one is picked

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_idle_printer_targets_most_recent_print(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="P1S Links")
        now = datetime(2026, 11, 3, 12, 0)
        await archive_factory(printer.id, print_name="Old", started_at=now - timedelta(days=2))
        newest = await archive_factory(printer.id, print_name="Newest", status="failed", started_at=now)

        with _printer_state("IDLE"):
            response = await async_client.get(f"{API}/printers/{printer.id}/target")
        assert response.status_code == 200
        target = response.json()
        assert target["archive_id"] == newest.id
        assert target["is_current_print"] is False
        assert target["existing_report"] is None  # reads never import the history

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_running_printer_targets_current_print(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="P1S Rechts")
        now = datetime(2026, 11, 3, 12, 0)
        current = await archive_factory(printer.id, print_name="Running", status="printing", started_at=now)
        await archive_factory(printer.id, print_name="Finished later?", started_at=now + timedelta(minutes=1))

        with _printer_state("RUNNING"):
            target = (await async_client.get(f"{API}/printers/{printer.id}/target")).json()
        assert target["archive_id"] == current.id
        assert target["is_current_print"] is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_print_yet_returns_404(self, async_client, printer_factory):
        printer = await printer_factory(name="Brand new")
        with _printer_state(None):
            response = await async_client.get(f"{API}/printers/{printer.id}/target")
        assert response.status_code == 404


class TestCreateReport:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_report_snapshots_print_and_keeps_failure_reason_untouched(
        self, async_client, printer_factory, archive_factory, db_session
    ):
        printer = await printer_factory(name="X2D")
        archive = await archive_factory(
            printer.id,
            print_name="schniepatz11",
            filename="schniepatz11_0.2mm_PLA_30m24s.gcode",
            status="failed",
            failure_reason="Layer shift",
            started_at=datetime(2026, 11, 2, 13, 41),
            filament_type="PLA, PETG",
            filament_used_grams=6.5,
            print_time_seconds=1824,
            extra_data={
                "filament_slots": [
                    {"slot_id": 3, "used_g": 4.28, "type": "PLA", "color": "#FFFFFF"},
                    {"slot_id": 2, "used_g": 2.22, "type": "PETG", "color": "#898989"},
                ]
            },
        )

        report = await _report(
            async_client,
            printer.id,
            archive.id,
            "fail_reason_08",
            comment="  Spaghetti after layer 40 ",
            reported_by="   ",
        )
        assert report["custom_failure_reason"] == "fail_reason_08"
        assert report["printer_name"] == "X2D"
        assert report["print_name"] == "schniepatz11"
        assert report["print_time_seconds"] == 1824
        assert report["comment"] == "Spaghetti after layer 40"
        assert report["reported_by"] is None  # empty name stays anonymous
        assert [m["type"] for m in report["materials"]] == ["PLA", "PETG"]
        assert report["materials"][0]["grams"] == 4.28

        await db_session.refresh(archive)
        assert archive.failure_reason == "Layer shift"  # automatic field is not touched

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_reporting_same_run_again_updates_instead_of_duplicating(
        self, async_client, printer_factory, archive_factory
    ):
        printer = await printer_factory(name="A1")
        archive = await archive_factory(printer.id, started_at=datetime(2026, 11, 1, 8, 0))

        first = await _report(async_client, printer.id, archive.id, "fail_reason_01")
        second = await _report(async_client, printer.id, archive.id, "fail_reason_02", reported_by="Alex")
        assert second["id"] == first["id"]
        assert second["custom_failure_reason"] == "fail_reason_02"
        assert second["reported_by"] == "Alex"

        with _printer_state("IDLE"):
            target = (await async_client.get(f"{API}/printers/{printer.id}/target")).json()
        assert target["existing_report"]["id"] == first["id"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_reprint_of_same_file_is_a_separate_report(
        self, async_client, printer_factory, archive_factory, db_session
    ):
        printer = await printer_factory(name="Voron")
        archive = await archive_factory(printer.id, started_at=datetime(2026, 11, 1, 8, 0))
        first = await _report(async_client, printer.id, archive.id, "fail_reason_03")

        # A reprint reuses the archive row with a new start time.
        archive.started_at = datetime(2026, 11, 2, 9, 0)
        await db_session.commit()
        second = await _report(async_client, printer.id, archive.id, "fail_reason_03")
        assert second["id"] != first["id"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rejects_unknown_reason_and_foreign_print(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="One")
        other = await printer_factory(name="Two")
        archive = await archive_factory(other.id)

        response = await async_client.post(
            f"{API}/",
            json={"printer_id": other.id, "archive_id": archive.id, "custom_failure_reason": "fail_reason_99"},
        )
        assert response.status_code == 400

        response = await async_client.post(
            f"{API}/",
            json={"printer_id": printer.id, "archive_id": archive.id, "custom_failure_reason": "fail_reason_01"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_and_withdraw(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="MK4")
        archive = await archive_factory(printer.id)
        report = await _report(async_client, printer.id, archive.id, "fail_reason_04", comment="first guess")

        response = await async_client.patch(
            f"{API}/{report['id']}", json={"custom_failure_reason": "fail_reason_05", "comment": ""}
        )
        assert response.status_code == 200
        assert response.json()["custom_failure_reason"] == "fail_reason_05"
        assert response.json()["comment"] is None

        assert (await async_client.delete(f"{API}/{report['id']}")).status_code == 200
        assert (await async_client.get(f"{API}/")).json() == []


class TestStatistics:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_counts_percentages_and_latest_limit(self, async_client, printer_factory, archive_factory):
        printer_a = await printer_factory(name="A")
        printer_b = await printer_factory(name="B")
        start = datetime(2026, 10, 1, 8, 0)
        # 17 reports for reason 08 across two printers, 3 for reason 02.
        for i in range(17):
            printer = printer_a if i % 2 else printer_b
            archive = await archive_factory(printer.id, print_name=f"Part {i}", started_at=start + timedelta(hours=i))
            await _report(async_client, printer.id, archive.id, "fail_reason_08")
        for i in range(3):
            archive = await archive_factory(printer_a.id, started_at=start + timedelta(days=1, hours=i))
            await _report(async_client, printer_a.id, archive.id, "fail_reason_02")

        stats = (await async_client.get(f"{API}/stats")).json()
        assert stats["total"] == 20
        assert stats["latest_limit"] == 15
        top, second = stats["reasons"][0], stats["reasons"][1]
        assert (top["reason"], top["count"], top["percent"]) == ("fail_reason_08", 17, 85.0)
        assert (second["reason"], second["count"], second["percent"]) == ("fail_reason_02", 3, 15.0)
        assert len(stats["reasons"]) == 14  # every configured reason is listed, also with 0
        assert len(top["latest"]) == 15
        assert top["latest"][0]["print_name"] == "Part 16"  # newest first

        everything = (await async_client.get(f"{API}/", params={"reason": "fail_reason_08"})).json()
        assert len(everything) == 17
        assert everything[-1]["print_name"] == "Part 0"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_date_filter_uses_print_date(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="Filter")
        inside = await archive_factory(printer.id, started_at=datetime(2026, 10, 15, 10, 0))
        outside = await archive_factory(printer.id, started_at=datetime(2026, 9, 1, 10, 0))
        await _report(async_client, printer.id, inside.id, "fail_reason_01")
        await _report(async_client, printer.id, outside.id, "fail_reason_01")

        stats = (
            await async_client.get(f"{API}/stats", params={"date_from": "2026-10-01", "date_to": "2026-10-31"})
        ).json()
        assert stats["total"] == 1


class TestSchema:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_startup_seed_runs_once(self, test_engine, db_session):
        """init_db seeds the defaults; running it again (restart, second worker) adds nothing."""
        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from backend.app.core.database import seed_custom_failure_reasons
        from backend.app.models.custom_failure_report import CustomFailureReason

        sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        with patch("backend.app.core.database.async_session", sessions):
            await seed_custom_failure_reasons()
            await seed_custom_failure_reasons()
        count = (await db_session.execute(select(func.count()).select_from(CustomFailureReason))).scalar()
        assert count == 14

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_new_report_defaults_to_manual_source(
        self, async_client, db_session, printer_factory, archive_factory
    ):
        """Columns for the later parts exist from the start; a person's report is "manual"."""
        from backend.app.models.custom_failure_report import CustomFailureReport

        printer = await printer_factory(name="Schema")
        archive = await archive_factory(printer.id, started_at=datetime(2026, 10, 15, 10, 0))
        created = await _report(async_client, printer.id, archive.id, "fail_reason_01")
        row = await db_session.get(CustomFailureReport, created["id"])
        assert row.source == "manual"
        assert row.print_log_entry_id is None
        assert row.progress_percent == 100.0  # reported after the print completed
