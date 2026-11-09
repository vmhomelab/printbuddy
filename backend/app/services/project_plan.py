"""Project plan ("Job") helpers.

A project plan lists every plate a job needs: library file + plate,
quantity, material/colour per filament slot and an optional printer
assignment. Progress per plan row is derived from the queue items and
archives that carry the row's ``plan_item_id``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.project_plan import ProjectPlanItem

logger = logging.getLogger(__name__)

FAILED_STATUSES = {"failed", "aborted", "cancelled", "stopped"}


@dataclass
class PlanProgress:
    completed: int = 0
    printing: int = 0
    queued: int = 0
    failed: int = 0
    quantity: int = 0

    @property
    def remaining(self) -> int:
        """Copies that still have to be put into the queue."""
        return max(0, self.quantity - self.completed - self.printing - self.queued)

    @property
    def open_copies(self) -> int:
        """Copies that are not printed yet (queued, printing or not queued)."""
        return max(0, self.quantity - self.completed)

    @property
    def percent(self) -> float:
        if self.quantity <= 0:
            return 0.0
        return round(min(self.completed, self.quantity) / self.quantity * 100, 1)

    def as_dict(self) -> dict:
        return {
            "completed": self.completed,
            "printing": self.printing,
            "queued": self.queued,
            "failed": self.failed,
            "remaining": self.remaining,
            "percent": self.percent,
        }


@dataclass
class PlanOverview:
    items: list[ProjectPlanItem] = field(default_factory=list)
    progress: dict[int, PlanProgress] = field(default_factory=dict)


def normalize_color(color: str | None) -> str:
    """Normalise a colour to ``#RRGGBB`` (drops the alpha channel of #RRGGBBAA)."""
    if not color:
        return ""
    value = color.strip()
    if not value.startswith("#"):
        value = f"#{value}"
    if len(value) == 9:
        value = value[:7]
    return value.upper()


async def compute_plan_progress(db: AsyncSession, items: list[ProjectPlanItem]) -> dict[int, PlanProgress]:
    """Count completed / printing / queued / failed copies per plan row.

    Archives are the durable record (queue history can be cleared), so a
    finished copy counts once whether it is visible through its archive, its
    queue item, or both.
    """
    progress = {item.id: PlanProgress(quantity=item.quantity or 0) for item in items}
    if not items:
        return progress
    ids = list(progress.keys())

    archive_rows = await db.execute(
        select(PrintArchive.id, PrintArchive.plan_item_id, PrintArchive.status).where(
            PrintArchive.plan_item_id.in_(ids), PrintArchive.deleted_at.is_(None)
        )
    )
    counted_archives: set[int] = set()
    for archive_id, plan_item_id, status in archive_rows.all():
        entry = progress[plan_item_id]
        if status == "completed":
            entry.completed += 1
            counted_archives.add(archive_id)
        elif status in FAILED_STATUSES:
            entry.failed += 1
            counted_archives.add(archive_id)
        # "printing"/other archive states are covered by the queue item below

    queue_rows = await db.execute(
        select(PrintQueueItem.plan_item_id, PrintQueueItem.status, PrintQueueItem.archive_id).where(
            PrintQueueItem.plan_item_id.in_(ids)
        )
    )
    for plan_item_id, status, archive_id in queue_rows.all():
        entry = progress[plan_item_id]
        if status == "pending":
            entry.queued += 1
        elif status == "printing":
            # The archive may already say completed/failed while the queue
            # row lags one scheduler tick behind — don't count it twice.
            if archive_id not in counted_archives:
                entry.printing += 1
        elif archive_id in counted_archives:
            continue
        elif status == "completed":
            entry.completed += 1
        elif status in FAILED_STATUSES:
            entry.failed += 1
    return progress


async def load_plan(db: AsyncSession, project_id: int) -> PlanOverview:
    result = await db.execute(
        select(ProjectPlanItem)
        .where(ProjectPlanItem.project_id == project_id)
        .order_by(ProjectPlanItem.sort_order, ProjectPlanItem.id)
    )
    items = list(result.scalars().all())
    return PlanOverview(items=items, progress=await compute_plan_progress(db, items))


def _item_filaments(item: ProjectPlanItem) -> list[dict]:
    return [f for f in (item.filaments or []) if isinstance(f, dict)]


