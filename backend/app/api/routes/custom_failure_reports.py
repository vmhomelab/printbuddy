"""Endpoints for user-reported failure reasons ("Report failed print").

Separate from the automatic failure_reason / Failure Analysis widget; see
backend/app/services/custom_failure_reports.py.
"""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.archive import PrintArchive
from backend.app.models.custom_failure_report import CustomFailureReport
from backend.app.models.printer import Printer
from backend.app.services.custom_failure_reasons import get_reason_by_code
from backend.app.services.custom_failure_reports import (
    apply_print_snapshot,
    clean_text,
    find_report_for_run,
    find_target_archive,
    list_reports,
    reason_statistics,
    report_to_dict,
)
from backend.app.services.failure_history_import import SOURCE_MANUAL
from backend.app.services.failure_reason_mapping import SKIP, hms_short_code, reason_for_hms_list
from backend.app.services.hms_errors import get_error_description
from backend.app.services.printer_manager import printer_manager

router = APIRouter(prefix="/custom-failure-reports", tags=["custom-failure-reports"])


class MaterialUsage(BaseModel):
    type: str | None = None
    color: str | None = None
    grams: float | None = None


class CustomFailureReportResponse(BaseModel):
    id: int
    custom_failure_reason: str
    comment: str | None = None
    reported_by: str | None = None
    reported_at: datetime | None = None
    printer_id: int | None = None
    printer_name: str | None = None
    archive_id: int | None = None
    print_name: str | None = None
    filename: str | None = None
    print_status: str | None = None
    print_started_at: datetime | None = None
    print_date: datetime | None = None
    materials: list[MaterialUsage] = []
    filament_used_grams: float | None = None
    print_time_seconds: int | None = None
    has_thumbnail: bool = False
    source: Literal["manual", "auto", "imported"] = "manual"
    original_reason: str | None = None
    hms_code: str | None = None
    hms_description: str | None = None


class ReasonSuggestion(BaseModel):
    """A reason the pop-up pre-selects, derived from the printer's current error."""

    reason: str
    hms_code: str
    hms_description: str | None = None


class ReportTargetResponse(BaseModel):
    """The print a new report from this printer would apply to."""

    printer_id: int
    printer_name: str
    is_current_print: bool
    archive_id: int
    print_name: str | None = None
    filename: str | None = None
    print_status: str | None = None
    print_started_at: datetime | None = None
    has_thumbnail: bool = False
    existing_report: CustomFailureReportResponse | None = None
    suggestion: ReasonSuggestion | None = None


class CustomFailureReportCreate(BaseModel):
    printer_id: int
    archive_id: int
    custom_failure_reason: str
    comment: str | None = Field(default=None, max_length=2000)
    reported_by: str | None = Field(default=None, max_length=100)


class CustomFailureReportUpdate(BaseModel):
    custom_failure_reason: str | None = None
    comment: str | None = Field(default=None, max_length=2000)
    reported_by: str | None = Field(default=None, max_length=100)


class ReasonStatistics(BaseModel):
    reason: str
    count: int
    percent: float
    latest: list[CustomFailureReportResponse]


class ReasonStatisticsResponse(BaseModel):
    total: int
    automatic_total: int = 0
    latest_limit: int
    reasons: list[ReasonStatistics]


async def _validate_reason(db: AsyncSession, reason: str, current: str | None = None) -> None:
    """The reason must exist and be visible; a report may keep its current (meanwhile hidden) reason."""
    if reason == current:
        return
    configured = await get_reason_by_code(db, reason)
    if not configured or configured.is_hidden:
        raise HTTPException(400, f"Unknown failure reason '{reason}'")


async def _get_printer(db: AsyncSession, printer_id: int) -> Printer:
    printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one_or_none()
    if not printer:
        raise HTTPException(404, "Printer not found")
    return printer


