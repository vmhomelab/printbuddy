"""Archive metadata for plain and binary G-code files.

Bambu virtual printers always receive a ``.gcode.3mf`` whose metadata
``ThreeMFParser`` reads. Moonraker/OctoPrint-compatible virtual printers (#52)
receive raw ``.gcode`` from OrcaSlicer, PrusaSlicer, SuperSlicer, Cura and
friends, which put the interesting values in comments: thumbnails and some
values in the header, the slicer config block at the end of the file. Only
the head and tail of the file are read, so multi-hundred-MB G-code stays cheap.

Prusa's binary G-code (``.bgcode``, PrusaSlicer's default for MK4/Core One/
XL/MINI) keeps the same key/value pairs in INI metadata blocks and the
thumbnails in thumbnail blocks ahead of the G-code, so only the start of the
file is read there too. Format: https://github.com/prusa3d/libbgcode
"""

from __future__ import annotations

import logging
import re
import struct
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

_HEAD_BYTES = 512 * 1024
_TAIL_BYTES = 256 * 1024

_KV = re.compile(r"^\s*;\s*([A-Za-z_][\w \[\]().-]*?)\s*[=:]\s*(.+?)\s*$")
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([dhms])", re.IGNORECASE)


def _parse_duration(value: str) -> int | None:
    """Parse ``1d 2h 3m 4s`` (PrusaSlicer/Orca) or bare seconds (Cura ``;TIME:``)."""
    value = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return int(float(value))
    total = 0.0
    found = False
    for number, unit in _DURATION_PART.findall(value):
        found = True
        total += float(number) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit.lower()]
    return int(total) if found else None


def _first_number(value: str) -> float | None:
    """First number of a possibly multi-extruder value like ``12.3, 0.0``."""
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _read_head_tail(file_path: Path) -> tuple[str, str]:
    with file_path.open("rb") as f:
        head = f.read(_HEAD_BYTES)
        f.seek(0, 2)
        size = f.tell()
        tail = b""
        if size > _HEAD_BYTES:
            f.seek(max(_HEAD_BYTES, size - _TAIL_BYTES))
            tail = f.read()
    return head.decode("utf-8", errors="ignore"), tail.decode("utf-8", errors="ignore")


