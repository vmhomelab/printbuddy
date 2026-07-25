from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.printer import Printer
from backend.app.models.printer_fleet_group import PrinterFleetGroup, PrinterFleetGroupMember
from backend.app.schemas.printer_fleet_group import (
    PrinterFleetGroupCreate,
    PrinterFleetGroupResponse,
    PrinterFleetGroupUpdate,
)

router = APIRouter(prefix="/printer-fleet-groups", tags=["printer-fleet-groups"])


def _to_response(group: PrinterFleetGroup) -> PrinterFleetGroupResponse:
    return PrinterFleetGroupResponse(
        id=group.id,
        name=group.name,
        color=group.color,
        sort_order=group.sort_order,
        printer_ids=[member.printer_id for member in sorted(group.members, key=lambda item: item.printer_id)],
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


async def _validate_printer_ids(db: AsyncSession, printer_ids: list[int]) -> list[int]:
    unique_ids = list(dict.fromkeys(printer_ids))
    if not unique_ids:
        return []
    result = await db.execute(select(Printer.id).where(Printer.id.in_(unique_ids)))
    found = set(result.scalars().all())
    missing = [printer_id for printer_id in unique_ids if printer_id not in found]
    if missing:
        raise HTTPException(400, f"Unknown printer id(s): {', '.join(str(item) for item in missing)}")
    return unique_ids


async def _load_group(db: AsyncSession, group_id: int) -> PrinterFleetGroup:
    result = await db.execute(
        select(PrinterFleetGroup)
        .options(selectinload(PrinterFleetGroup.members))
        .where(PrinterFleetGroup.id == group_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(404, "Printer fleet group not found")
    return group


@router.get("/", response_model=list[PrinterFleetGroupResponse])
async def list_printer_fleet_groups(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PrinterFleetGroup)
        .options(selectinload(PrinterFleetGroup.members))
        .order_by(PrinterFleetGroup.sort_order, PrinterFleetGroup.name)
    )
    return [_to_response(group) for group in result.scalars().all()]


@router.post("/", response_model=PrinterFleetGroupResponse)
async def create_printer_fleet_group(
    data: PrinterFleetGroupCreate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    printer_ids = await _validate_printer_ids(db, data.printer_ids)
    group = PrinterFleetGroup(name=data.name.strip(), color=data.color, sort_order=data.sort_order)
    group.members = [PrinterFleetGroupMember(printer_id=printer_id) for printer_id in printer_ids]
    db.add(group)
    await db.commit()
    group = await _load_group(db, group.id)
    return _to_response(group)


@router.put("/{group_id}", response_model=PrinterFleetGroupResponse)
async def update_printer_fleet_group(
    group_id: int,
    data: PrinterFleetGroupUpdate,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    group = await _load_group(db, group_id)
    printer_ids = await _validate_printer_ids(db, data.printer_ids)
    group.name = data.name.strip()
    group.color = data.color
    group.sort_order = data.sort_order
    await db.execute(delete(PrinterFleetGroupMember).where(PrinterFleetGroupMember.group_id == group.id))
    group.members = [PrinterFleetGroupMember(group_id=group.id, printer_id=printer_id) for printer_id in printer_ids]
    await db.commit()
    group = await _load_group(db, group.id)
    return _to_response(group)


@router.delete("/{group_id}", status_code=204)
async def delete_printer_fleet_group(
    group_id: int,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    group = await _load_group(db, group_id)
    await db.delete(group)
    await db.commit()
    return Response(status_code=204)
