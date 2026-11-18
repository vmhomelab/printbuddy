"""Endpoints for managing the selectable "Report failed print" reasons.

Everyone who may report can read the reasons; changing them needs settings rights
(no login = everyone). See backend/app/services/custom_failure_reasons.py.
"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequireCameraStreamTokenIfAuthEnabled, RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.custom_failure_report import CustomFailureReason
from backend.app.services import custom_failure_reasons as reasons_service
from backend.app.services.custom_failure_reports import clean_text

router = APIRouter(prefix="/custom-failure-reports/reasons", tags=["custom-failure-reports"])

ICON_NAME_PATTERN = r"^[A-Za-z0-9]{1,50}$"


class CustomFailureReasonResponse(BaseModel):
    id: int
    code: str
    title: str | None = None
    subtitle: str | None = None
    icon: str | None = None
    custom_icon_filename: str | None = None
    is_system: bool
    is_hidden: bool
    sort_order: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _default_icon(self):
        """Default reasons without a picked icon show the icon defined in code."""
        if not self.icon and self.is_system:
            self.icon = reasons_service.DEFAULT_ICONS.get(self.code)
        return self


class CustomFailureReasonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    subtitle: str | None = Field(default=None, max_length=300)
    icon: str | None = Field(default=None, pattern=ICON_NAME_PATTERN)


class CustomFailureReasonUpdate(BaseModel):
    # For default reasons an empty title/subtitle means "back to the translated default text".
    title: str | None = Field(default=None, max_length=100)
    subtitle: str | None = Field(default=None, max_length=300)
    icon: str | None = Field(default=None, pattern=ICON_NAME_PATTERN)
    is_hidden: bool | None = None


class ReasonOrder(BaseModel):
    ids: list[int] = Field(max_length=reasons_service.MAX_REASONS)


async def _get_reason_or_404(db: AsyncSession, reason_id: int) -> CustomFailureReason:
    reason = await reasons_service.get_reason(db, reason_id)
    if not reason:
        raise HTTPException(404, "Failure reason not found")
    return reason


@router.get("/", response_model=list[CustomFailureReasonResponse])
async def get_reasons(
    include_hidden: bool = Query(default=False),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Reasons in display order (hidden ones only on request, e.g. for settings and statistics)."""
    return await reasons_service.list_reasons(db, include_hidden=include_hidden)


@router.post("/", response_model=CustomFailureReasonResponse)
async def create_reason(
    data: CustomFailureReasonCreate,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    title = clean_text(data.title)
    if not title:
        raise HTTPException(400, "A title is required")
    try:
        return await reasons_service.create_reason(db, title, clean_text(data.subtitle), data.icon)
    except reasons_service.ReasonLimitReached as exc:
        raise HTTPException(400, f"At most {reasons_service.MAX_REASONS} failure reasons are possible") from exc


@router.put("/order", response_model=list[CustomFailureReasonResponse])
async def reorder_reasons(
    data: ReasonOrder,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    await reasons_service.reorder_reasons(db, data.ids)
    return await reasons_service.list_reasons(db, include_hidden=True)


@router.post("/restore-defaults")
async def restore_defaults(
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    return {"restored": await reasons_service.restore_defaults(db)}


@router.patch("/{reason_id}", response_model=CustomFailureReasonResponse)
async def update_reason(
    reason_id: int,
    data: CustomFailureReasonUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    reason = await _get_reason_or_404(db, reason_id)
    changes = data.model_dump(exclude_unset=True)
    if "title" in changes:
        title = clean_text(changes["title"])
        if not title and not reason.is_system:
            raise HTTPException(400, "A title is required")
        reason.title = title
    if "subtitle" in changes:
        reason.subtitle = clean_text(changes["subtitle"])
    if "icon" in changes:
        reason.icon = changes["icon"]
    if "is_hidden" in changes and changes["is_hidden"] is not None:
        reason.is_hidden = changes["is_hidden"]
    await db.commit()
    await db.refresh(reason)
    return reason


@router.delete("/{reason_id}")
async def delete_reason(
    reason_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Default reasons and reasons with reports are hidden; unused custom reasons are deleted."""
    reason = await _get_reason_or_404(db, reason_id)
    return {"status": await reasons_service.remove_reason(db, reason)}


@router.post("/{reason_id}/icon", response_model=CustomFailureReasonResponse)
async def upload_icon(
    reason_id: int,
    file: UploadFile = File(...),
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Use an own image as icon. It is scaled down to fit 500x500 px."""
    reason = await _get_reason_or_404(db, reason_id)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in reasons_service.ICON_UPLOAD_EXTENSIONS:
        raise HTTPException(400, "Image must be JPG, PNG, GIF, or WebP")
    try:
        data = await file.read(reasons_service.ICON_UPLOAD_MAX_BYTES + 1)
    finally:
        await file.close()
    if len(data) > reasons_service.ICON_UPLOAD_MAX_BYTES:
        raise HTTPException(400, "Image is too large (max 10 MiB)")
    try:
        filename = reasons_service.save_icon(data, reason.id)
    except reasons_service.InvalidIconImage as exc:
        raise HTTPException(400, str(exc)) from exc

    old_filename = reason.custom_icon_filename
    reason.custom_icon_filename = filename
    await db.commit()
    await db.refresh(reason)
    reasons_service.remove_icon_file(old_filename, reason.id)
    return reason


@router.get("/{reason_id}/icon")
async def get_icon(
    reason_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = RequireCameraStreamTokenIfAuthEnabled,
):
    reason = await _get_reason_or_404(db, reason_id)
    path = reasons_service.icon_path(reason.custom_icon_filename, reason.id)
    if not path or not path.is_file():
        raise HTTPException(404, "No custom icon set")
    return FileResponse(path, media_type="image/png")


@router.delete("/{reason_id}/icon", response_model=CustomFailureReasonResponse)
async def delete_icon(
    reason_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Go back to the built-in icon."""
    reason = await _get_reason_or_404(db, reason_id)
    old_filename = reason.custom_icon_filename
    reason.custom_icon_filename = None
    await db.commit()
    await db.refresh(reason)
    reasons_service.remove_icon_file(old_filename, reason.id)
    return reason