def summarize_plan(overview: PlanOverview) -> dict:
    """Totals for the job: plates, time, grams and grams per material + colour."""
    summary = {
        "total_plates": 0,
        "completed_plates": 0,
        "printing_plates": 0,
        "queued_plates": 0,
        "failed_plates": 0,
        "remaining_plates": 0,
        "progress_percent": None,
        "planned_print_time_seconds": 0,
        "remaining_print_time_seconds": 0,
        "planned_filament_grams": 0.0,
        "remaining_filament_grams": 0.0,
        "unestimated_items": 0,
        "materials": [],
    }
    materials: dict[tuple[str, str], dict] = {}

    for item in overview.items:
        prog = overview.progress.get(item.id) or PlanProgress(quantity=item.quantity)
        qty = item.quantity or 0
        done = min(prog.completed, qty)
        open_copies = prog.open_copies

        summary["total_plates"] += qty
        summary["completed_plates"] += done
        summary["printing_plates"] += prog.printing
        summary["queued_plates"] += prog.queued
        summary["failed_plates"] += prog.failed
        summary["remaining_plates"] += prog.remaining

        if item.est_print_time_seconds:
            summary["planned_print_time_seconds"] += item.est_print_time_seconds * qty
            summary["remaining_print_time_seconds"] += item.est_print_time_seconds * open_copies

        filaments = _item_filaments(item)
        slot_grams_total = sum(float(f.get("used_grams") or 0) for f in filaments)
        per_copy_grams = item.est_filament_grams if item.est_filament_grams is not None else slot_grams_total
        if not item.est_print_time_seconds and not per_copy_grams:
            summary["unestimated_items"] += 1
        summary["planned_filament_grams"] += (per_copy_grams or 0) * qty
        summary["remaining_filament_grams"] += (per_copy_grams or 0) * open_copies

        # Per material/colour. When only a total is known (unsliced file with a
        # manual estimate) attribute it to the first filament entry.
        entries: list[tuple[dict, float]] = []
        if slot_grams_total > 0:
            entries = [(f, float(f.get("used_grams") or 0)) for f in filaments]
        elif filaments and per_copy_grams:
            entries = [(filaments[0], float(per_copy_grams))]
        elif filaments:
            entries = [(filaments[0], 0.0)]
        for fil, grams in entries:
            ftype = (fil.get("type") or "").strip() or "?"
            color = normalize_color(fil.get("color"))
            key = (ftype.upper(), color)
            bucket = materials.setdefault(
                key,
                {
                    "type": ftype,
                    "color": color,
                    "color_name": fil.get("color_name"),
                    "planned_grams": 0.0,
                    "completed_grams": 0.0,
                    "remaining_grams": 0.0,
                },
            )
            if not bucket["color_name"] and fil.get("color_name"):
                bucket["color_name"] = fil.get("color_name")
            bucket["planned_grams"] += grams * qty
            bucket["completed_grams"] += grams * done
            bucket["remaining_grams"] += grams * open_copies

    if summary["total_plates"] > 0:
        summary["progress_percent"] = round(summary["completed_plates"] / summary["total_plates"] * 100, 1)
    summary["planned_filament_grams"] = round(summary["planned_filament_grams"], 2)
    summary["remaining_filament_grams"] = round(summary["remaining_filament_grams"], 2)
    for bucket in materials.values():
        for key in ("planned_grams", "completed_grams", "remaining_grams"):
            bucket[key] = round(bucket[key], 2)
    summary["materials"] = sorted(materials.values(), key=lambda m: -m["planned_grams"])
    return summary


async def linked_files_estimate(db: AsyncSession, project_id: int) -> tuple[int, float, int]:
    """Sum the slice estimates of files in folders linked to the project.

    Returns ``(print_time_seconds, filament_grams, file_count)``; used for the
    project stats when the project has no plan yet.
    """
    result = await db.execute(
        LibraryFile.active()
        .join(LibraryFolder, LibraryFile.folder_id == LibraryFolder.id)
        .where(LibraryFolder.project_id == project_id)
    )
    total_time = 0
    total_grams = 0.0
    count = 0
    for lib_file in result.scalars().all():
        meta = lib_file.file_metadata or {}
        time_s = meta.get("print_time_seconds")
        grams = meta.get("filament_used_grams")
        if time_s or grams:
            count += 1
        try:
            total_time += int(time_s or 0)
            total_grams += float(grams or 0)
        except (TypeError, ValueError):
            continue
    return total_time, round(total_grams, 2), count


