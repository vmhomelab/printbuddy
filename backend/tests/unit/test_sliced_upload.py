"""Tests for preparing sliced files for G-code (non-Bambu) printers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from backend.app.utils.sliced_upload import SlicedUploadError, prepare_sliced_upload


def _make_3mf(path: Path, plates: dict[int, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        archive.writestr("Metadata/plate_1.png", b"png")
        for number, gcode in plates.items():
            archive.writestr(f"Metadata/plate_{number}.gcode", gcode)
            archive.writestr(f"Metadata/plate_{number}.gcode.md5", "x")
    return path


@pytest.mark.parametrize("provider", ["bambu"])
def test_bambu_gets_the_3mf_unchanged(tmp_path, provider):
    source = _make_3mf(tmp_path / "Cube.gcode.3mf", {1: "G28\n"})

    upload = prepare_sliced_upload(source, "Cube.gcode.3mf", provider, None)

    assert upload.source == source
    assert upload.filename == "Cube.gcode.3mf"
    assert not upload.extracts_gcode


@pytest.mark.parametrize("filename", ["Cube.gcode", "Cube.bgcode"])
def test_plain_gcode_passes_through_for_gcode_printers(tmp_path, filename):
    source = tmp_path / filename
    source.write_text("G28\n", encoding="utf-8")

    upload = prepare_sliced_upload(source, filename, "moonraker", 1)

    assert upload.source == source
    assert upload.filename == filename
    assert not upload.extracts_gcode


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["moonraker", "klipper", "prusalink", "octoprint", "elegoo_sdcp"])
async def test_single_plate_3mf_becomes_plain_gcode(tmp_path, provider):
    source = _make_3mf(tmp_path / "Cable Holder.gcode.3mf", {1: "; plate 1\nG28\n"})

    upload = prepare_sliced_upload(source, "Cable Holder.gcode.3mf", provider, None)

    assert upload.filename == "Cable Holder.gcode"
    async with upload.local_file() as local:
        assert local.name == "Cable Holder.gcode"
        assert local.read_text(encoding="utf-8") == "; plate 1\nG28\n"
        temp_dir = local.parent
    assert not temp_dir.exists()
    assert source.exists()


@pytest.mark.asyncio
async def test_multi_plate_3mf_uploads_the_selected_plate(tmp_path):
    source = _make_3mf(tmp_path / "Set.gcode.3mf", {1: "; plate 1\n", 2: "; plate 2\n", 3: "; plate 3\n"})

    upload = prepare_sliced_upload(source, "Set.gcode.3mf", "prusalink", 2)

    assert upload.filename == "Set_plate_2.gcode"
    async with upload.local_file() as local:
        assert local.read_text(encoding="utf-8") == "; plate 2\n"


def test_without_plate_the_lowest_sliced_plate_is_used(tmp_path):
    source = _make_3mf(tmp_path / "Set.3mf", {3: "; plate 3\n", 2: "; plate 2\n"})

    upload = prepare_sliced_upload(source, "Set.3mf", "moonraker", None)

    assert upload.filename == "Set_plate_2.gcode"


def test_unsliced_plate_is_rejected_with_the_sliced_plates(tmp_path):
    source = _make_3mf(tmp_path / "Set.gcode.3mf", {1: "G28\n", 3: "G28\n"})

    with pytest.raises(SlicedUploadError, match=r"Plate 2 .* \(sliced plates: 1, 3\)"):
        prepare_sliced_upload(source, "Set.gcode.3mf", "moonraker", 2)


def test_project_without_gcode_is_rejected(tmp_path):
    source = _make_3mf(tmp_path / "Model.3mf", {})

    with pytest.raises(SlicedUploadError, match="contains no sliced G-code"):
        prepare_sliced_upload(source, "Model.3mf", "elegoo_sdcp", None)


def test_unreadable_3mf_is_rejected(tmp_path):
    source = tmp_path / "Broken.gcode.3mf"
    source.write_bytes(b"not a zip")

    with pytest.raises(SlicedUploadError, match="not a readable 3MF"):
        prepare_sliced_upload(source, "Broken.gcode.3mf", "prusalink", None)


def test_gcode_inside_other_folders_is_ignored(tmp_path):
    source = tmp_path / "Odd.gcode.3mf"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode.md5", "x")
        archive.writestr("Other/plate_1.gcode", "G28\n")

    with pytest.raises(SlicedUploadError, match="contains no sliced G-code"):
        prepare_sliced_upload(source, "Odd.gcode.3mf", "moonraker", None)
