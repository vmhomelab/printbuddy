"""Archive metadata for plain G-code files.

Bambu virtual printers always receive a ``.gcode.3mf`` whose metadata
``ThreeMFParser`` reads. Moonraker/OctoPrint-compatible virtual printers (#52)
receive raw ``.gcode`` from OrcaSlicer, PrusaSlicer, SuperSlicer, Cura and
friends, which put the interesting values in comments: thumbnails and some
values in the header, the slicer config block at the end of the file. Only
the head and tail of the file are read, so multi-hundred-MB G-code stays cheap.
"""

from __future__ import annotations

import logging
import re
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
