"""Bring Printbuddy's own failure history into "Report failed print".

Every print run Printbuddy logged as "failed" or "aborted" becomes a report,
with the reason translated by failure_reason_mapping. Printbuddy's tables
(print_log_entries, print_archives, print_queue) are only read, never changed.

The sync is idempotent. It runs in the background once at startup, after each
finished print (on_print_complete) and after a failure reason or status is
changed in the Edit Archive dialog, never on a read request. A unique index on
print_log_entry_id prevents duplicates even with several workers.

Rules:
* A run that a person already reported keeps the person's reason; the import only
  links it and remembers Printbuddy's text.
* "User cancelled" and "Stale ..." are not failure causes -> not imported.
* Failed runs without any known cause land in "unassigned".
* A withdrawn imported report stays as an invisible marker (dismissed_at), so it
  doesn't come back.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.custom_failure_report import CustomFailureReport
from backend.app.models.print_log import PrintLogEntry
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.services.custom_failure_reports import materials_from_archive
from backend.app.services.failure_reason_mapping import (
    SKIP,
    UNASSIGNED,
    hms_codes_in_text,
    is_automatic_text,
    reason_for_hms_list,
    reason_for_text,
)

logger = logging.getLogger(__name__)

IMPORTED_STATUSES = ("failed", "aborted")
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
SOURCE_IMPORTED = "imported"

# Queue items are matched to a log entry by archive and end time.
QUEUE_MATCH_SECONDS = 3600

_sync_lock = asyncio.Lock()
# Keeps scheduled background syncs referenced until they finish.
_background_tasks: set[asyncio.Task] = set()


def classify_entry(failure_reason: str | None, status: str, hms_codes: list[str]) -> tuple[str | None, str, str | None]:
    """Decide (reason, source, hms_code) for one log entry. reason None = don't import."""
    text = (failure_reason or "").strip()
    hms_reason, hms_code = reason_for_hms_list(hms_codes)
    if text:
        reason = reason_for_text(text)
        if reason == SKIP:
            return None, SOURCE_AUTO, hms_code
        source = SOURCE_AUTO if is_automatic_text(text) else SOURCE_IMPORTED
        if reason is None:
            # Free text nobody knows (other language, API): keep it, but unassigned.
            return UNASSIGNED, source, hms_code
        return reason, source, hms_code
    if status != "failed":
        return None, SOURCE_AUTO, hms_code
    return hms_reason or UNASSIGNED, SOURCE_AUTO, hms_code


def _same_run(report: CustomFailureReport, entry: PrintLogEntry) -> bool:
    """Guards against a reused log entry id (SQLite can reuse ids after the log was cleared)."""
    return report.print_started_at == entry.started_at and (
        report.printer_name is None or entry.printer_name is None or report.printer_name == entry.printer_name
    )


def _queue_codes(queue_items: list[PrintQueueItem], entry: PrintLogEntry) -> list[str]:
    """HMS codes from the queue item that belongs to this run, if the print came from the queue."""
    best, best_delta = None, None
    for item in queue_items:
        if item.completed_at is None or entry.completed_at is None:
            delta = 0 if len(queue_items) == 1 else None
        else:
            delta = abs((item.completed_at - entry.completed_at).total_seconds())
        if delta is None or delta > QUEUE_MATCH_SECONDS:
            continue
        if best_delta is None or delta < best_delta:
            best, best_delta = item, delta
    return hms_codes_in_text(best.error_message) if best else []


def _snapshot(
    report: CustomFailureReport,
    entry: PrintLogEntry,
    archive: PrintArchive | None,
    printer_name: str | None,
) -> None:
    report.printer_id = entry.printer_id if printer_name is not None else None
    report.archive_id = archive.id if archive else None
    report.printer_name = entry.printer_name or printer_name
    report.print_name = entry.print_name or (archive.print_name if archive else None)
    report.filename = archive.filename if archive else None
    report.print_status = entry.status
    report.print_started_at = entry.started_at
    report.reported_at = entry.completed_at or entry.created_at or datetime.now()
    if archive:
        report.materials = materials_from_archive(archive)
        report.filament_used_grams = archive.filament_used_grams
        report.print_time_seconds = archive.print_time_seconds
    else:
        report.materials = (
            [{"type": entry.filament_type, "color": entry.filament_color, "grams": entry.filament_used_grams}]
            if entry.filament_type or entry.filament_color
            else []
        )
        report.filament_used_grams = entry.filament_used_grams
        report.print_time_seconds = entry.duration_seconds


