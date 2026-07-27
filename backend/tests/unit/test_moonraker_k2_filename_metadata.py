from types import SimpleNamespace

import pytest


def test_k2_filename_metadata_parses_material_time_and_grams_from_underscore_name():
    from backend.app import main

    metadata = main._filename_filament_metadata("3DBenchy_-_K2Plus_-_PLA-_30m41s_-_12g.gcode")

    assert metadata["source"] == "creality_filename_meta"
    assert metadata["filament_used_grams"] == pytest.approx(12.0)
    assert metadata["filament_type"] == "PLA"
    assert metadata["print_time_seconds"] == 30 * 60 + 41


def test_k2_filename_metadata_parses_material_time_and_grams_from_spaced_name():
    from backend.app import main

    metadata = main._filename_filament_metadata("3DBenchy - K2Plus - PLA- 30m41s - 12g.gcode")

    assert metadata["source"] == "creality_filename_meta"
    assert metadata["filament_used_grams"] == pytest.approx(12.0)
    assert metadata["filament_type"] == "PLA"
    assert metadata["print_time_seconds"] == 30 * 60 + 41


def test_moonraker_fallback_archive_uses_k2_filename_metadata():
    from backend.app import main

    data = {
        "filename": "3DBenchy_-_K2Plus_-_PLA-_30m41s_-_12g.gcode",
        "raw_data": {
            "filename": "3DBenchy-K2Plus-_PLA-30m41s-_12g.gcode",
        },
    }

    metadata = main._file_metadata_for_archive(
        SimpleNamespace(provider="fluidd", model="Creality K2 Plus"),
        data,
    )

    assert metadata["source"] == "creality_filename_meta"
    assert metadata["filament_used_grams"] == pytest.approx(12.0)
    assert metadata["filament_type"] == "PLA"
    assert metadata["print_time_seconds"] == 1841
    assert data["file_metadata"] == metadata


def test_non_metadata_filename_is_ignored_for_moonraker_archive():
    from backend.app import main

    data = {"filename": "Cube_PLA.gcode"}

    assert main._file_metadata_for_archive(SimpleNamespace(provider="fluidd"), data) == {}
    assert "file_metadata" not in data
