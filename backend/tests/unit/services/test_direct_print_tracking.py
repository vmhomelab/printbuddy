"""Regression tests for direct printer-storage print filament tracking."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.app.models.spool import Spool
from backend.app.models.spool_assignment import SpoolAssignment
from backend.app.models.spool_usage_history import SpoolUsageHistory
from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment
from backend.app.services import direct_print_tracking


class _FakeSpoolmanClient:
    def __init__(self) -> None:
        self.used: list[tuple[int, float]] = []

    async def use_spool(self, spool_id: int, grams_used: float) -> None:
        self.used.append((spool_id, grams_used))


@pytest.mark.asyncio
async def test_completed_direct_file_print_reports_loaded_spoolman_usage(
    db_session, printer_factory, monkeypatch: pytest.MonkeyPatch
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    db_session.add(SpoolmanSlotAssignment(printer_id=printer.id, ams_id=255, tray_id=0, spoolman_spool_id=4242))
    await db_session.commit()
    fake_client = _FakeSpoolmanClient()
    monkeypatch.setattr(direct_print_tracking, "_get_spoolman_client_with_fallback", lambda: fake_client)

    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/cc1-buttpad.gcode",
        estimated_weight_grams=9.79,
    )

    results = await direct_print_tracking.report_spoolman_usage(
        printer.id,
        {"status": "completed", "filename": "/local/cc1-buttpad.gcode"},
        db_session,
    )

    assert fake_client.used == [(4242, 9.79)]
    assert results == [
        {
            "spoolman_spool_id": 4242,
            "ams_id": 255,
            "tray_id": 0,
            "weight_used": 9.79,
            "source": "direct_file_estimate",
        }
    ]


@pytest.mark.asyncio
async def test_completed_direct_file_print_debits_loaded_inventory_spool(db_session, printer_factory):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    spool = Spool(
        material="TPU",
        subtype="Basic",
        color_name="Blue",
        label_weight=1000,
        core_weight=250,
        weight_used=12.0,
        cost_per_kg=25.0,
    )
    db_session.add(spool)
    await db_session.flush()
    db_session.add(SpoolAssignment(spool_id=spool.id, printer_id=printer.id, ams_id=255, tray_id=0))
    await db_session.commit()

    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/cc1-buttpad.gcode",
        estimated_weight_grams=9.79,
        estimated_time_seconds=2608,
    )

    results = await direct_print_tracking.report_inventory_usage(
        printer.id,
        {"status": "completed", "filename": "/local/cc1-buttpad.gcode"},
        db_session,
    )

    await db_session.refresh(spool)
    history = (await db_session.execute(select(SpoolUsageHistory))).scalars().one()
    assert spool.weight_used == pytest.approx(21.79)
    assert history.spool_id == spool.id
    assert history.printer_id == printer.id
    assert history.print_name == "/local/cc1-buttpad.gcode"
    assert history.weight_used == pytest.approx(9.79)
    assert history.status == "completed"
    assert history.cost == pytest.approx(0.24475)
    assert results == [
        {
            "spool_id": spool.id,
            "ams_id": 255,
            "tray_id": 0,
            "weight_used": 9.79,
            "percent_used": 1,
            "source": "direct_file_estimate",
            "cost": pytest.approx(0.24475),
        }
    ]


@pytest.mark.asyncio
async def test_completed_direct_file_print_updates_archive_and_links_inventory_usage(
    db_session, printer_factory, archive_factory
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    archive = await archive_factory(
        printer.id,
        filename="cc1-buttpad.gcode",
        file_path="",
        filament_used_grams=None,
        print_time_seconds=None,
        status="printing",
        extra_data={"no_3mf_available": True},
    )
    spool = Spool(
        material="TPU",
        subtype="Basic",
        color_name="Blue",
        label_weight=1000,
        core_weight=250,
        weight_used=0.0,
        cost_per_kg=24.0,
    )
    db_session.add(spool)
    await db_session.flush()
    db_session.add(SpoolAssignment(spool_id=spool.id, printer_id=printer.id, ams_id=255, tray_id=0))
    await db_session.commit()

    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/cc1-buttpad.gcode",
        estimated_weight_grams=9.79,
        estimated_time_seconds=2608,
    )

    results = await direct_print_tracking.report_inventory_usage(
        printer.id,
        {"status": "completed", "filename": "/local/cc1-buttpad.gcode"},
        db_session,
        archive_id=archive.id,
    )

    await db_session.refresh(archive)
    await db_session.refresh(spool)
    history = (await db_session.execute(select(SpoolUsageHistory))).scalars().one()

    assert archive.filament_used_grams == pytest.approx(9.79)
    assert archive.print_time_seconds == 2608
    assert archive.extra_data["file_metadata"]["source"] == "elegoo_sdcp_file_info"
    assert archive.extra_data["file_metadata"]["filament_used_grams"] == pytest.approx(9.79)
    assert spool.weight_used == pytest.approx(9.79)
    assert history.archive_id == archive.id
    assert results[0]["archive_id"] == archive.id


@pytest.mark.asyncio
async def test_completed_direct_file_print_updates_archive_even_without_loaded_inventory_spool(
    db_session, printer_factory, archive_factory
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    archive = await archive_factory(
        printer.id,
        filename="cc1-no-spool.gcode",
        file_path="",
        filament_used_grams=None,
        print_time_seconds=None,
        status="printing",
        extra_data={"no_3mf_available": True},
    )

    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/cc1-no-spool.gcode",
        estimated_weight_grams=12.34,
        estimated_time_seconds=1234,
    )

    results = await direct_print_tracking.report_inventory_usage(
        printer.id,
        {"status": "completed", "filename": "/local/cc1-no-spool.gcode"},
        db_session,
        archive_id=archive.id,
    )

    await db_session.refresh(archive)

    assert results == []
    assert archive.filament_used_grams == pytest.approx(12.34)
    assert archive.print_time_seconds == 1234
    assert archive.extra_data["file_metadata"]["source"] == "elegoo_sdcp_file_info"


@pytest.mark.asyncio
async def test_direct_file_print_applies_estimated_cost_to_archive(db_session, printer_factory, archive_factory):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    archive = await archive_factory(
        printer.id,
        filename="cc1-filename-meta.gcode",
        file_path="",
        filament_used_grams=None,
        print_time_seconds=None,
        cost=None,
        status="printing",
        extra_data={"no_3mf_available": True},
    )

    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "cc1-filename-meta_fw15.5_tc0.42.gcode",
        estimated_weight_grams=15.5,
        estimated_cost=0.42,
    )
    results = await direct_print_tracking.report_inventory_usage(
        printer.id,
        {"status": "completed", "filename": "cc1-filename-meta_fw15.5_tc0.42.gcode"},
        db_session,
        archive_id=archive.id,
    )

    await db_session.refresh(archive)

    assert results == []
    assert archive.filament_used_grams == pytest.approx(15.5)
    assert archive.cost == pytest.approx(0.42)
    assert archive.extra_data["file_metadata"]["filament_cost"] == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_direct_file_spoolman_usage_updates_archive(db_session, printer_factory, archive_factory, monkeypatch):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    archive = await archive_factory(
        printer.id,
        filename="cc1-spoolman.gcode",
        file_path="",
        filament_used_grams=None,
        print_time_seconds=None,
        status="printing",
        extra_data={"no_3mf_available": True},
    )
    db_session.add(SpoolmanSlotAssignment(printer_id=printer.id, ams_id=255, tray_id=0, spoolman_spool_id=4242))
    await db_session.commit()
    fake_client = _FakeSpoolmanClient()
    monkeypatch.setattr(direct_print_tracking, "_get_spoolman_client_with_fallback", lambda: fake_client)

    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/cc1-spoolman.gcode",
        estimated_weight_grams=22.5,
        estimated_time_seconds=3600,
    )

    results = await direct_print_tracking.report_spoolman_usage(
        printer.id,
        {"status": "completed", "filename": "/local/cc1-spoolman.gcode"},
        db_session,
        archive_id=archive.id,
    )

    await db_session.refresh(archive)

    assert fake_client.used == [(4242, 22.5)]
    assert archive.filament_used_grams == pytest.approx(22.5)
    assert archive.print_time_seconds == 3600
    assert results[0]["archive_id"] == archive.id


@pytest.mark.asyncio
async def test_direct_file_print_does_not_debit_when_no_estimated_weight(db_session, printer_factory):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/no-weight.gcode",
        estimated_weight_grams=0,
    )

    results = await direct_print_tracking.report_inventory_usage(
        printer.id,
        {"status": "completed", "filename": "/local/no-weight.gcode"},
        db_session,
    )

    assert results == []


@pytest.mark.asyncio
async def test_failed_direct_file_print_clears_metadata_without_debit(db_session, printer_factory):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    direct_print_tracking.register_direct_print_metadata(
        printer.id,
        "/local/failed.gcode",
        estimated_weight_grams=9.79,
    )

    results = await direct_print_tracking.report_inventory_usage(
        printer.id,
        {"status": "failed", "filename": "/local/failed.gcode"},
        db_session,
    )

    assert results == []
    assert direct_print_tracking.pop_direct_print_metadata(printer.id, "/local/failed.gcode") is None
