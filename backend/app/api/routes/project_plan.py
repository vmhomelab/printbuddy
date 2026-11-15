"""Project plan ("Job") endpoints.

A plan lists every plate a project/job needs. Each row knows its library
file + plate, quantity, material/colour per slot and printer assignment.
``POST /projects/{id}/plan/enqueue`` turns the open copies into queue items.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.library import is_sliced_file
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.library import LibraryFile
from backend.app.models.printer import Printer
from backend.app.models.project import Project
from backend.app.models.project_plan import ProjectPlanItem
from backend.app.models.user import User
from backend.app.schemas.print_queue import PrintQueueItemCreate
from backend.app.schemas.project import (
    PlanEnqueueRequest,
    PlanEnqueueResponse,
    PlanEnqueueResult,
    PlanFilament,
    PlanItemCreate,
    PlanItemProgress,
    PlanItemResponse,
    PlanItemUpdate,
    PlanReorder,
    PlanSummary,
)
from backend.app.services.project_plan import (
    PlanProgress,
    compute_plan_progress,
    detach_plan_items,
    filament_overrides_for,
    filaments_from_slice,
    load_plan,
    normalize_color,
    read_plate_info,
    summarize_plan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def _display_file_name(lib_file: LibraryFile) -> str:
    name = lib_file.filename
    for suffix in (".gcode.3mf", ".3mf", ".gcode", ".bgcode", ".stl"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def _clean_filaments(filaments: list[PlanFilament] | None) -> list[dict] | None:
    if filaments is None:
        return None
    out = []
    for f in filaments:
        entry = f.model_dump()
        entry["color"] = normalize_color(entry.get("color"))
        if entry.get("original_color"):
            entry["original_color"] = normalize_color(entry["original_color"])
        entry["type"] = (entry.get("type") or "").strip()
        out.append(entry)
    return out


async def _get_project(db: AsyncSession, project_id: int) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_plan_item(db: AsyncSession, project_id: int, item_id: int) -> ProjectPlanItem:
    result = await db.execute(
        select(ProjectPlanItem).where(ProjectPlanItem.id == item_id, ProjectPlanItem.project_id == project_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Plan item not found")
    return item


async def _validate_assignment(db: AsyncSession, printer_id: int | None, target_model: str | None) -> None:
    if printer_id and target_model:
        raise HTTPException(status_code=400, detail="Cannot specify both printer_id and target_model")
    if printer_id:
        result = await db.execute(select(Printer.id).where(Printer.id == printer_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Printer not found")


async def _build_responses(
    db: AsyncSession, items: list[ProjectPlanItem], progress: dict[int, PlanProgress] | None = None
) -> list[PlanItemResponse]:
    if progress is None:
        progress = await compute_plan_progress(db, items)

    file_ids = {i.library_file_id for i in items if i.library_file_id}
    files: dict[int, LibraryFile] = {}
    if file_ids:
        result = await db.execute(LibraryFile.active().where(LibraryFile.id.in_(file_ids)))
        files = {f.id: f for f in result.scalars().all()}

    printer_ids = {i.printer_id for i in items if i.printer_id}
    printer_names: dict[int, str] = {}
    if printer_ids:
        result = await db.execute(select(Printer.id, Printer.name).where(Printer.id.in_(printer_ids)))
        printer_names = dict(result.all())

    responses = []
    for item in items:
        lib_file = files.get(item.library_file_id) if item.library_file_id else None
        thumbnail_url = None
        if lib_file:
            if item.plate_id:
                thumbnail_url = f"/api/v1/library/files/{lib_file.id}/plate-thumbnail/{item.plate_id}"
            elif lib_file.thumbnail_path:
                thumbnail_url = f"/api/v1/library/files/{lib_file.id}/thumbnail"
        prog = progress.get(item.id) or PlanProgress(quantity=item.quantity)
        responses.append(
            PlanItemResponse(
                id=item.id,
                project_id=item.project_id,
                library_file_id=item.library_file_id,
                library_file_name=lib_file.filename if lib_file else None,
                library_file_missing=bool(item.library_file_id) and lib_file is None,
                is_sliced=bool(lib_file and is_sliced_file(lib_file.filename)),
                thumbnail_url=thumbnail_url,
                plate_id=item.plate_id,
                name=item.name,
                group_label=item.group_label,
                quantity=item.quantity,
                filaments=[PlanFilament(**f) for f in (item.filaments or []) if isinstance(f, dict)],
                est_print_time_seconds=item.est_print_time_seconds,
                est_filament_grams=item.est_filament_grams,
                printer_id=item.printer_id,
                printer_name=printer_names.get(item.printer_id) if item.printer_id else None,
                target_model=item.target_model,
                notes=item.notes,
                sort_order=item.sort_order,
                progress=PlanItemProgress(**prog.as_dict()),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
    return responses


@router.get("/{project_id}/plan", response_model=list[PlanItemResponse])
async def list_plan_items(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PROJECTS_READ),
):
    """List the plates planned for a project, with progress per row."""
    await _get_project(db, project_id)
    overview = await load_plan(db, project_id)
    return await _build_responses(db, overview.items, overview.progress)


@router.get("/{project_id}/plan/summary", response_model=PlanSummary)
async def get_plan_summary(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PROJECTS_READ),
):
    """Running totals for the job: plates, print time, filament per material + colour."""
    await _get_project(db, project_id)
    overview = await load_plan(db, project_id)
    return PlanSummary(**summarize_plan(overview))


@router.post("/{project_id}/plan", response_model=PlanItemResponse)
async def create_plan_item(
    project_id: int,
    data: PlanItemCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PROJECTS_UPDATE),
):
    """Add a plate to the job plan.

    Filaments and estimates are read from the file's slice data unless they
    are given explicitly.
    """
    await _get_project(db, project_id)
    await _validate_assignment(db, data.printer_id, data.target_model)

    lib_file = None
    if data.library_file_id is not None:
        result = await db.execute(LibraryFile.active().where(LibraryFile.id == data.library_file_id))
        lib_file = result.scalar_one_or_none()
        if not lib_file:
            raise HTTPException(status_code=400, detail="Library file not found")
    elif not data.name:
        raise HTTPException(status_code=400, detail="Either library_file_id or name is required")

    plate_info = await read_plate_info(db, lib_file, data.plate_id) if lib_file else None

    filaments = _clean_filaments(data.filaments)
    if filaments is None:
        filaments = filaments_from_slice(plate_info.get("filaments") or []) if plate_info else []

    est_time = data.est_print_time_seconds
    if est_time is None and plate_info:
        est_time = plate_info.get("print_time_seconds")
    est_grams = data.est_filament_grams
    if est_grams is None and plate_info:
        est_grams = plate_info.get("filament_used_grams")

    name = (data.name or "").strip()
    if not name and lib_file:
        base = _display_file_name(lib_file)
        plate_name = plate_info.get("name") if plate_info else None
        if data.plate_id:
            name = f"{base} – {plate_name}" if plate_name else f"{base} – Plate {data.plate_id}"
        else:
            name = base

    max_order = await db.execute(
        select(func.max(ProjectPlanItem.sort_order)).where(ProjectPlanItem.project_id == project_id)
    )
    item = ProjectPlanItem(
        project_id=project_id,
        library_file_id=lib_file.id if lib_file else None,
        plate_id=data.plate_id,
        name=name[:255],
        group_label=(data.group_label or "").strip() or None,
        quantity=data.quantity,
        filaments=filaments,
        est_print_time_seconds=int(est_time) if est_time else None,
        est_filament_grams=float(est_grams) if est_grams else None,
        printer_id=data.printer_id or None,
        target_model=(data.target_model or "").strip() or None,
        notes=data.notes,
        sort_order=(max_order.scalar() or 0) + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return (await _build_responses(db, [item]))[0]


@router.patch("/{project_id}/plan/{item_id}", response_model=PlanItemResponse)
async def update_plan_item(
    project_id: int,
    item_id: int,
    data: PlanItemUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PROJECTS_UPDATE),
):
    """Update quantity, material/colour, printer assignment, ... of a plan row."""
    item = await _get_plan_item(db, project_id, item_id)
    fields = data.model_fields_set

    if "plate_id" in fields and data.plate_id != item.plate_id:
        item.plate_id = data.plate_id
        # Different plate → refresh slice data unless the caller sends it too
        if item.library_file_id:
            result = await db.execute(LibraryFile.active().where(LibraryFile.id == item.library_file_id))
            lib_file = result.scalar_one_or_none()
            if lib_file:
                info = await read_plate_info(db, lib_file, item.plate_id)
                if "filaments" not in fields:
                    item.filaments = filaments_from_slice(info.get("filaments") or []) if info else []
                if "est_print_time_seconds" not in fields:
                    item.est_print_time_seconds = (info or {}).get("print_time_seconds")
                if "est_filament_grams" not in fields:
                    item.est_filament_grams = (info or {}).get("filament_used_grams")

    if data.name is not None and data.name.strip():
        item.name = data.name.strip()[:255]
    if "group_label" in fields:
        item.group_label = (data.group_label or "").strip() or None
    if data.quantity is not None:
        item.quantity = data.quantity
    if data.filaments is not None:
        item.filaments = _clean_filaments(data.filaments)
    if "est_print_time_seconds" in fields:
        item.est_print_time_seconds = data.est_print_time_seconds
    if "est_filament_grams" in fields:
        item.est_filament_grams = data.est_filament_grams
    if "notes" in fields:
        item.notes = data.notes
    if data.sort_order is not None:
        item.sort_order = data.sort_order

    if "printer_id" in fields or "target_model" in fields:
        printer_id = item.printer_id
        target_model = item.target_model
        if "printer_id" in fields:
            printer_id = data.printer_id or None
            if printer_id:
                target_model = None
        if "target_model" in fields:
            target_model = (data.target_model or "").strip() or None
            if target_model:
                printer_id = None
        await _validate_assignment(db, printer_id, target_model)
        item.printer_id = printer_id
        item.target_model = target_model

    await db.commit()
    await db.refresh(item)
    return (await _build_responses(db, [item]))[0]


@router.delete("/{project_id}/plan/{item_id}")
async def delete_plan_item(
    project_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PROJECTS_UPDATE),
):
    """Remove a plate from the plan. Queue items / archives keep existing."""
    item = await _get_plan_item(db, project_id, item_id)
    await detach_plan_items(db, [item.id])
    await db.delete(item)
    await db.commit()
    return {"message": "Plan item deleted"}


@router.post("/{project_id}/plan/reorder")
async def reorder_plan_items(
    project_id: int,
    data: PlanReorder,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PROJECTS_UPDATE),
):
    await _get_project(db, project_id)
    result = await db.execute(select(ProjectPlanItem).where(ProjectPlanItem.project_id == project_id))
    by_id = {i.id: i for i in result.scalars().all()}
    for index, item_id in enumerate(data.item_ids):
        if item_id in by_id:
            by_id[item_id].sort_order = index + 1
    await db.commit()
    return {"message": "Plan reordered"}


@router.post("/{project_id}/plan/enqueue", response_model=PlanEnqueueResponse)
async def enqueue_plan(
    project_id: int,
    data: PlanEnqueueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.QUEUE_CREATE),
):
    """Add every copy of the plan that is not yet queued/printed to the print queue.

    Rows already fully queued or printed are skipped, so calling this again
    only tops up what is missing (e.g. after raising a quantity or after a
    failed print).
    """
    from backend.app.api.routes.print_queue import add_to_queue

    await _get_project(db, project_id)
    overview = await load_plan(db, project_id)
    selected = overview.items
    if data.item_ids is not None:
        wanted = set(data.item_ids)
        selected = [i for i in overview.items if i.id in wanted]

    # Snapshot everything needed up front: add_to_queue commits, which
    # expires ORM instances.
    jobs = []
    for item in selected:
        prog = overview.progress.get(item.id) or PlanProgress(quantity=item.quantity)
        jobs.append(
            {
                "id": item.id,
                "library_file_id": item.library_file_id,
                "plate_id": item.plate_id,
                "printer_id": item.printer_id,
                "target_model": item.target_model,
                "overrides": filament_overrides_for(item),
                "count": prog.remaining,
            }
        )

    file_ids = {j["library_file_id"] for j in jobs if j["library_file_id"]}
    sliced: dict[int, bool] = {}
    if file_ids:
        result = await db.execute(LibraryFile.active().where(LibraryFile.id.in_(file_ids)))
        sliced = {f.id: is_sliced_file(f.filename) for f in result.scalars().all()}

    response = PlanEnqueueResponse()
    for job in jobs:
        if job["count"] <= 0:
            continue
        if not job["library_file_id"] or job["library_file_id"] not in sliced:
            response.results.append(PlanEnqueueResult(plan_item_id=job["id"], error="file_missing"))
            continue
        if not sliced[job["library_file_id"]]:
            response.results.append(PlanEnqueueResult(plan_item_id=job["id"], error="not_sliced"))
            continue
        try:
            await add_to_queue(
                PrintQueueItemCreate(
                    library_file_id=job["library_file_id"],
                    plate_id=job["plate_id"],
                    printer_id=job["printer_id"],
                    target_model=job["target_model"],
                    filament_overrides=job["overrides"],
                    quantity=job["count"],
                    manual_start=data.manual_start,
                    project_id=project_id,
                    plan_item_id=job["id"],
                ),
                db,
                current_user,
            )
        except HTTPException as e:
            await db.rollback()
            response.results.append(PlanEnqueueResult(plan_item_id=job["id"], error=str(e.detail)))
            continue
        response.results.append(PlanEnqueueResult(plan_item_id=job["id"], queued=job["count"]))
        response.queued_total += job["count"]

    logger.info("Project %s: queued %s plate(s) from plan", project_id, response.queued_total)
    return response