async def read_plate_info(db: AsyncSession, lib_file: LibraryFile, plate_id: int | None) -> dict | None:
    """Slice data for one plate: ``{name, print_time_seconds, filament_used_grams, filaments}``.

    Falls back to the file-level metadata for single-plate / G-code files.
    Returns ``None`` when the file has no slice data (STL, unsliced project).
    """
    from backend.app.api.routes.library import get_library_file_plates

    plates: list[dict] = []
    try:
        data = await get_library_file_plates(lib_file.id, db, None)
        plates = data.get("plates") or []
    except HTTPException:
        plates = []
    except Exception as e:  # pragma: no cover - defensive, parsing is best-effort
        logger.warning("Plan: failed to read plates for library file %s: %s", lib_file.id, e)
        plates = []

    plate = None
    if plates:
        if plate_id is not None:
            plate = next((p for p in plates if p.get("index") == plate_id), None)
        if plate is None and plate_id is None:
            plate = plates[0]

    meta = lib_file.file_metadata or {}
    if plate and (plate.get("print_time_seconds") or plate.get("filament_used_grams") or plate.get("filaments")):
        return {
            "name": plate.get("name"),
            "print_time_seconds": plate.get("print_time_seconds"),
            "filament_used_grams": plate.get("filament_used_grams"),
            "filaments": [
                {
                    "slot_id": f.get("slot_id"),
                    "type": f.get("type") or "",
                    "color": f.get("color") or "",
                    "used_grams": f.get("used_grams"),
                }
                for f in plate.get("filaments") or []
            ],
        }

    if plate_id not in (None, 1) and plates:
        # A specific plate was asked for but has no slice data
        return {"name": plate.get("name") if plate else None, "filaments": []}

    if meta.get("print_time_seconds") or meta.get("filament_used_grams"):
        slots = meta.get("filament_slots") or []
        filaments = [
            {
                "slot_id": s.get("slot_id"),
                "type": s.get("type") or "",
                "color": s.get("color") or "",
                "used_grams": s.get("used_g"),
            }
            for s in slots
            if isinstance(s, dict)
        ]
        if not filaments and meta.get("filament_type"):
            first_color = (meta.get("filament_color") or "").split(",")[0]
            filaments = [
                {
                    "slot_id": 1,
                    "type": str(meta.get("filament_type")).split(",")[0].strip(),
                    "color": first_color,
                    "used_grams": meta.get("filament_used_grams"),
                }
            ]
        return {
            "name": plate.get("name") if plate else None,
            "print_time_seconds": meta.get("print_time_seconds"),
            "filament_used_grams": meta.get("filament_used_grams"),
            "filaments": filaments,
        }
    return None


def filaments_from_slice(slice_filaments: list[dict]) -> list[dict]:
    """Plan filament entries for freshly added plates (original = as sliced)."""
    out = []
    for f in slice_filaments:
        color = normalize_color(f.get("color"))
        out.append(
            {
                "slot_id": int(f.get("slot_id") or 1),
                "type": f.get("type") or "",
                "color": color,
                "color_name": None,
                "used_grams": f.get("used_grams"),
                "original_type": f.get("type") or "",
                "original_color": color,
            }
        )
    return out


def filament_overrides_for(item: ProjectPlanItem) -> list[dict] | None:
    """Queue filament overrides for slots whose material/colour was changed."""
    overrides = []
    for fil in _item_filaments(item):
        ftype = (fil.get("type") or "").strip()
        color = normalize_color(fil.get("color"))
        orig_type = (fil.get("original_type") or "").strip()
        orig_color = normalize_color(fil.get("original_color"))
        if not ftype or not color:
            continue
        if orig_type and ftype.upper() == orig_type.upper() and color == orig_color:
            continue
        if not orig_type and not orig_color:
            # Unsliced file: nothing to override against
            continue
        override = {"slot_id": int(fil.get("slot_id") or 1), "type": ftype, "color": color}
        if fil.get("color_name"):
            override["color_name"] = fil["color_name"]
        overrides.append(override)
    return overrides or None


async def detach_plan_items(db: AsyncSession, plan_item_ids: list[int]) -> None:
    """Clear plan links on queue items/archives before plan rows are deleted.

    SQLite runs without FK enforcement here, so ON DELETE SET NULL would not
    fire on its own.
    """
    if not plan_item_ids:
        return
    await db.execute(
        update(PrintQueueItem).where(PrintQueueItem.plan_item_id.in_(plan_item_ids)).values(plan_item_id=None)
    )
    await db.execute(update(PrintArchive).where(PrintArchive.plan_item_id.in_(plan_item_ids)).values(plan_item_id=None))