async def _get_active_report(db: AsyncSession, report_id: int) -> CustomFailureReport:
    report = (
        await db.execute(
            select(CustomFailureReport).where(
                CustomFailureReport.id == report_id, CustomFailureReport.dismissed_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not report:
        raise HTTPException(404, "Report not found")
    return report


def _printer_state(printer_id: int) -> str | None:
    status = printer_manager.get_status(printer_id)
    return getattr(status, "state", None) if status else None


async def _suggestion(db: AsyncSession, printer_id: int) -> dict | None:
    """Pre-select a reason from the printer's active HMS errors (Bambu only), if one maps to a visible reason."""
    status = printer_manager.get_status(printer_id)
    errors = (getattr(status, "hms_errors", None) or []) if status else []
    codes = []
    for error in errors:
        try:
            codes.append(hms_short_code(getattr(error, "attr", 0), getattr(error, "code", 0)))
        except (TypeError, ValueError):
            continue
    reason, code = reason_for_hms_list(codes)
    if not reason or reason == SKIP:
        return None
    configured = await get_reason_by_code(db, reason)
    if not configured or configured.is_hidden:
        return None
    return {"reason": reason, "hms_code": code, "hms_description": get_error_description(code)}


@router.get("/printers/{printer_id}/target", response_model=ReportTargetResponse)
async def get_report_target(
    printer_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Which print a report would flag: the running print, otherwise the most recent one."""
    printer = await _get_printer(db, printer_id)
    state = _printer_state(printer_id)
    archive = await find_target_archive(db, printer_id, state)
    if not archive:
        raise HTTPException(404, "No print found for this printer")

    existing = await find_report_for_run(db, archive)
    has_thumbnail = bool(archive.thumbnail_path)
    return {
        "printer_id": printer.id,
        "printer_name": printer.name,
        "is_current_print": archive.status == "printing",
        "archive_id": archive.id,
        "print_name": archive.print_name,
        "filename": archive.filename,
        "print_status": archive.status,
        "print_started_at": archive.started_at,
        "has_thumbnail": has_thumbnail,
        "existing_report": report_to_dict(existing, has_thumbnail=has_thumbnail) if existing else None,
        "suggestion": await _suggestion(db, printer_id),
    }


@router.post("/", response_model=CustomFailureReportResponse)
async def create_report(
    data: CustomFailureReportCreate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Flag a print run with a reason. Reporting the same run again updates its report."""
    printer = await _get_printer(db, data.printer_id)
    archive = (
        await db.execute(
            select(PrintArchive).where(PrintArchive.id == data.archive_id, PrintArchive.printer_id == printer.id)
        )
    ).scalar_one_or_none()
    if not archive:
        raise HTTPException(404, "Print not found for this printer")

    existing = await find_report_for_run(db, archive, include_dismissed=True)
    current_reason = existing.custom_failure_reason if existing and existing.dismissed_at is None else None
    await _validate_reason(db, data.custom_failure_reason, current_reason)
    report = existing or CustomFailureReport()
    apply_print_snapshot(report, archive, printer)
    # A person decided now: the history import never overwrites this reason again.
    report.source = SOURCE_MANUAL
    report.dismissed_at = None
    report.custom_failure_reason = data.custom_failure_reason
    report.comment = clean_text(data.comment)
    report.reported_by = clean_text(data.reported_by)
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report_to_dict(report, has_thumbnail=bool(archive.thumbnail_path))


@router.patch("/{report_id}", response_model=CustomFailureReportResponse)
async def update_report(
    report_id: int,
    data: CustomFailureReportUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
    db: AsyncSession = Depends(get_db),
):
    """Change the reason, comment or name of an existing report."""
    report = await _get_active_report(db, report_id)

    changes = data.model_dump(exclude_unset=True)
    if "custom_failure_reason" in changes:
        if changes["custom_failure_reason"] is None:
            raise HTTPException(400, "A failure reason is required")
        await _validate_reason(db, changes["custom_failure_reason"], report.custom_failure_reason)
        report.custom_failure_reason = changes["custom_failure_reason"]
        report.source = SOURCE_MANUAL  # confirmed or corrected by a person
    if "comment" in changes:
        report.comment = clean_text(changes["comment"])
    if "reported_by" in changes:
        report.reported_by = clean_text(changes["reported_by"])
    await db.commit()
    await db.refresh(report)
    return report_to_dict(report)


@router.delete("/{report_id}")
async def delete_report(
    report_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_DELETE_ALL),
    db: AsyncSession = Depends(get_db),
):
    """Withdraw a report (e.g. flagged by mistake).

    Reports linked to Printbuddy's print log are kept as an invisible marker, so the
    history import doesn't bring them back.
    """
    report = await _get_active_report(db, report_id)
    if report.print_log_entry_id is not None:
        report.dismissed_at = datetime.now()
    else:
        await db.delete(report)
    await db.commit()
    return {"status": "deleted"}


@router.get("/stats", response_model=ReasonStatisticsResponse)
async def get_statistics(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    source: Literal["person", "automatic"] | None = Query(default=None),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """Per-reason counts and shares with the latest prints for "Fail reason statistics"."""
    return await reason_statistics(db, date_from=date_from, date_to=date_to, source=source)


@router.get("/", response_model=list[CustomFailureReportResponse])
async def get_reports(
    reason: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    source: Literal["person", "automatic"] | None = Query(default=None),
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """All reports (optionally for one reason), newest print first — used by "show all"."""
    return await list_reports(db, reason=reason, date_from=date_from, date_to=date_to, source=source)