def parse_gcode_metadata(file_path: Path) -> dict:
    """Return archive metadata in the same shape as ``ThreeMFParser.parse()``.

    Keys are only set when found. The thumbnail, when present, is returned as
    ``_thumbnail_data`` / ``_thumbnail_ext`` like the 3MF parser does.
    """
    metadata: dict = {}
    try:
        head, tail = _read_head_tail(file_path)
    except OSError as exc:
        logger.warning("Failed to read G-code metadata from %s: %s", file_path, exc)
        return metadata

    values: dict[str, str] = {}
    for line in (head + "\n" + tail).splitlines():
        if not line.lstrip().startswith(";"):
            continue
        match = _KV.match(line)
        if match:
            # Keep the first occurrence: header values describe the job.
            values.setdefault(match.group(1).strip().lower(), match.group(2))

    metadata.update(_metadata_from_values(values))

    try:
        from backend.app.api.routes.library import extract_gcode_thumbnail

        thumbnail = extract_gcode_thumbnail(file_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("G-code thumbnail extraction failed for %s: %s", file_path, exc)
        thumbnail = None
    if thumbnail:
        metadata["_thumbnail_data"] = thumbnail
        metadata["_thumbnail_ext"] = ".jpg" if thumbnail[:3] == b"\xff\xd8\xff" else ".png"

    return metadata


def _metadata_from_values(values: dict[str, str]) -> dict:
    """Map slicer config keys (lower-cased) to archive metadata fields."""
    metadata: dict = {}

    def pick(*keys: str) -> str | None:
        for key in keys:
            if values.get(key):
                return values[key]
        return None

    raw_time = pick(
        "estimated printing time (normal mode)",
        "estimated printing time",
        "model printing time",
        "total estimated time",
        "time",
    )
    if raw_time:
        seconds = _parse_duration(raw_time)
        if seconds:
            metadata["print_time_seconds"] = seconds

    raw_grams = pick("total filament used [g]", "filament used [g]", "filament used [g] (total)")
    if raw_grams:
        grams = _first_number(raw_grams)
        if grams:
            metadata["filament_used_grams"] = round(grams, 2)

    raw_type = pick("filament_type", "initial_filament")
    if raw_type:
        types: list[str] = []
        for part in re.split(r"[;,]", raw_type):
            part = part.strip().strip('"')
            if part and part not in types:
                types.append(part)
        if types:
            metadata["filament_type"] = ", ".join(types)

    raw_color = pick("filament_colour", "filament_color", "extruder_colour")
    if raw_color:
        colors = [c.strip().strip('"') for c in re.split(r"[;,]", raw_color) if c.strip().strip('"')]
        if colors:
            metadata["filament_color"] = ",".join(dict.fromkeys(colors))

    for key, target in (
        ("layer_height", "layer_height"),
        ("nozzle_diameter", "nozzle_diameter"),
        ("first_layer_bed_temperature", "bed_temperature"),
        ("bed_temperature", "bed_temperature"),
        ("first_layer_temperature", "nozzle_temperature"),
        ("nozzle_temperature_initial_layer", "nozzle_temperature"),
        ("temperature", "nozzle_temperature"),
    ):
        if target in metadata or not values.get(key):
            continue
        number = _first_number(values[key])
        if number is not None:
            metadata[target] = number if target in ("layer_height", "nozzle_diameter") else int(number)

    raw_layers = pick("total layer number", "total layers count", "layer_count")
    if raw_layers:
        number = _first_number(raw_layers)
        if number:
            metadata["total_layers"] = int(number)

    printer_model = pick("printer_model", "printer_settings_id")
    if printer_model:
        metadata["sliced_for_model"] = printer_model.strip().strip('"')[:100]

    return metadata


# --------------------------------------------------------------------------
# Binary G-code (.bgcode)
# --------------------------------------------------------------------------

_BGCODE_MAGIC = b"GCDE"
_BLOCK_FILE_METADATA = 0
_BLOCK_GCODE = 1
_BLOCK_SLICER_METADATA = 2
_BLOCK_PRINTER_METADATA = 3
_BLOCK_PRINT_METADATA = 4
_BLOCK_THUMBNAIL = 5
_METADATA_BLOCKS = (_BLOCK_FILE_METADATA, _BLOCK_SLICER_METADATA, _BLOCK_PRINTER_METADATA, _BLOCK_PRINT_METADATA)
_COMPRESSION_NONE = 0
_COMPRESSION_DEFLATE = 1
_THUMB_PNG = 0
_THUMB_JPG = 1
# Metadata and thumbnails sit before the G-code blocks; never read past this.
_BGCODE_SCAN_LIMIT = 16 * 1024 * 1024
_MAX_BLOCK_BYTES = 8 * 1024 * 1024


def _inflate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        return zlib.decompress(data, -15)  # raw deflate stream


def _bgcode_blocks(f, checksum_size: int):
    """Yield ``(block_type, params, payload | None)`` up to the first G-code block.

    ``payload`` is the uncompressed data, or ``None`` when the block was
    skipped (unsupported compression or oversized).
    """
    while f.tell() < _BGCODE_SCAN_LIMIT:
        header = f.read(8)
        if len(header) < 8:
            return
        block_type, compression, uncompressed_size = struct.unpack("<HHI", header)
        compressed_size = uncompressed_size
        if compression != _COMPRESSION_NONE:
            raw = f.read(4)
            if len(raw) < 4:
                return
            (compressed_size,) = struct.unpack("<I", raw)
        if block_type == _BLOCK_GCODE:
            return
        params_size = 6 if block_type == _BLOCK_THUMBNAIL else 2
        params = f.read(params_size)
        if len(params) < params_size:
            return
        if compressed_size > _MAX_BLOCK_BYTES or compression not in (_COMPRESSION_NONE, _COMPRESSION_DEFLATE):
            f.seek(compressed_size + checksum_size, 1)
            yield block_type, params, None
            continue
        data = f.read(compressed_size)
        if len(data) < compressed_size:
            return
        f.seek(checksum_size, 1)
        if compression == _COMPRESSION_DEFLATE:
            try:
                data = _inflate(data)
            except zlib.error:
                yield block_type, params, None
                continue
        yield block_type, params, data


def parse_bgcode_metadata(file_path: Path) -> dict:
    """Return archive metadata for a Prusa binary G-code file.

    Same keys as :func:`parse_gcode_metadata`. Reads the INI metadata blocks
    and the largest PNG/JPG thumbnail up to 300 px wide (QOI thumbnails are
    skipped: browsers can't show them).
    """
    values: dict[str, str] = {}
    best_thumb: tuple[int, int, bytes] | None = None  # (width, format, data)
    try:
        with file_path.open("rb") as f:
            header = f.read(10)
            if len(header) < 10 or header[:4] != _BGCODE_MAGIC:
                logger.warning("Not a binary G-code file: %s", file_path)
                return {}
            _version, checksum_type = struct.unpack("<IH", header[4:10])
            checksum_size = 4 if checksum_type == 1 else 0
            for block_type, params, payload in _bgcode_blocks(f, checksum_size):
                if payload is None:
                    continue
                if block_type in _METADATA_BLOCKS:
                    for line in payload.decode("utf-8", errors="ignore").splitlines():
                        key, sep, value = line.partition("=")
                        if sep and key.strip():
                            values.setdefault(key.strip().lower(), value.strip())
                elif block_type == _BLOCK_THUMBNAIL:
                    fmt, width, _height = struct.unpack("<HHH", params)
                    if fmt not in (_THUMB_PNG, _THUMB_JPG) or width > 300:
                        continue
                    if best_thumb is None or width > best_thumb[0]:
                        best_thumb = (width, fmt, payload)
    except (OSError, struct.error) as exc:
        logger.warning("Failed to read binary G-code metadata from %s: %s", file_path, exc)

    metadata = _metadata_from_values(values)
    if best_thumb:
        metadata["_thumbnail_data"] = best_thumb[2]
        metadata["_thumbnail_ext"] = ".jpg" if best_thumb[1] == _THUMB_JPG else ".png"
    return metadata