def schedule_failure_history_sync(trigger: str) -> None:
    """Run the sync in the background (startup, print completed, archive edited)."""
    task = asyncio.create_task(run_failure_history_sync(trigger))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def run_failure_history_sync(trigger: str) -> None:
    """Sync with its own session; never raises, so callers' flows can't break."""
    from backend.app.core.database import async_session

    try:
        async with async_session() as db:
            await sync_failure_history(db)
    except Exception as exc:  # e.g. another worker imported the same entry first
        logger.warning("Failure history sync (%s) failed: %s", trigger, exc)


async def sync_failure_history(db: AsyncSession) -> dict:
    """Create / update reports from the print log. Returns counts (for logs and tests)."""
    async with _sync_lock:
        return await _sync(db)


async def _sync(db: AsyncSession) -> dict:
    counts = {"created": 0, "updated": 0, "linked": 0, "removed": 0}
    entries = (
        (await db.execute(select(PrintLogEntry).where(PrintLogEntry.status.in_(IMPORTED_STATUSES)))).scalars().all()
    )
    if not entries:
        return counts

    reports = (await db.execute(select(CustomFailureReport))).scalars().all()
    by_entry = {r.print_log_entry_id: r for r in reports if r.print_log_entry_id is not None}
    unlinked_by_run = {}
    for r in reports:
        if r.print_log_entry_id is None and r.archive_id is not None:
            unlinked_by_run.setdefault((r.archive_id, r.print_started_at), r)

    archive_ids = {e.archive_id for e in entries if e.archive_id is not None}
    archives = {}
    queue_by_archive: dict[int, list[PrintQueueItem]] = {}
    if archive_ids:
        archives = {
            a.id: a
            for a in (await db.execute(select(PrintArchive).where(PrintArchive.id.in_(archive_ids)))).scalars().all()
        }
        for item in (
            await db.execute(
                select(PrintQueueItem).where(
                    PrintQueueItem.archive_id.in_(archive_ids), PrintQueueItem.error_message.is_not(None)
                )
            )
        ).scalars():
            queue_by_archive.setdefault(item.archive_id, []).append(item)
    printer_names = dict((await db.execute(select(Printer.id, Printer.name))).all())

    changed = False
    for entry in entries:
        codes = _queue_codes(queue_by_archive.get(entry.archive_id, []), entry) if entry.archive_id else []
        reason, source, hms_code = classify_entry(entry.failure_reason, entry.status, codes)
        original = (entry.failure_reason or "").strip() or None

        report = by_entry.get(entry.id)
        if report is not None and not _same_run(report, entry):
            report.print_log_entry_id = None  # stale link from a cleared log
            await db.flush()  # free the id before a new report takes it (unique index)
            report = None
            changed = True
        if report is None and entry.archive_id is not None:
            report = unlinked_by_run.pop((entry.archive_id, entry.started_at), None)
            if report is not None:
                report.print_log_entry_id = entry.id
                counts["linked"] += 1
                changed = True

        if report is not None:
            if report.dismissed_at is not None:
                continue
            if report.source == SOURCE_MANUAL:
                # A person decided; only remember what Printbuddy had recorded.
                if report.original_reason != original or (hms_code and report.hms_code != hms_code):
                    report.original_reason = original
                    report.hms_code = hms_code or report.hms_code
                    changed = True
                continue
            if reason is None:
                # E.g. the reason was changed to "User cancelled" in Edit Archive.
                await db.delete(report)
                counts["removed"] += 1
                changed = True
                continue
            if (report.custom_failure_reason, report.source, report.original_reason, report.hms_code) != (
                reason,
                source,
                original,
                hms_code,
            ):
                report.custom_failure_reason = reason
                report.source = source
                report.original_reason = original
                report.hms_code = hms_code
                counts["updated"] += 1
                changed = True
            continue

        if reason is None:
            continue
        report = CustomFailureReport(
            custom_failure_reason=reason,
            source=source,
            original_reason=original,
            hms_code=hms_code,
            print_log_entry_id=entry.id,
        )
        _snapshot(report, entry, archives.get(entry.archive_id), printer_names.get(entry.printer_id))
        db.add(report)
        counts["created"] += 1
        changed = True

    if changed:
        await db.commit()
        if counts["created"] or counts["updated"] or counts["removed"]:
            logger.info("Failure history sync: %s", counts)
    return counts
