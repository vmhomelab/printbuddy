"""User-reported failure reasons ("Report failed print") and their statistics.

Kept apart from the automatic failure_reason on archives / print log entries:
this module only reads PrintArchive and never writes to it.
"""

from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.custom_failure_report import CustomFailureReport
from backend.app.models.printer import Printer
from backend.app.services.custom_failure_reasons import list_reasons
from backend.app.services.hms_errors import get_error_description

# How many prints per reason the statistics show before "show all (N)".
LATEST_ENTRIES_PER_REASON = 15

ACTIVE_PRINTER_STATES = {"RUNNING", "PAUSE"}

# Statistics filter: who decided the reason.
#   "person"    - reported via "Report failed print" or picked in Printbuddy's Edit Archive dialog
#   "automatic" - derived from what the printer / Printbuddy recorded, not confirmed by anyone
PERSON_SOURCES = ("manual", "imported")
AUTOMATIC_SOURCES = ("auto",)


async def find_target_archive(db: AsyncSession, printer_id: int, printer_state: str | None) -> PrintArchive | None:
    """The print a report applies to: the running print, otherwise the most recent one."""
    base = select(PrintArchive).where(PrintArchive.printer_id == printer_id, PrintArchive.deleted_at.is_(None))
    newest_first = (func.coalesce(PrintArchive.started_at, PrintArchive.created_at).desc(), PrintArchive.id.desc())

    if printer_state in ACTIVE_PRINTER_STATES:
        result = await db.execute(base.where(PrintArchive.status == "printing").order_by(*newest_first).limit(1))
        archive = result.scalar_one_or_none()
        if archive:
            return archive

    result = await db.execute(base.order_by(*newest_first).limit(1))
    return result.scalar_one_or_none()


async def find_report_for_run(
    db: AsyncSession, archive: PrintArchive, include_dismissed: bool = False
) -> CustomFailureReport | None:
    """A print run is identified by its archive plus the run's start time (reprints reuse the archive)."""
    query = select(CustomFailureReport).where(CustomFailureReport.archive_id == archive.id)
    if not include_dismissed:
        query = query.where(CustomFailureReport.dismissed_at.is_(None))
    if archive.started_at is not None:
        query = query.where(CustomFailureReport.print_started_at == archive.started_at)
    result = await db.execute(query.order_by(CustomFailureReport.id.desc()).limit(1))
    return result.scalar_one_or_none()


