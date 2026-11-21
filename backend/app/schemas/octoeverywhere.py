"""Schemas for the OctoEverywhere Gadget failure-detection provider (PB-35)."""

from typing import Literal

from pydantic import BaseModel, Field, StrictInt, field_validator

Sensitivity = Literal["low", "medium", "high"]
Action = Literal["notify", "pause", "pause_and_off"]


def _validate_poll_interval(v: int | None) -> int | None:
    # 0 = follow Gadget's recommended interval; otherwise a fixed 5-120 s.
    if v is None or v == 0 or 5 <= v <= 120:
        return v
    raise ValueError("poll_interval must be 0 (automatic) or between 5 and 120 seconds")


class OctoEverywhereSettings(BaseModel):
    """Stored settings. The API key itself is never returned."""

    enabled: bool = False
    has_api_key: bool = False
    sensitivity: Sensitivity = "medium"
    action: Action = "notify"
    poll_interval: int = Field(default=0, description="0 = automatic (Gadget's recommended interval)")
    enabled_printers: list[int] | None = Field(default=None, description="None = all connected printers")
    notify_on_warning: bool = True


class OctoEverywhereSettingsUpdate(BaseModel):
    enabled: bool | None = None
    api_key: str | None = Field(
        default=None,
        max_length=512,
        description="New API key. Empty string clears the stored key; omit to keep it.",
    )
    sensitivity: Sensitivity | None = None
    action: Action | None = None
    poll_interval: int | None = None
    enabled_printers: list[StrictInt] | None = Field(
        default=None,
        description="Printer IDs to monitor. Send null together with all_printers=true to monitor all.",
    )
    all_printers: bool | None = Field(default=None, description="true = monitor all connected printers")
    notify_on_warning: bool | None = None

    @field_validator("poll_interval")
    @classmethod
    def check_poll_interval(cls, v: int | None) -> int | None:
        return _validate_poll_interval(v)


class OctoEverywhereTestRequest(BaseModel):
    """Optional key override so the settings form can test before saving."""

    api_key: str | None = Field(default=None, max_length=512)


class OctoEverywhereTestResult(BaseModel):
    ok: bool
    error_type: str | None = None
    error: str | None = None
