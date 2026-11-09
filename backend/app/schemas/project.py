from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_project_url(value: str | None) -> str | None:
    """Reject anything that isn't an http(s) URL — the URL is rendered as a
    clickable `<a href>` so a `javascript:` / `data:` / `file:` value would be
    an XSS vector even with React's default escaping (#1155)."""
    if value is None:
        return value
    trimmed = value.strip()
    if not trimmed:
        return None
    lowered = trimmed.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("url must start with http:// or https://")
    return trimmed


class ProjectCreate(BaseModel):
    """Schema for creating a new project."""

    name: str
    description: str | None = None
    color: str | None = None
    target_count: int | None = None
    target_parts_count: int | None = None
    notes: str | None = None
    tags: str | None = None
    due_date: datetime | None = None
    priority: str = "normal"
    budget: float | None = None
    parent_id: int | None = None  # For sub-projects
    url: str | None = None
    order_number: str | None = None  # External order / tracking number (e.g. Etsy)
    # File Manager folders to link to the new project right away
    folder_ids: list[int] | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_project_url(v)


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: str | None = None
    description: str | None = None
    color: str | None = None
    status: str | None = None  # active, completed, archived
    target_count: int | None = None
    target_parts_count: int | None = None
    notes: str | None = None
    tags: str | None = None
    due_date: datetime | None = None
    priority: str | None = None
    budget: float | None = None
    parent_id: int | None = None
    url: str | None = None
    order_number: str | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_project_url(v)


class ProjectStats(BaseModel):
    """Statistics for a project."""

    total_archives: int = 0  # Number of archive records
    total_items: int = 0  # Sum of quantities (total items printed)
    completed_prints: int = 0  # Sum of quantities for completed prints
    failed_prints: int = 0  # Sum of quantities for failed prints
    queued_prints: int = 0
    in_progress_prints: int = 0
    total_print_time_hours: float = 0.0
    total_filament_grams: float = 0.0
    progress_percent: float | None = None  # Based on target_count (plates)
    parts_progress_percent: float | None = None  # Based on target_parts_count
    # Cost tracking (Phase 6)
    estimated_cost: float = 0.0  # Based on filament cost
    total_energy_kwh: float = 0.0
    total_energy_cost: float = 0.0
    remaining_prints: int | None = None  # target_count - total_archives
    remaining_parts: int | None = None  # target_parts_count - completed_prints
    # BOM stats (Phase 7)
    bom_total_items: int = 0
    bom_completed_items: int = 0
    bom_cost: float = 0.0  # Total cost of BOM items (sum of unit_price * quantity_needed)
    # Planned totals: from the project plan ("job") when it has rows, else
    # from the slice metadata of files in folders linked to the project.
    planned_source: str | None = None  # "plan" | "files" | None
    planned_print_time_hours: float = 0.0
    planned_filament_grams: float = 0.0
    # Job plan progress (only when the project has plan rows)
    plan_total_plates: int = 0
    plan_completed_plates: int = 0
    plan_queued_plates: int = 0
    plan_printing_plates: int = 0
    plan_failed_plates: int = 0
    plan_remaining_plates: int = 0
    plan_progress_percent: float | None = None


class ProjectChildPreview(BaseModel):
    """Minimal project data for child preview."""

    id: int
    name: str
    color: str | None
    status: str
    progress_percent: float | None = None


class ProjectResponse(BaseModel):
    """Schema for project response."""

    id: int
    name: str
    description: str | None
    color: str | None
    status: str
    target_count: int | None
    target_parts_count: int | None = None
    notes: str | None = None
    attachments: list | None = None
    tags: str | None = None
    due_date: datetime | None = None
    priority: str = "normal"
    budget: float | None = None
    is_template: bool = False
    template_source_id: int | None = None
    parent_id: int | None = None
    parent_name: str | None = None  # For display
    children: list[ProjectChildPreview] = []
    created_at: datetime
    updated_at: datetime
    stats: ProjectStats | None = None
    url: str | None = None
    cover_image_filename: str | None = None
    order_number: str | None = None

    class Config:
        from_attributes = True


