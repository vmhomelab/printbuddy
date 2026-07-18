"""Direct printer-storage print filament usage tracking.

Some providers, notably Elegoo SDCP / Centauri Carbon, can start a G-code file
that already lives on the printer without a Printbuddy archive/3MF. In that
workflow the normal 3MF usage tracker has no archive metadata to read, but the
printer WebUI exposes a preflight file-info estimate (Cmd 260 / EstWeight).
This module stores that short-lived estimate and applies it to the fallback
archive plus the loaded single-spool assignment when the print completes.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.spool import Spool
from backend.app.models.spool_assignment import SpoolAssignment
from backend.app.models.spool_usage_history import SpoolUsageHistory
from backend.app.models.spoolman_slot_assignment import SpoolmanSlotAssignment

logger = logging.getLogger(__name__)

_LOADED_SPOOL_AMS_ID = 255
_LOADED_SPOOL_TRAY_ID = 0


@dataclass(slots=True)
class DirectPrintMetadata:
    printer_id: int
    filename: str
    estimated_weight_grams: float
    estimated_time_seconds: int | None = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_direct_prints: dict[int, DirectPrintMetadata] = {}


def _normalize_filename(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # Compare both full printer paths and basenames; CC1 may report either
    # "/local/file.gcode" or just "file.gcode" in completion status.
    return PurePosixPath(text.replace("\\", "/")).name.lower()


def _matches(metadata: DirectPrintMetadata, filename: str | None) -> bool:
    if not filename:
        return True
    raw = str(filename).strip()
    if raw == metadata.filename:
        return True
    return _normalize_filename(raw) == _normalize_filename(metadata.filename)


def register_direct_print_metadata(
    printer_id: int,
    filename: str,
    estimated_weight_grams: float | int | None,
    estimated_time_seconds: int | None = None,
) -> None:
    """Register one active direct printer-storage print estimate."""
    try:
        weight = float(estimated_weight_grams or 0)
    except (TypeError, ValueError):
        weight = 0.0
    if weight <= 0:
        logger.debug("Direct print metadata for printer %s has no positive EstWeight; skipping", printer_id)
        return
    _direct_prints[printer_id] = DirectPrintMetadata(
        printer_id=printer_id,
        filename=filename,
        estimated_weight_grams=weight,
        estimated_time_seconds=estimated_time_seconds,
        registered_at=datetime.now(timezone.utc),
    )
    logger.info(
        "Registered direct print estimate for printer %s: %s %.2fg",
        printer_id,
        filename,
        weight,
    )


def pop_direct_print_metadata(printer_id: int, filename: str | None = None) -> DirectPrintMetadata | None:
    metadata = _direct_prints.get(printer_id)
    if metadata is None:
        return None
    if not _matches(metadata, filename):
        logger.debug(
            "Direct print metadata filename mismatch for printer %s: registered=%s completed=%s",
            printer_id,
            metadata.filename,
            filename,
        )
        return None
    return _direct_prints.pop(printer_id, None)


async def _apply_metadata_to_archive(
    metadata: DirectPrintMetadata,
    archive_id: int | None,
    db: AsyncSession,
) -> None:
    if not archive_id:
        return
    archive = await db.get(PrintArchive, archive_id)
    if archive is None:
        return

    if not archive.filament_used_grams:
        archive.filament_used_grams = metadata.estimated_weight_grams
    if metadata.estimated_time_seconds and not archive.print_time_seconds:
        archive.print_time_seconds = metadata.estimated_time_seconds

    extra_data = dict(archive.extra_data or {}) if isinstance(archive.extra_data, dict) else {}
    extra_data["file_metadata"] = {
        **(extra_data.get("file_metadata") if isinstance(extra_data.get("file_metadata"), dict) else {}),
        "source": "elegoo_sdcp_file_info",
        "filename": metadata.filename,
        "filament_used_grams": metadata.estimated_weight_grams,
        "print_time_seconds": metadata.estimated_time_seconds,
    }
    archive.extra_data = extra_data
    await db.commit()
    logger.info(
        "Direct print %s: applied %.2fg estimate to archive %s",
        metadata.filename,
        metadata.estimated_weight_grams,
        archive_id,
    )


async def _get_spoolman_client_with_fallback():
    from backend.app.services.spoolman_tracking import _get_spoolman_client_with_fallback as _get_client

    return await _get_client()


async def report_spoolman_usage(
    printer_id: int,
    data: dict,
    db: AsyncSession,
    *,
    archive_id: int | None = None,
) -> list[dict]:
    """Report direct print EstWeight to the loaded Spoolman spool assignment."""
    filename = data.get("filename") or data.get("subtask_name")
    metadata = pop_direct_print_metadata(printer_id, filename)
    if metadata is None:
        return []

    status = data.get("status", "completed")
    if status != "completed":
        logger.info(
            "Direct print %s on printer %s ended as %s; cleared Spoolman estimate without usage",
            metadata.filename,
            printer_id,
            status,
        )
        return []

    await _apply_metadata_to_archive(metadata, archive_id, db)

    weight_used = metadata.estimated_weight_grams
    if weight_used <= 0:
        return []

    assignment_result = await db.execute(
        select(SpoolmanSlotAssignment).where(
            SpoolmanSlotAssignment.printer_id == printer_id,
            SpoolmanSlotAssignment.ams_id == _LOADED_SPOOL_AMS_ID,
            SpoolmanSlotAssignment.tray_id == _LOADED_SPOOL_TRAY_ID,
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        logger.info(
            "Direct print %s has no loaded Spoolman spool assignment for printer %s", metadata.filename, printer_id
        )
        return []

    maybe_client = _get_spoolman_client_with_fallback()
    client = await maybe_client if inspect.isawaitable(maybe_client) else maybe_client
    if not client:
        return []

    await client.use_spool(assignment.spoolman_spool_id, weight_used)
    logger.info(
        "Direct print %s: reported %.2fg to Spoolman spool %s on printer %s",
        metadata.filename,
        weight_used,
        assignment.spoolman_spool_id,
        printer_id,
    )
    result = {
        "spoolman_spool_id": assignment.spoolman_spool_id,
        "ams_id": _LOADED_SPOOL_AMS_ID,
        "tray_id": _LOADED_SPOOL_TRAY_ID,
        "weight_used": weight_used,
        "source": "direct_file_estimate",
    }
    if archive_id:
        result["archive_id"] = archive_id
    return [result]


async def report_inventory_usage(
    printer_id: int,
    data: dict,
    db: AsyncSession,
    *,
    archive_id: int | None = None,
) -> list[dict]:
    """Debit the loaded internal-inventory spool from a direct print estimate."""
    filename = data.get("filename") or data.get("subtask_name")
    metadata = pop_direct_print_metadata(printer_id, filename)
    if metadata is None:
        return []

    status = data.get("status", "completed")
    if status != "completed":
        logger.info(
            "Direct print %s on printer %s ended as %s; cleared estimate without debiting spool",
            metadata.filename,
            printer_id,
            status,
        )
        return []

    await _apply_metadata_to_archive(metadata, archive_id, db)

    weight_used = metadata.estimated_weight_grams
    if weight_used <= 0:
        return []

    assignment_result = await db.execute(
        select(SpoolAssignment).where(
            SpoolAssignment.printer_id == printer_id,
            SpoolAssignment.ams_id == _LOADED_SPOOL_AMS_ID,
            SpoolAssignment.tray_id == _LOADED_SPOOL_TRAY_ID,
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        logger.info("Direct print %s has no loaded spool assignment for printer %s", metadata.filename, printer_id)
        return []

    spool_result = await db.execute(select(Spool).where(Spool.id == assignment.spool_id))
    spool = spool_result.scalar_one_or_none()
    if spool is None:
        return []

    spool.weight_used = (spool.weight_used or 0) + weight_used
    spool.last_used = datetime.now(timezone.utc)
    percent_used = int(round((weight_used / spool.label_weight) * 100)) if spool.label_weight else 0
    cost = (weight_used / 1000.0) * spool.cost_per_kg if spool.cost_per_kg else None

    history = SpoolUsageHistory(
        spool_id=spool.id,
        printer_id=printer_id,
        print_name=metadata.filename,
        weight_used=weight_used,
        percent_used=percent_used,
        status=status,
        cost=cost,
        archive_id=archive_id,
    )
    db.add(history)
    await db.commit()

    logger.info(
        "Direct print %s: debited %.2fg from loaded spool %s on printer %s",
        metadata.filename,
        weight_used,
        spool.id,
        printer_id,
    )
    result = {
        "spool_id": spool.id,
        "ams_id": _LOADED_SPOOL_AMS_ID,
        "tray_id": _LOADED_SPOOL_TRAY_ID,
        "weight_used": weight_used,
        "percent_used": percent_used,
        "source": "direct_file_estimate",
        "cost": cost,
    }
    if archive_id:
        result["archive_id"] = archive_id
    return [result]
