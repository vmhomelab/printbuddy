import logging
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


def test_moonraker_fallback_archive_prefers_k2_cur_print_data_filament_grams():
    from backend.app import main

    data = {
        "status": "completed",
        "filename": "Cube_PLA_1m26s.gcode",
        "raw_data": {
            "virtual_sdcard": {
                "cur_print_data": {
                    "filament_used": 0.0,
                    "filename": "Cube_PLA_1m26s.gcode",
                    "metadata": {
                        "estimated_time": 86,
                        "filament_type": "PLA",
                        "default_filament_colour": ["#0a2989", "", "", ""],
                        "filament_used_g": ["0.84", "0.00", "0.00", "0.00"],
                    },
                    "print_duration": 0.0,
                    "status": "completed",
                    "total_duration": 259.32381003999035,
                }
            }
        },
    }

    metadata = main._file_metadata_for_archive(
        SimpleNamespace(provider="fluidd", model="Creality K2 Plus"),
        data,
    )

    assert metadata["source"] == "k2_cur_print_data"
    assert metadata["filament_used_grams"] == pytest.approx(0.84)
    assert metadata["filament_type"] == "PLA"
    assert metadata["print_time_seconds"] == 86
    assert metadata["filament_slots"] == [
        {"slot": 0, "filament_used_grams": 0.84, "filament_type": "PLA", "color": "#0a2989"},
        {"slot": 1, "filament_used_grams": 0.0, "filament_type": "PLA", "color": ""},
        {"slot": 2, "filament_used_grams": 0.0, "filament_type": "PLA", "color": ""},
        {"slot": 3, "filament_used_grams": 0.0, "filament_type": "PLA", "color": ""},
    ]
    assert data["file_metadata"] == metadata


@pytest.mark.asyncio
async def test_k2_cur_print_data_updates_no_3mf_archive(db_session, printer_factory, archive_factory):
    from backend.app import main

    printer = await printer_factory(provider="fluidd", model="Creality K2 Plus")
    archive = await archive_factory(
        printer.id,
        filename="Cube_PLA_1m26s.gcode",
        file_path="",
        filament_used_grams=None,
        print_time_seconds=None,
        status="printing",
        extra_data={"no_3mf_available": True},
    )
    data = {
        "status": "completed",
        "filename": "Cube_PLA_1m26s.gcode",
        "raw_data": {
            "virtual_sdcard": {
                "cur_print_data": {
                    "filename": "Cube_PLA_1m26s.gcode",
                    "metadata": {
                        "estimated_time": 86,
                        "filament_type": "PLA",
                        "default_filament_colour": ["#0a2989", "", "", ""],
                        "filament_used_g": ["0.84", "0.00", "0.00", "0.00"],
                    },
                    "status": "completed",
                    "total_duration": 259.32381003999035,
                }
            }
        },
    }

    updated = await main._apply_file_metadata_to_archive(
        db_session,
        printer.id,
        printer,
        archive,
        data,
        logging.getLogger(__name__),
    )
    await db_session.commit()
    await db_session.refresh(archive)

    assert updated is True
    assert archive.filament_used_grams == pytest.approx(0.84)
    assert archive.filament_type == "PLA"
    assert archive.print_time_seconds == 86
    assert archive.extra_data["file_metadata"]["source"] == "k2_cur_print_data"
    assert archive.extra_data["file_metadata"]["filament_slots"][0]["filament_used_grams"] == pytest.approx(0.84)


def test_moonraker_fallback_archive_ignores_stale_k2_cur_print_data_from_previous_file():
    from backend.app import main

    data = {
        "status": "RUNNING",
        "filename": "NewJob_PLA_5m.gcode",
        "raw_data": {
            "virtual_sdcard": {
                "cur_print_data": {
                    "filename": "PreviousJob_PLA_1m26s.gcode",
                    "metadata": {
                        "estimated_time": 86,
                        "filament_type": "PLA",
                        "filament_used_g": ["0.84"],
                    },
                    "status": "completed",
                }
            }
        },
    }

    assert main._file_metadata_for_archive(SimpleNamespace(provider="fluidd", model="Creality K2 Plus"), data) == {}
    assert "file_metadata" not in data


def test_non_metadata_filename_is_ignored_for_moonraker_archive():
    from backend.app import main

    data = {"filename": "Cube_PLA.gcode"}

    assert main._file_metadata_for_archive(SimpleNamespace(provider="fluidd"), data) == {}
    assert "file_metadata" not in data
