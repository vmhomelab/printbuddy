"""Pydantic schemas for the pending slot assignment API."""

from datetime import datetime

from pydantic import BaseModel, model_validator


class PendingSlotAssignmentCreate(BaseModel):
    """Request body for POST /api/v1/inventory/spools/assign-on-next-slot."""

    tray_uuid: str | None = None
    tag_uid: str | None = None
    printer_id: int | None = None
    source: str
    timeout: int

    @model_validator(mode="after")
    def _require_at_least_one_identifier(self) -> "PendingSlotAssignmentCreate":
        if not self.tray_uuid and not self.tag_uid:
            raise ValueError("At least one of tray_uuid or tag_uid must be provided.")
        return self


class PendingSlotAssignmentResponse(BaseModel):
    """Response body for assignment endpoints."""

    assignment_id: int
    tray_uuid: str | None = None
    tag_uid: str | None = None
    spool_id: int | None = None
    printer_id: int | None = None
    source: str
    status: str  # pending, completed, timed_out, cancelled
    timeout_seconds: int
    # Completion details
    assigned_printer_id: int | None = None
    assigned_ams_id: int | None = None
    assigned_tray_id: int | None = None
    completed_at: datetime | None = None
    time_to_placement: float | None = None
    created_at: datetime

    class Config:
        from_attributes = True
