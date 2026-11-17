"""Selectable reasons for "Report failed print": the default reasons.

Reports only store a reason's ``code``; titles and subtitles of the default
reasons come from the frontend translations. The table also holds the fields
used to customise reasons later (own text, icon, hidden).
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.custom_failure_report import CustomFailureReason

# Default reasons: codes stay fixed forever (existing reports point at them).
# Their titles/subtitles are translated in the frontend (customFailure.reasons.<code>).
DEFAULT_REASONS: list[dict] = [
    {"code": "fail_reason_01", "icon": "Ban"},  # clogged nozzle
    {"code": "fail_reason_02", "icon": "Layers"},  # warping
    {"code": "fail_reason_03", "icon": "Move"},  # layer shift
    {"code": "fail_reason_04", "icon": "SlidersHorizontal"},  # slicing error
    {"code": "fail_reason_05", "icon": "PackageX"},  # material run-out
    {"code": "fail_reason_06", "icon": "Wrench"},  # hardware/software fault
    {"code": "fail_reason_07", "icon": "Hand"},  # external interference
    {"code": "fail_reason_08", "icon": "Shuffle"},  # tangled filament
    {"code": "fail_reason_09", "icon": "Sparkles"},  # missing maintenance
    {"code": "fail_reason_10", "icon": "Eye"},  # poor print quality
    {"code": "fail_reason_12", "icon": "Spline"},  # spaghetti / part detached
    {"code": "fail_reason_13", "icon": "Cable"},  # feeding / AMS problem
    {"code": "fail_reason_14", "icon": "Construction"},  # print preparation error
    {"code": "fail_reason_11", "icon": "CircleHelp"},  # other (kept last)
]
# "Other" stays the last default; reasons added in later versions go in front of it.
LAST_DEFAULT_CODE = "fail_reason_11"
DEFAULT_CODES = [r["code"] for r in DEFAULT_REASONS]
# Default reasons store icon=NULL until someone picks one, so changing an icon here
# also reaches installations that already exist.
DEFAULT_ICONS = {r["code"]: r["icon"] for r in DEFAULT_REASONS}


async def ensure_default_reasons(db: AsyncSession) -> None:
    """Create any missing default reason (first start, or after an upgrade)."""
    existing = {reason.code: reason for reason in (await db.execute(select(CustomFailureReason))).scalars().all()}
    missing = [r for r in DEFAULT_REASONS if r["code"] not in existing]
    if not missing:
        return
    if not existing:
        # First start: the list order is the display order.
        for index, definition in enumerate(DEFAULT_REASONS, start=1):
            db.add(CustomFailureReason(code=definition["code"], icon=None, is_system=True, sort_order=index))
    else:
        # Upgrade: new defaults go right before "Other" (or at the end if it's gone),
        # everything from "Other" on moves down. The user's own order stays otherwise.
        last = existing.get(LAST_DEFAULT_CODE)
        if last is not None:
            insert_at = last.sort_order
            for reason in existing.values():
                if reason.sort_order >= insert_at:
                    reason.sort_order += len(missing)
        else:
            insert_at = max(r.sort_order for r in existing.values()) + 1
        for offset, definition in enumerate(missing):
            db.add(
                CustomFailureReason(code=definition["code"], icon=None, is_system=True, sort_order=insert_at + offset)
            )
    try:
        await db.commit()
    except IntegrityError:
        # Another request created them at the same moment.
        await db.rollback()


async def list_reasons(db: AsyncSession, include_hidden: bool = False) -> list[CustomFailureReason]:
    await ensure_default_reasons(db)
    query = select(CustomFailureReason).order_by(CustomFailureReason.sort_order, CustomFailureReason.id)
    if not include_hidden:
        query = query.where(CustomFailureReason.is_hidden.is_(False))
    return list((await db.execute(query)).scalars().all())


async def get_reason_by_code(db: AsyncSession, code: str) -> CustomFailureReason | None:
    await ensure_default_reasons(db)
    return (await db.execute(select(CustomFailureReason).where(CustomFailureReason.code == code))).scalar_one_or_none()