class ArchivePreview(BaseModel):
    """Minimal archive data for project preview."""

    id: int
    print_name: str | None
    thumbnail_path: str | None
    status: str
    filament_type: str | None = None
    filament_color: str | None = None


class ProjectListResponse(BaseModel):
    """Schema for project list item (lighter weight)."""

    id: int
    name: str
    description: str | None
    color: str | None
    status: str
    target_count: int | None
    target_parts_count: int | None = None
    budget: float | None = None
    created_at: datetime
    # Quick stats
    archive_count: int = 0  # Number of print jobs
    total_items: int = 0  # Sum of quantities (total items printed, including failed)
    completed_count: int = 0  # Sum of quantities for completed prints only
    failed_count: int = 0  # Sum of quantities for failed prints
    queue_count: int = 0
    progress_percent: float | None = None
    # Preview of archives (up to 5)
    archives: list[ArchivePreview] = []
    # #1155: card-level metadata
    url: str | None = None
    cover_image_filename: str | None = None
    order_number: str | None = None
    # Job plan progress (plates), present when the project has plan rows
    plan_total_plates: int = 0
    plan_completed_plates: int = 0

    class Config:
        from_attributes = True


class BatchAddArchives(BaseModel):
    """Schema for batch adding archives to a project."""

    archive_ids: list[int]


class BatchAddQueueItems(BaseModel):
    """Schema for batch adding queue items to a project."""

    queue_item_ids: list[int]


# Phase 7: BOM Schemas - Tracks sourced/purchased parts
class BOMItemCreate(BaseModel):
    """Schema for creating a BOM item."""

    name: str
    quantity_needed: int = 1
    unit_price: float | None = None
    sourcing_url: str | None = None
    archive_id: int | None = None
    stl_filename: str | None = None
    remarks: str | None = None


class BOMItemUpdate(BaseModel):
    """Schema for updating a BOM item."""

    name: str | None = None
    quantity_needed: int | None = None
    quantity_acquired: int | None = None
    unit_price: float | None = None
    sourcing_url: str | None = None
    archive_id: int | None = None
    stl_filename: str | None = None
    remarks: str | None = None


class BOMItemResponse(BaseModel):
    """Schema for BOM item response."""

    id: int
    project_id: int
    name: str
    quantity_needed: int
    quantity_acquired: int
    unit_price: float | None
    sourcing_url: str | None
    archive_id: int | None
    archive_name: str | None = None
    stl_filename: str | None
    remarks: str | None
    sort_order: int
    is_complete: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Phase 9: Timeline Schemas
class TimelineEvent(BaseModel):
    """Schema for a timeline event."""

    event_type: str  # archive_added, queue_started, queue_completed, status_changed, note_updated
    timestamp: datetime
    title: str
    description: str | None = None
    metadata: dict | None = None  # Additional event-specific data


# Phase 10: Import/Export Schemas
class BOMItemExport(BaseModel):
    """Schema for exporting a BOM item."""

    name: str
    quantity_needed: int
    quantity_acquired: int
    unit_price: float | None
    sourcing_url: str | None
    stl_filename: str | None
    remarks: str | None


class LinkedFolderExport(BaseModel):
    """Schema for exporting a linked library folder."""

    name: str


class ProjectExport(BaseModel):
    """Schema for exporting a project."""

    name: str
    description: str | None
    color: str | None
    status: str
    target_count: int | None
    target_parts_count: int | None
    notes: str | None
    tags: str | None
    due_date: datetime | None
    priority: str
    budget: float | None
    bom_items: list[BOMItemExport] = []
    linked_folders: list[LinkedFolderExport] = []


