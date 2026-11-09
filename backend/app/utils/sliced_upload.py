"""Prepare sliced files for upload to printers that cannot read 3MF projects.

Bambu printers print ``.gcode.3mf`` projects directly. Every other provider
(Moonraker/Klipper, PrusaLink, Prusa Connect, OctoPrint, Elegoo SDCP) expects
plain G-code. PrintBuddy's integrated slicer, however, always stores its
output as ``.gcode.3mf`` (``Metadata/plate_N.gcode`` inside a 3MF container),
and archives of Bambu prints use the same layout. Uploading such a file
unchanged to a G-code printer produces a file the printer cannot start.

:func:`prepare_sliced_upload` picks the G-code of the plate to print and, for
non-Bambu providers, extracts it to a temporary ``.gcode`` file right before
the upload. Plain ``.gcode`` / ``.bgcode`` files and every upload to a Bambu
printer pass through unchanged.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

_PLATE_GCODE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")
_COPY_CHUNK = 1024 * 1024


class SlicedUploadError(RuntimeError):
    """The file cannot be turned into G-code for the target printer."""


@dataclass(frozen=True)
class SlicedUpload:
    """The file to upload and the printer-side filename it should get.

    ``member`` is the 3MF entry to extract, or ``None`` when ``source`` is
    uploaded as-is.
    """

    source: Path
    filename: str
    member: str | None = None

    @property
    def extracts_gcode(self) -> bool:
        return self.member is not None

    @asynccontextmanager
    async def local_file(self) -> AsyncIterator[Path]:
        """Yield the local path to upload; extracted G-code is removed afterwards."""
        if self.member is None:
            yield self.source
            return
        temp_dir = Path(tempfile.mkdtemp(prefix="printbuddy-gcode-"))
        try:
            target = temp_dir / Path(self.filename).name
            await asyncio.to_thread(_extract_member, self.source, self.member, target)
            yield target
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _extract_member(source: Path, member: str, target: Path) -> None:
    with zipfile.ZipFile(source) as archive, archive.open(member) as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst, _COPY_CHUNK)


def _base_name(filename: str) -> str:
    lower = filename.lower()
    for suffix in (".gcode.3mf", ".3mf"):
        if lower.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def prepare_sliced_upload(file_path: Path, filename: str, provider: str, plate_id: int | None) -> SlicedUpload:
    """Decide what to upload for ``provider``.

    For non-Bambu providers and 3MF files, select the G-code of ``plate_id``
    (or the lowest sliced plate when ``plate_id`` is ``None``) and name it
    ``<name>.gcode``, or ``<name>_plate_<N>.gcode`` when the file holds several
    sliced plates. Raises :class:`SlicedUploadError` when the 3MF holds no
    G-code for that plate.
    """
    if provider == "bambu" or not filename.lower().endswith(".3mf"):
        return SlicedUpload(source=file_path, filename=filename)

    try:
        with zipfile.ZipFile(file_path) as archive:
            plates: dict[int, str] = {}
            for name in archive.namelist():
                match = _PLATE_GCODE.match(name)
                if match:
                    plates[int(match.group(1))] = name
    except (zipfile.BadZipFile, OSError) as exc:
        raise SlicedUploadError(f"{filename} is not a readable 3MF file") from exc

    if not plates:
        raise SlicedUploadError(f"{filename} contains no sliced G-code. Slice it for this printer before printing.")

    plate = plate_id if plate_id else min(plates)
    if plate not in plates:
        sliced = ", ".join(str(number) for number in sorted(plates))
        raise SlicedUploadError(f"Plate {plate} of {filename} is not sliced (sliced plates: {sliced}).")

    base = _base_name(filename)
    gcode_name = f"{base}_plate_{plate}.gcode" if len(plates) > 1 else f"{base}.gcode"
    return SlicedUpload(source=file_path, filename=gcode_name, member=plates[plate])
