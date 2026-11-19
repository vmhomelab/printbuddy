"""Remember how far a print got when it stopped or failed ("Stopped/Failed at" in the statistics).

Printbuddy doesn't store this for finished prints. ``record_run_progress`` is
called once from Printbuddy's print-complete handler and writes our own table;
nothing of Printbuddy's is changed. Older prints simply have no value.

Rows belong to an archive: a hard-deleted archive takes its rows with it
(``delete_progress_for_archive``), and the startup sync removes any rows whose
archive is gone some other way (``delete_orphaned_progress``, e.g. when a printer
or user was deleted together with its archives). Reports keep their own copy.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.custom_failure_report import PrintRunProgress

logger = logging.getLogger(__name__)


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 100 else None


def progress_from_completion(data: dict, live_status=None) -> tuple[float | None, int | None, int | None]:
    """(progress %, layer, total layers) from the print-complete data.

    Bambu sends ``last_progress`` (the last value before the firmware resets it),
    Klipper/Moonraker sends ``progress``. The live printer state is the fallback.
    """
    candidates = [_number(data.get("last_progress")), _number(data.get("progress"))]
    if live_status is not None:
        candidates.append(_number(getattr(live_status, "progress", None)))
    known = [value for value in candidates if value is not None]
    # 0 often just means "already reset"; prefer the first real value, keep 0 only if nothing else is known.
    progress = next((value for value in known if value > 0), known[0] if known else None)
    layer = data.get("last_layer_num")
    if layer is None and live_status is not None:
        layer = getattr(live_status, "layer_num", None)
    total = getattr(live_status, "total_layers", None) if live_status is not None else None
    return (
        round(progress, 1) if progress is not None else None,
        int(layer) if isinstance(layer, (int, float)) and layer > 0 else None,
        int(total) if isinstance(total, (int, float)) and total > 0 else None,
    )


async def record_run_progress(db: AsyncSession, printer_id: int, archive_id: int | None, data: dict) -> None:
    """Store the progress of a print that ended without completing. Never raises."""
    try:
        status = data.get("status")
        if status == "completed" or archive_id is None:
            return
        from backend.app.services.printer_manager import printer_manager

        progress, layer, total = progress_from_completion(data, printer_manager.get_status(printer_id))
        if progress is None:
            return
        archive = await db.get(PrintArchive, archive_id)
        if archive is None:
            return
        db.add(
            PrintRunProgress(
                printer_id=printer_id,
                archive_id=archive_id,
                started_at=archive.started_at,
                status=status,
                progress_percent=progress,
                layer_num=layer,
                total_layers=total,
            )
        )
        await db.commit()
    except Exception as exc:  # must never disturb Printbuddy's own print-complete handling
        logger.warning("Could not record print progress for archive %s: %s", archive_id, exc)


async def progress_by_run(db: AsyncSession, archive_ids: set[int]) -> dict[tuple[int, object], float]:
    """{(archive_id, started_at): progress %}; the latest record wins."""
    if not archive_ids:
        return {}
    rows = (
        await db.execute(
            select(PrintRunProgress).where(PrintRunProgress.archive_id.in_(archive_ids)).order_by(PrintRunProgress.id)
        )
    ).scalars()
    return {(r.archive_id, r.started_at): r.progress_percent for r in rows}


async def delete_progress_for_archive(db: AsyncSession, archive_id: int) -> None:
    """Drop the progress rows of an archive that is being hard-deleted (caller commits)."""
    await db.execute(delete(PrintRunProgress).where(PrintRunProgress.archive_id == archive_id))


async def delete_orphaned_progress(db: AsyncSession) -> int:
    """Drop progress rows whose archive no longer exists. Returns how many (caller commits).

    Reads first, so the usual case (nothing to drop) doesn't open a write transaction.
    """
    orphaned = (
        (
            await db.execute(
                select(PrintRunProgress.id).where(
                    PrintRunProgress.archive_id.is_not(None),
                    PrintRunProgress.archive_id.not_in(select(PrintArchive.id)),
                )
            )
        )
        .scalars()
        .all()
    )
    if orphaned:
        await db.execute(delete(PrintRunProgress).where(PrintRunProgress.id.in_(orphaned)))
    return len(orphaned)