class ProjectImport(BaseModel):
    """Schema for importing a project."""

    name: str
    description: str | None = None
    color: str | None = None
    status: str = "active"
    target_count: int | None = None
    target_parts_count: int | None = None
    notes: str | None = None
    tags: str | None = None
    due_date: datetime | None = None
    priority: str = "normal"
    budget: float | None = None
    bom_items: list[BOMItemExport] = []
    linked_folders: list[LinkedFolderExport] = []


# Project plan ("Job") schemas — every planned plate of a project
class PlanFilament(BaseModel):
    """Material/colour for one filament slot of a planned plate."""

    slot_id: int = 1
    type: str = ""
    color: str = ""  # hex, e.g. "#000000"
    color_name: str | None = None
    used_grams: float | None = None  # per copy
    original_type: str | None = None  # as sliced in the 3MF
    original_color: str | None = None


class PlanItemCreate(BaseModel):
    library_file_id: int | None = None
    plate_id: int | None = None
    name: str | None = None  # defaults to plate / file name
    group_label: str | None = None
    quantity: int = Field(default=1, ge=1, le=1000)
    # When omitted, filaments + estimates are filled from the file's slice data
    filaments: list[PlanFilament] | None = None
    est_print_time_seconds: int | None = Field(default=None, ge=0)
    est_filament_grams: float | None = Field(default=None, ge=0)
    printer_id: int | None = None
    target_model: str | None = None
    notes: str | None = None


class PlanItemUpdate(BaseModel):
    plate_id: int | None = None
    name: str | None = None
    group_label: str | None = None
    quantity: int | None = Field(default=None, ge=1, le=1000)
    filaments: list[PlanFilament] | None = None
    est_print_time_seconds: int | None = Field(default=None, ge=0)
    est_filament_grams: float | None = Field(default=None, ge=0)
    printer_id: int | None = None  # 0 = clear
    target_model: str | None = None  # "" = clear
    notes: str | None = None
    sort_order: int | None = None


class PlanItemProgress(BaseModel):
    completed: int = 0
    printing: int = 0
    queued: int = 0
    failed: int = 0
    remaining: int = 0  # still to be queued: quantity - completed - printing - queued
    percent: float = 0.0


class PlanItemResponse(BaseModel):
    id: int
    project_id: int
    library_file_id: int | None
    library_file_name: str | None = None
    library_file_missing: bool = False
    is_sliced: bool = False
    thumbnail_url: str | None = None
    plate_id: int | None
    name: str
    group_label: str | None
    quantity: int
    filaments: list[PlanFilament] = []
    est_print_time_seconds: int | None
    est_filament_grams: float | None
    printer_id: int | None
    printer_name: str | None = None
    target_model: str | None
    notes: str | None
    sort_order: int
    progress: PlanItemProgress
    created_at: datetime
    updated_at: datetime


class PlanMaterialTotal(BaseModel):
    type: str
    color: str
    color_name: str | None = None
    planned_grams: float = 0.0
    completed_grams: float = 0.0
    remaining_grams: float = 0.0


class PlanSummary(BaseModel):
    total_plates: int = 0
    completed_plates: int = 0
    printing_plates: int = 0
    queued_plates: int = 0
    failed_plates: int = 0
    remaining_plates: int = 0  # not yet queued
    progress_percent: float | None = None
    planned_print_time_seconds: int = 0
    remaining_print_time_seconds: int = 0  # plates not completed yet
    planned_filament_grams: float = 0.0
    remaining_filament_grams: float = 0.0
    unestimated_items: int = 0  # rows without print-time / filament estimates
    materials: list[PlanMaterialTotal] = []


class PlanEnqueueRequest(BaseModel):
    item_ids: list[int] | None = None  # None = every plan row with copies left to queue
    manual_start: bool = False  # stage items (require manual start)


class PlanEnqueueResult(BaseModel):
    plan_item_id: int
    queued: int = 0
    error: str | None = None


class PlanEnqueueResponse(BaseModel):
    queued_total: int = 0
    results: list[PlanEnqueueResult] = []


class PlanReorder(BaseModel):
    item_ids: list[int]
