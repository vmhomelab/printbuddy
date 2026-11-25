"""Archiving a multi-plate 3MF records totals over all plates (not just plate 1)."""

import zipfile

import pytest
from httpx import AsyncClient

from backend.app.core.config import settings
from backend.app.models.filament import Filament
from backend.app.services.archive import ArchiveService

SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="3600"/>
    <metadata key="weight" value="60"/>
    <object identify_id="11" name="A" skipped="false"/>
    <object identify_id="12" name="B" skipped="false"/>
    <filament id="1" type="PLA" color="#FFFFFF" used_g="60"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="1200"/>
    <metadata key="weight" value="40"/>
    <object identify_id="21" name="C" skipped="false"/>
    <filament id="2" type="PETG" color="#000000" used_g="40"/>
  </plate>
</config>
"""


@pytest.fixture
def archive_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "archive_dir", tmp_path / "archive")
    source = tmp_path / "upload" / "model.3mf"
    source.parent.mkdir()
    with zipfile.ZipFile(source, "w") as zf:
        zf.writestr("Metadata/slice_info.config", SLICE_INFO)
        zf.writestr("Metadata/plate_1.gcode", "; total layer number: 10\n")
        zf.writestr("Metadata/plate_2.gcode", "; total layer number: 20\n")
    return source


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_archive_sums_all_plates(db_session, archive_dirs, async_client: AsyncClient):
    db_session.add_all(
        [Filament(name="PLA", type="PLA", cost_per_kg=20.0), Filament(name="PETG", type="PETG", cost_per_kg=30.0)]
    )
    await db_session.commit()

    archive = await ArchiveService(db_session).archive_print(printer_id=None, source_file=archive_dirs)

    assert archive is not None
    assert archive.print_time_seconds == 4800
    assert archive.filament_used_grams == 100
    assert archive.quantity == 3
    # 60 g PLA @ 20/kg + 40 g PETG @ 30/kg
    assert archive.cost == 2.4
    assert archive.extra_data["plate_count"] == 2

    # Plates endpoint (shared slice_info parser) still reports per-plate values
    response = await async_client.get(f"/api/v1/archives/{archive.id}/plates")
    assert response.status_code == 200
    plates = response.json()["plates"]
    assert [(p["index"], p["print_time_seconds"], p["filament_used_grams"]) for p in plates] == [
        (1, 3600, 60.0),
        (2, 1200, 40.0),
    ]
    assert plates[1]["filaments"][0]["type"] == "PETG"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_printed_plate_uses_only_that_plate(db_session, archive_dirs, async_client: AsyncClient):
    archive = await ArchiveService(db_session).archive_print(
        printer_id=None,
        source_file=archive_dirs,
        print_data={"filename": "/data/Metadata/plate_2.gcode", "status": "printing"},
    )

    assert archive is not None
    assert archive.print_time_seconds == 1200
    assert archive.filament_used_grams == 40
    assert archive.quantity == 1
    assert archive.total_layers == 20

    # Rescan keeps restricting to the printed plate
    response = await async_client.post(f"/api/v1/archives/{archive.id}/rescan")
    assert response.status_code == 200
    assert response.json()["print_time_seconds"] == 1200
