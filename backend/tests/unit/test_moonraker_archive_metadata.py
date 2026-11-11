"""Klipper/Moonraker archive support: slicer metadata, thumbnails, fileless
archive side files (finish photos) and skipping Bambu-only timelapse FTP."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services.printer_providers.moonraker import (
    MoonrakerPrinterClient,
    normalize_moonraker_file_metadata,
)

MOONRAKER_METADATA = {
    "filename": "parts/benchy.gcode",
    "size": 2_345_678,
    "slicer": "OrcaSlicer",
    "slicer_version": "2.3.0",
    "layer_height": 0.2,
    "first_layer_height": 0.25,
    "object_height": 48.0,
    "nozzle_diameter": 0.4,
    "estimated_time": 3725.4,
    "filament_total": 4520.7,
    "filament_weight_total": 13.48,
    "filament_type": "PLA",
    "filament_name": "Generic PLA",
    "filament_colors": ["#FF6600"],
    "first_layer_extr_temp": 215,
    "first_layer_bed_temp": 60,
    "thumbnails": [
        {"width": 32, "height": 32, "size": 900, "relative_path": ".thumbs/benchy-32x32.png"},
        {"width": 300, "height": 300, "size": 20_000, "relative_path": ".thumbs/benchy-300x300.png"},
    ],
}


def test_normalize_moonraker_file_metadata_maps_slicer_fields():
    metadata = normalize_moonraker_file_metadata(MOONRAKER_METADATA, "parts/benchy.gcode")

    assert metadata["source"] == "moonraker_file_metadata"
    assert metadata["filament_used_grams"] == pytest.approx(13.48)
    assert metadata["filament_total_mm"] == pytest.approx(4520.7)
    assert metadata["print_time_seconds"] == 3725
    assert metadata["filament_type"] == "PLA"
    assert metadata["filament_colors"] == ["#FF6600"]
    assert metadata["layer_height"] == pytest.approx(0.2)
    assert metadata["nozzle_temperature"] == 215
    assert metadata["bed_temperature"] == 60
    assert metadata["slicer"] == "OrcaSlicer"
    # Largest thumbnail, resolved relative to the G-code's directory.
    assert metadata["thumbnail_path"] == "parts/.thumbs/benchy-300x300.png"


def test_normalize_moonraker_file_metadata_handles_multi_material():
    metadata = normalize_moonraker_file_metadata(
        {
            "filament_type": "PLA;PETG",
            "filament_weights": [10.0, 2.5],
            "filament_colors": ["FF0000", "00FF00"],
            "thumbnails": [{"width": 64, "height": 64, "relative_path": ".thumbs/a.png"}],
        },
        "a.gcode",
    )

    assert metadata["filament_type"] == "PLA"
    assert metadata["filament_types"] == ["PLA", "PETG"]
    assert metadata["filament_colors"] == ["#FF0000", "#00FF00"]
    assert metadata["filament_slots"] == [
        {"slot_id": 1, "used_g": 10.0, "type": "PLA", "color": "#FF0000"},
        {"slot_id": 2, "used_g": 2.5, "type": "PETG", "color": "#00FF00"},
    ]
    assert metadata["thumbnail_path"] == ".thumbs/a.png"


def test_moonraker_lifecycle_payload_carries_file_metadata_and_actual_usage(monkeypatch):
    client = MoonrakerPrinterClient("http://voron.local:7125")
    requested: list[str] = []

    def fake_get(path, *, base_url=None):  # noqa: ARG001
        requested.append(path)
        return MOONRAKER_METADATA

    monkeypatch.setattr(client, "_get", fake_get)
    client.state.gcode_file = "parts/benchy.gcode"
    client.state.subtask_name = "parts/benchy.gcode"
    client.state.raw_data = {"print_stats": {"filament_used": 2260.35}}

    payload = client._build_lifecycle_payload()
    client._build_lifecycle_payload()  # cached: no second metadata request

    assert payload["file_metadata"]["filament_used_grams"] == pytest.approx(13.48)
    assert payload["actual_filament_used_mm"] == pytest.approx(2260.35)
    assert requested == ["server/files/metadata?filename=parts%2Fbenchy.gcode"]


def test_moonraker_lifecycle_payload_survives_metadata_failure(monkeypatch):
    client = MoonrakerPrinterClient("http://voron.local:7125")

    def failing_get(path, *, base_url=None):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(client, "_get", failing_get)
    client.state.gcode_file = "benchy.gcode"

    payload = client._build_lifecycle_payload()

    assert "file_metadata" not in payload
    assert payload["filename"] == "benchy.gcode"


def test_moonraker_metadata_without_weight_merges_filename_grams():
    from backend.app import main

    data = {
        "filename": "3DBenchy_-_K2Plus_-_PLA-_30m41s_-_12g.gcode",
        "file_metadata": {
            "source": "moonraker_file_metadata",
            "layer_height": 0.2,
            "thumbnail_path": ".thumbs/x.png",
        },
    }

    metadata = main._file_metadata_for_archive(SimpleNamespace(provider="klipper"), data)

    assert metadata["source"] == "moonraker_file_metadata"
    assert metadata["filament_used_grams"] == pytest.approx(12.0)
    assert metadata["layer_height"] == pytest.approx(0.2)
    assert metadata["thumbnail_path"] == ".thumbs/x.png"


def test_moonraker_metadata_with_weight_is_used_as_is():
    from backend.app import main

    meta = normalize_moonraker_file_metadata(MOONRAKER_METADATA, "parts/benchy.gcode")
    data = {"filename": "parts/benchy.gcode", "file_metadata": meta}

    assert main._file_metadata_for_archive(SimpleNamespace(provider="mainsail"), data) is meta


def test_apply_moonraker_details_to_archive():
    from backend.app import main

    archive = SimpleNamespace(
        layer_height=None,
        nozzle_diameter=None,
        total_layers=None,
        nozzle_temperature=None,
        bed_temperature=None,
        filament_color=None,
        filament_type=None,
    )
    main._apply_moonraker_details_to_archive(
        archive, normalize_moonraker_file_metadata(MOONRAKER_METADATA, "parts/benchy.gcode")
    )

    assert archive.layer_height == pytest.approx(0.2)
    assert archive.nozzle_diameter == pytest.approx(0.4)
    assert archive.nozzle_temperature == 215
    assert archive.bed_temperature == 60
    assert archive.filament_color == "#FF6600"
    assert archive.filament_type == "PLA"


@pytest.mark.asyncio
async def test_store_moonraker_thumbnail_writes_into_fileless_archive_dir(tmp_path, monkeypatch):
    from backend.app import main
    from backend.app.services import archive as archive_module

    monkeypatch.setattr(archive_module.settings, "base_dir", tmp_path)
    monkeypatch.setattr(archive_module.settings, "archive_dir", tmp_path / "archive")
    monkeypatch.setattr(main.app_settings, "base_dir", tmp_path)

    fake_client = SimpleNamespace(download_thumbnail=lambda path: b"\x89PNG-data" if path.endswith(".png") else None)
    monkeypatch.setattr(main.printer_manager, "get_client", lambda printer_id: fake_client)

    archive = SimpleNamespace(id=42, file_path="", thumbnail_path=None)
    stored = await main._store_moonraker_thumbnail(
        1, archive, {"thumbnail_path": ".thumbs/benchy-300x300.png"}, MagicMock()
    )

    assert stored is True
    # A no-3MF archive owns <archive_dir>/<id> (utils/archive_paths, #1820).
    assert archive.thumbnail_path == "archive/42/thumbnail.png"
    assert (tmp_path / archive.thumbnail_path).read_bytes() == b"\x89PNG-data"


def test_photo_written_under_fileless_dir_is_still_found(tmp_path, monkeypatch):
    """Printbuddy dev builds kept no-3MF archives under archive/_fileless/<id>;
    photos captured there must still be found, before and after a 3MF turns up."""
    from backend.app.core.config import settings as app_config
    from backend.app.utils.archive_paths import find_archive_photo

    monkeypatch.setattr(app_config, "base_dir", tmp_path)
    monkeypatch.setattr(app_config, "archive_dir", tmp_path / "archive")
    legacy = tmp_path / "archive/_fileless/9/photos/finish.jpg"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"jpg")

    archive = SimpleNamespace(id=9, file_path="")
    assert find_archive_photo(archive, "finish.jpg") == legacy

    archive.file_path = "archive/1/20260101_x/x.3mf"
    assert find_archive_photo(archive, "finish.jpg") == legacy
    assert find_archive_photo(archive, "missing.jpg") is None


@pytest.mark.asyncio
async def test_timelapse_listing_skips_bambu_ftp_for_moonraker(monkeypatch):
    from backend.app import main

    list_files = AsyncMock(return_value=[{"name": "x.mp4"}])
    monkeypatch.setattr("backend.app.services.bambu_ftp.list_files_async", list_files)

    printer = SimpleNamespace(provider="klipper", ip_address="10.0.0.5", access_code="", model="Voron")
    assert await main._list_timelapse_videos(printer) == ([], None)

    main._timelapse_baselines.pop(123, None)
    await main._capture_timelapse_baseline_at_start(printer, 123, MagicMock())

    list_files.assert_not_called()
    assert 123 not in main._timelapse_baselines
