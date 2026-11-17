"""Endpoints for the selectable "Report failed print" reasons.

Reasons are read-only here: the default reasons are created on first use
(see backend/app/services/custom_failure_reasons.py).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import custom_failure_reasons as reasons_service

router = APIRouter(prefix="/custom-failure-reports/reasons", tags=["custom-failure-reports"])


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


@router.get("/", response_model=list[CustomFailureReasonResponse])
async def get_reasons(
    include_hidden: bool = Query(default=False),
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Reasons in display order (hidden ones only on request, e.g. for settings and statistics)."""
    return await reasons_service.list_reasons(db, include_hidden=include_hidden)
