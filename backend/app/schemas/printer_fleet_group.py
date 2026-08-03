from datetime import datetime

from pydantic import BaseModel, Field


class PrinterFleetGroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str | None = Field(default=None, max_length=20)
    sort_order: int = 0
    printer_ids: list[int] = Field(default_factory=list)


class PrinterFleetGroupCreate(PrinterFleetGroupBase):
    pass


class PrinterFleetGroupUpdate(PrinterFleetGroupBase):
    pass


class PrinterFleetGroupResponse(PrinterFleetGroupBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