def _split_list(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def materials_from_archive(archive: PrintArchive) -> list[dict]:
    """Per-material usage of a print, one entry per filament (several for multi-material prints)."""
    slots = (archive.extra_data or {}).get("filament_slots")
    if isinstance(slots, list) and slots:
        return [
            {"type": slot.get("type") or None, "color": slot.get("color") or None, "grams": slot.get("used_g")}
            for slot in slots
            if isinstance(slot, dict)
        ]

    types = _split_list(archive.filament_type)
    colors = _split_list(archive.filament_color)
    if not types and not colors:
        return []
    if len(types) <= 1 and len(colors) <= 1:
        return [
            {
                "type": types[0] if types else None,
                "color": colors[0] if colors else None,
                "grams": archive.filament_used_grams,
            }
        ]
    # Several materials but no per-material amounts: list them, total stays on the report.
    count = max(len(types), len(colors))
    return [
        {
            "type": types[i] if i < len(types) else None,
            "color": colors[i] if i < len(colors) else None,
            "grams": None,
        }
        for i in range(count)
    ]


def apply_print_snapshot(report: CustomFailureReport, archive: PrintArchive, printer: Printer) -> None:
    """Copy the print run's details onto the report."""
    report.printer_id = printer.id
    report.archive_id = archive.id
    report.printer_name = printer.name
    report.print_name = archive.print_name
    report.filename = archive.filename
    report.print_status = archive.status
    report.print_started_at = archive.started_at
    report.materials = materials_from_archive(archive)
    report.filament_used_grams = archive.filament_used_grams
    report.print_time_seconds = archive.print_time_seconds


def _print_date_column():
    return func.coalesce(CustomFailureReport.print_started_at, CustomFailureReport.reported_at)


def _date_filters(date_from: date | None, date_to: date | None, source: str | None = None) -> list:
    filters = [CustomFailureReport.dismissed_at.is_(None)]
    if source == "person":
        filters.append(CustomFailureReport.source.in_(PERSON_SOURCES))
    elif source == "automatic":
        filters.append(CustomFailureReport.source.in_(AUTOMATIC_SOURCES))
    if date_from:
        filters.append(_print_date_column() >= datetime.combine(date_from, time.min))
    if date_to:
        filters.append(_print_date_column() <= datetime.combine(date_to, time.max))
    return filters


async def list_reports(
    db: AsyncSession,
    reason: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int | None = None,
    source: str | None = None,
) -> list[dict]:
    """Reports newest print first, with whether the archive still has a thumbnail."""
    query = (
        select(CustomFailureReport, PrintArchive.thumbnail_path, PrintArchive.deleted_at)
        .outerjoin(PrintArchive, PrintArchive.id == CustomFailureReport.archive_id)
        .where(*_date_filters(date_from, date_to, source))
        .order_by(_print_date_column().desc(), CustomFailureReport.id.desc())
    )
    if reason:
        query = query.where(CustomFailureReport.custom_failure_reason == reason)
    if limit:
        query = query.limit(limit)
    result = await db.execute(query)
    return [
        report_to_dict(report, has_thumbnail=bool(thumbnail_path) and deleted_at is None)
        for report, thumbnail_path, deleted_at in result.all()
    ]


async def latest_reports_per_reason(
    db: AsyncSession,
    limit: int,
    date_from: date | None = None,
    date_to: date | None = None,
    source: str | None = None,
) -> dict[str, list[dict]]:
    """The newest ``limit`` reports of every reason in ONE query (window function, SQLite >= 3.25 and PostgreSQL)."""
    position = (
        func.row_number()
        .over(
            partition_by=CustomFailureReport.custom_failure_reason,
            order_by=(_print_date_column().desc(), CustomFailureReport.id.desc()),
        )
        .label("position")
    )
    ranked = (
        select(CustomFailureReport.id.label("report_id"), position)
        .where(*_date_filters(date_from, date_to, source))
        .subquery()
    )
    result = await db.execute(
        select(CustomFailureReport, PrintArchive.thumbnail_path, PrintArchive.deleted_at)
        .join(ranked, ranked.c.report_id == CustomFailureReport.id)
        .outerjoin(PrintArchive, PrintArchive.id == CustomFailureReport.archive_id)
        .where(ranked.c.position <= limit)
        .order_by(_print_date_column().desc(), CustomFailureReport.id.desc())
    )
    latest: dict[str, list[dict]] = {}
    for report, thumbnail_path, deleted_at in result.all():
        latest.setdefault(report.custom_failure_reason, []).append(
            report_to_dict(report, has_thumbnail=bool(thumbnail_path) and deleted_at is None)
        )
    return latest


def report_to_dict(report: CustomFailureReport, has_thumbnail: bool = False) -> dict:
    return {
        "id": report.id,
        "custom_failure_reason": report.custom_failure_reason,
        "comment": report.comment,
        "reported_by": report.reported_by,
        "reported_at": report.reported_at,
        "printer_id": report.printer_id,
        "printer_name": report.printer_name,
        "archive_id": report.archive_id,
        "print_name": report.print_name,
        "filename": report.filename,
        "print_status": report.print_status,
        "print_started_at": report.print_started_at,
        "print_date": report.print_started_at or report.reported_at,
        "materials": report.materials or [],
        "filament_used_grams": report.filament_used_grams,
        "print_time_seconds": report.print_time_seconds,
        "has_thumbnail": has_thumbnail,
        "source": report.source or "manual",
        "original_reason": report.original_reason,
        "hms_code": report.hms_code,
        "hms_description": get_error_description(report.hms_code) if report.hms_code else None,
    }


async def reason_statistics(
    db: AsyncSession,
    date_from: date | None = None,
    date_to: date | None = None,
    source: str | None = None,
) -> dict:
    """Count and share per reason, plus the latest prints for each.

    Every visible reason is listed (also with 0 reports), plus any reason code
    found in the data that is hidden or no longer configured, so old reports never vanish.
    """
    result = await db.execute(
        select(CustomFailureReport.custom_failure_reason, func.count(CustomFailureReport.id))
        .where(*_date_filters(date_from, date_to, source))
        .group_by(CustomFailureReport.custom_failure_reason)
    )
    counts = dict(result.all())
    total = sum(counts.values())
    automatic_total = (
        await db.execute(
            select(func.count(CustomFailureReport.id)).where(
                *_date_filters(date_from, date_to),
                CustomFailureReport.source.in_(AUTOMATIC_SOURCES),
            )
        )
    ).scalar_one()

    all_reasons = await list_reasons(db, include_hidden=True)
    configured = [reason.code for reason in all_reasons]
    visible = {reason.code for reason in all_reasons if not reason.is_hidden}
    codes = [code for code in configured if code in visible or code in counts]
    codes += sorted(code for code in counts if code not in configured)
    latest = (
        await latest_reports_per_reason(
            db, LATEST_ENTRIES_PER_REASON, date_from=date_from, date_to=date_to, source=source
        )
        if total
        else {}
    )
    reasons = []
    for code in codes:
        count = counts.get(code, 0)
        reasons.append(
            {
                "reason": code,
                "count": count,
                "percent": round(count / total * 100, 1) if total else 0.0,
                "latest": latest.get(code, []),
            }
        )
    # Most frequent first; ties keep the configured order.
    reasons.sort(key=lambda r: -r["count"])
    return {
        "total": total,
        # Across all sources (ignores the source filter), so the UI knows whether to offer the filter.
        "automatic_total": automatic_total,
        "latest_limit": LATEST_ENTRIES_PER_REASON,
        "reasons": reasons,
    }


def clean_text(value: str | None) -> str | None:
    """Normalise optional free text: empty or whitespace-only becomes None."""
    value = (value or "").strip()
    return value or None
