"""Link print-queue items to projects (and optionally to a project's job plan).

Queue items created by a virtual printer in ``print_queue`` mode only carry an
archive (the uploaded 3MF), not a File Manager file. Linking them to a project
sets ``project_id`` on the queue item *and* on its archive so the print shows
up in the project once it runs. Job-plan rows reference File Manager files, so
adding such an item to the plan first copies the archive's 3MF into the File
Manager (deduplicated by content hash).
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.project import Project
from backend.app.models.project_plan import ProjectPlanItem

logger = logging.getLogger(__name__)


@dataclass
class PlanLinkStats:
    plan_items_created: int = 0
    plan_items_linked: int = 0
    library_files_created: int = 0


async def get_project_or_404(db: AsyncSession, project_id: int) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _archive_queue_item_count(db: AsyncSession, archive_id: int) -> int:
    result = await db.execute(select(func.count(PrintQueueItem.id)).where(PrintQueueItem.archive_id == archive_id))
    return int(result.scalar() or 0)


async def apply_project_to_queue_item(db: AsyncSession, item: PrintQueueItem, project_id: int | None) -> None:
    """Set (or clear) the project of a queue item and keep its archive in sync.

    The caller validates ``project_id`` and commits.
    """
    old_project_id = item.project_id
    item.project_id = project_id

    # A plan row belongs to exactly one project; drop a link that no longer fits.
    if item.plan_item_id is not None:
        plan_item = await db.get(ProjectPlanItem, item.plan_item_id)
        if plan_item is None or plan_item.project_id != project_id:
            item.plan_item_id = None

    if item.archive_id is None:
        return
    archive = await db.get(PrintArchive, item.archive_id)
    if archive is None:
        return
    if project_id is not None:
        archive.project_id = project_id
    elif archive.project_id == old_project_id:
        # Only clear the archive link we created; an archive assigned to a
        # different project on the Archives page keeps that assignment.
        archive.project_id = None
    if archive.plan_item_id is not None and item.plan_item_id is None and project_id != old_project_id:
        archive.plan_item_id = None


async def _default_project_folder_id(db: AsyncSession, project_id: int) -> int | None:
    result = await db.execute(
        select(LibraryFolder.id).where(LibraryFolder.project_id == project_id).order_by(LibraryFolder.id).limit(1)
    )
    return result.scalar_one_or_none()


async def copy_archive_to_library(
    db: AsyncSession,
    archive: PrintArchive,
    *,
    folder_id: int | None = None,
    project_id: int | None = None,
    owner_id: int | None = None,
) -> tuple[LibraryFile, bool]:
    """Copy an archive's 3MF into the File Manager; returns ``(file, created)``.

    An active File Manager file with the same content hash is reused instead
    of storing a second copy.
    """
    from backend.app.api.routes.library import (
        calculate_file_hash,
        new_managed_library_path,
        save_downloaded_file_to_library,
    )

    if archive.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Archive was deleted")
    source = settings.base_dir / archive.file_path
    if not source.exists():
        raise HTTPException(status_code=404, detail="Archive file not found on disk")

    file_hash = calculate_file_hash(source)
    existing = await db.execute(LibraryFile.active().where(LibraryFile.file_hash == file_hash).limit(1))
    existing_file = existing.scalar_one_or_none()
    if existing_file is not None:
        if project_id is not None and existing_file.project_id is None:
            existing_file.project_id = project_id
        return existing_file, False

    if folder_id is not None:
        folder = await db.get(LibraryFolder, folder_id)
        if folder is None:
            raise HTTPException(status_code=400, detail="Folder not found")
        if folder.is_external and folder.external_readonly:
            raise HTTPException(status_code=400, detail="Folder is read-only")
    elif project_id is not None:
        folder_id = await _default_project_folder_id(db, project_id)

    filename = archive.filename or Path(archive.file_path).name
    dest = new_managed_library_path(filename)
    shutil.copy2(source, dest)
    try:
        library_file = await save_downloaded_file_to_library(
            db,
            file_path=dest,
            filename=filename,
            folder_id=folder_id,
            source_type="archive",
            owner_id=owner_id,
        )
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if project_id is not None:
        library_file.project_id = project_id
    logger.info("Copied archive %s into File Manager as file %s", archive.id, library_file.id)
    return library_file, True


async def add_queue_items_to_plan(
    db: AsyncSession,
    items: list[PrintQueueItem],
    project_id: int,
    *,
    folder_id: int | None = None,
    owner_id: int | None = None,
) -> PlanLinkStats:
    """Attach queue items to job-plan rows of ``project_id``.

    Items are grouped by (File Manager file, plate). An existing plan row for
    the same file + plate is reused; otherwise a row is created. The row's
    quantity is raised so it covers every queue item linked to it.
    """
    from backend.app.api.routes.project_plan import _display_file_name
    from backend.app.services.project_plan import filaments_from_slice, read_plate_info

    stats = PlanLinkStats()
    archive_files: dict[int, LibraryFile] = {}
    touched_rows: dict[int, ProjectPlanItem] = {}

    for item in items:
        if item.plan_item_id is not None:
            plan_item = await db.get(ProjectPlanItem, item.plan_item_id)
            if plan_item is not None and plan_item.project_id == project_id:
                continue  # already part of this plan

        lib_file: LibraryFile | None = None
        if item.library_file_id is not None:
            result = await db.execute(LibraryFile.active().where(LibraryFile.id == item.library_file_id))
            lib_file = result.scalar_one_or_none()
        if lib_file is None and item.archive_id is not None:
            lib_file = archive_files.get(item.archive_id)
            if lib_file is None:
                archive = await db.get(PrintArchive, item.archive_id)
                if archive is None:
                    continue
                lib_file, created = await copy_archive_to_library(
                    db, archive, folder_id=folder_id, project_id=project_id, owner_id=owner_id
                )
                archive_files[item.archive_id] = lib_file
                if created:
                    stats.library_files_created += 1
        if lib_file is None:
            continue

        result = await db.execute(
            select(ProjectPlanItem)
            .where(
                ProjectPlanItem.project_id == project_id,
                ProjectPlanItem.library_file_id == lib_file.id,
                ProjectPlanItem.plate_id.is_(None)
                if item.plate_id is None
                else ProjectPlanItem.plate_id == item.plate_id,
            )
            .order_by(ProjectPlanItem.sort_order, ProjectPlanItem.id)
            .limit(1)
        )
        plan_item = result.scalar_one_or_none()
        if plan_item is None:
            plate_info = await read_plate_info(db, lib_file, item.plate_id)
            base = _display_file_name(lib_file)
            plate_name = plate_info.get("name") if plate_info else None
            if item.plate_id:
                name = f"{base} – {plate_name}" if plate_name else f"{base} – Plate {item.plate_id}"
            else:
                name = base
            max_order = await db.execute(
                select(func.max(ProjectPlanItem.sort_order)).where(ProjectPlanItem.project_id == project_id)
            )
            est_time = plate_info.get("print_time_seconds") if plate_info else None
            est_grams = plate_info.get("filament_used_grams") if plate_info else None
            plan_item = ProjectPlanItem(
                project_id=project_id,
                library_file_id=lib_file.id,
                plate_id=item.plate_id,
                name=name[:255],
                quantity=0,
                filaments=filaments_from_slice(plate_info.get("filaments") or []) if plate_info else [],
                est_print_time_seconds=int(est_time) if est_time else None,
                est_filament_grams=float(est_grams) if est_grams else None,
                printer_id=item.printer_id,
                target_model=item.target_model,
                sort_order=(max_order.scalar() or 0) + 1,
            )
            db.add(plan_item)
            await db.flush()
            stats.plan_items_created += 1
        else:
            stats.plan_items_linked += 1

        item.plan_item_id = plan_item.id
        touched_rows[plan_item.id] = plan_item

        # Single-plate archive: let the archive carry the plan row too, so the
        # finished print still counts after the queue history is cleared.
        if item.archive_id is not None and await _archive_queue_item_count(db, item.archive_id) == 1:
            archive = await db.get(PrintArchive, item.archive_id)
            if archive is not None:
                archive.plan_item_id = plan_item.id

    await db.flush()
    for plan_item in touched_rows.values():
        linked = await db.execute(
            select(func.count(PrintQueueItem.id)).where(
                PrintQueueItem.plan_item_id == plan_item.id,
                PrintQueueItem.status.in_(("pending", "printing", "completed")),
            )
        )
        plan_item.quantity = max(plan_item.quantity or 0, int(linked.scalar() or 0), 1)
    return stats
