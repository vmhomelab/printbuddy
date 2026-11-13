"""Archive metadata from plain and binary G-code (Moonraker/OctoPrint-compatible VPs, #52)."""

import struct
import zlib
from pathlib import Path

from backend.app.services.archive import resolve_display_stem
from backend.app.utils.gcode_metadata import parse_bgcode_metadata, parse_gcode_metadata

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8cfc0f01f0005000201a5c7d4e30000000049454e44ae426082"
)


def _block(block_type: int, params: bytes, payload: bytes, *, deflate: bool, crc: bool) -> bytes:
    """One libbgcode block: header, parameters, data, optional CRC32."""
    if deflate:
        data = zlib.compress(payload)
        header = struct.pack("<HHII", block_type, 1, len(payload), len(data))
    else:
        data = payload
        header = struct.pack("<HHI", block_type, 0, len(payload))
    body = header + params + data
    return body + (struct.pack("<I", zlib.crc32(body)) if crc else b"")


def _write_bgcode(path: Path, *, crc: bool = True) -> None:
    ini = 0  # INI encoding parameter for metadata blocks
    blocks = [
        _block(0, struct.pack("<H", ini), b"Producer=PrusaSlicer 2.9.0\n", deflate=False, crc=crc),
        _block(
            3,
            struct.pack("<H", ini),
            b"printer_model=COREONE\nfilament_type=PETG;PLA\nnozzle_diameter=0.4\n"
            b"layer_height=0.2\nbed_temperature=85\ntemperature=240\n",
            deflate=True,
            crc=crc,
        ),
        # A QOI thumbnail (format 2) must be ignored, the PNG one used.
        _block(5, struct.pack("<HHH", 2, 16, 16), b"qoif....", deflate=False, crc=crc),
        _block(5, struct.pack("<HHH", 0, 1, 1), PNG_1PX, deflate=False, crc=crc),
        _block(
            4,
            struct.pack("<H", ini),
            b"filament used [g]=18.52\nestimated printing time (normal mode)=2h 5m 10s\n",
            deflate=True,
            crc=crc,
        ),
        _block(2, struct.pack("<H", ini), b"total layer number=95\n", deflate=True, crc=crc),
        # G-code blocks end the scan; heatshrink (3) content is never read.
        _block(1, struct.pack("<H", 1), b"\x00" * 64, deflate=False, crc=crc),
    ]
    path.write_bytes(b"GCDE" + struct.pack("<IH", 1, 1 if crc else 0) + b"".join(blocks))


def test_bgcode_metadata_and_thumbnail(tmp_path: Path):
    path = tmp_path / "Benchy_0.4n_0.2mm_PETG_COREONE_2h5m.bgcode"
    _write_bgcode(path)

    meta = parse_bgcode_metadata(path)

    assert meta["print_time_seconds"] == 2 * 3600 + 5 * 60 + 10
    assert meta["filament_used_grams"] == 18.52
    assert meta["filament_type"] == "PETG, PLA"
    assert meta["sliced_for_model"] == "COREONE"
    assert meta["nozzle_diameter"] == 0.4
    assert meta["layer_height"] == 0.2
    assert meta["bed_temperature"] == 85
    assert meta["nozzle_temperature"] == 240
    assert meta["total_layers"] == 95
    assert meta["_thumbnail_data"] == PNG_1PX
    assert meta["_thumbnail_ext"] == ".png"


def test_bgcode_without_checksums(tmp_path: Path):
    path = tmp_path / "a.bgcode"
    _write_bgcode(path, crc=False)
    assert parse_bgcode_metadata(path)["filament_used_grams"] == 18.52


def test_non_bgcode_file_returns_empty(tmp_path: Path):
    path = tmp_path / "fake.bgcode"
    path.write_text("G28\n")
    assert parse_bgcode_metadata(path) == {}


def test_truncated_bgcode_keeps_what_was_read(tmp_path: Path):
    path = tmp_path / "cut.bgcode"
    _write_bgcode(path)
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    meta = parse_bgcode_metadata(path)
    assert meta.get("sliced_for_model") == "COREONE"


def test_plain_gcode_footer_values(tmp_path: Path):
    path = tmp_path / "a.gcode"
    path.write_text(";TIME:600\nG28\n; filament used [g] = 3.5\n; filament_type = PLA\n")
    meta = parse_gcode_metadata(path)
    assert meta["print_time_seconds"] == 600
    assert meta["filament_used_grams"] == 3.5
    assert meta["filament_type"] == "PLA"


def test_display_stem_strips_bgcode():
    assert resolve_display_stem("Benchy.bgcode") == "Benchy"
