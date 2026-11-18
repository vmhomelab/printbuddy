"""Selectable reasons for "Report failed print": defaults, custom reasons, icons.

Modelled on the maintenance types: default reasons can be hidden (and restored),
custom reasons can be added, edited and deleted. Reports only store a reason's
``code``, so nothing here ever rewrites existing reports.
"""

import logging
import re
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.models.custom_failure_report import CustomFailureReason, CustomFailureReport

logger = logging.getLogger(__name__)

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

# Upper limit for all reasons together (defaults + custom, hidden included).
MAX_REASONS = 100

# Uploaded icons are scaled down to fit this box and stored as PNG.
ICON_MAX_SIZE = 500
ICON_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
ICON_UPLOAD_MAX_PIXELS = 40_000_000
ICON_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


class ReasonLimitReached(Exception):
    pass


class InvalidIconImage(Exception):
    pass


async def ensure_default_reasons(db: AsyncSession) -> None:
    """Create any missing default reason (first start, or after an upgrade).

    Called once at startup from ``init_db`` (``seed_custom_failure_reasons``).
    """
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
    query = select(CustomFailureReason).order_by(CustomFailureReason.sort_order, CustomFailureReason.id)
    if not include_hidden:
        query = query.where(CustomFailureReason.is_hidden.is_(False))
    return list((await db.execute(query)).scalars().all())


async def get_reason(db: AsyncSession, reason_id: int) -> CustomFailureReason | None:
    return (
        await db.execute(select(CustomFailureReason).where(CustomFailureReason.id == reason_id))
    ).scalar_one_or_none()


async def get_reason_by_code(db: AsyncSession, code: str) -> CustomFailureReason | None:
    return (await db.execute(select(CustomFailureReason).where(CustomFailureReason.code == code))).scalar_one_or_none()


async def create_reason(db: AsyncSession, title: str, subtitle: str | None, icon: str | None) -> CustomFailureReason:
    count = (await db.execute(select(func.count(CustomFailureReason.id)))).scalar_one()
    if count >= MAX_REASONS:
        raise ReasonLimitReached()
    max_order = (await db.execute(select(func.max(CustomFailureReason.sort_order)))).scalar_one() or 0
    reason = CustomFailureReason(
        code=f"custom_{uuid.uuid4().hex[:12]}",
        title=title,
        subtitle=subtitle,
        icon=icon,
        is_system=False,
        sort_order=max_order + 1,
    )
    db.add(reason)
    await db.commit()
    await db.refresh(reason)
    return reason


async def count_reports(db: AsyncSession, code: str) -> int:
    return (
        await db.execute(
            select(func.count(CustomFailureReport.id)).where(CustomFailureReport.custom_failure_reason == code)
        )
    ).scalar_one()


async def remove_reason(db: AsyncSession, reason: CustomFailureReason) -> str:
    """Hide defaults and reasons that already have reports; delete the rest.

    Returns "hidden" or "deleted".
    """
    if reason.is_system or await count_reports(db, reason.code):
        reason.is_hidden = True
        await db.commit()
        return "hidden"
    filename = reason.custom_icon_filename
    reason_id = reason.id
    await db.delete(reason)
    await db.commit()
    remove_icon_file(filename, reason_id)
    return "deleted"


async def restore_defaults(db: AsyncSession) -> int:
    """Show hidden default reasons again (and re-create missing ones). Returns how many were restored."""
    await ensure_default_reasons(db)
    hidden = (
        (
            await db.execute(
                select(CustomFailureReason).where(
                    CustomFailureReason.is_system.is_(True), CustomFailureReason.is_hidden.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    for reason in hidden:
        reason.is_hidden = False
    await db.commit()
    return len(hidden)


async def reorder_reasons(db: AsyncSession, ordered_ids: list[int]) -> None:
    """Apply a new display order; reasons not in the list keep their relative order after them."""
    reasons = await list_reasons(db, include_hidden=True)
    position = {reason_id: index for index, reason_id in enumerate(ordered_ids)}
    reasons.sort(key=lambda r: (position.get(r.id, len(position)), r.sort_order, r.id))
    for index, reason in enumerate(reasons, start=1):
        reason.sort_order = index
    await db.commit()


# ---------- Uploaded icons ----------


def icons_dir() -> Path:
    return Path(settings.archive_dir) / "failure_reason_icons"


def icon_path(filename: str | None, reason_id: int) -> Path | None:
    """Resolve only filenames generated for this reason inside the icon directory."""
    if not filename or not re.fullmatch(rf"reason_{reason_id}_[0-9a-f]{{32}}\.png", filename):
        return None
    directory = icons_dir().resolve()
    path = (directory / filename).resolve()
    return path if path.parent == directory else None


def remove_icon_file(filename: str | None, reason_id: int) -> None:
    path = icon_path(filename, reason_id)
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to remove failure reason icon %s: %s", path, exc)


def save_icon(data: bytes, reason_id: int) -> str:
    """Verify an uploaded image, shrink it to fit 500x500 px and store it as PNG.

    Returns the new filename. Raises InvalidIconImage for anything that isn't a usable image.
    """
    directory = icons_dir()
    directory.mkdir(parents=True, exist_ok=True)
    temp_path = directory / f".upload_{uuid.uuid4().hex}"
    try:
        temp_path.write_bytes(data)
        with Image.open(temp_path) as image:
            image.verify()
        with Image.open(temp_path) as image:
            if image.width * image.height > ICON_UPLOAD_MAX_PIXELS:
                raise InvalidIconImage("Image dimensions are too large")
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA")
            image.thumbnail((ICON_MAX_SIZE, ICON_MAX_SIZE))
            filename = f"reason_{reason_id}_{uuid.uuid4().hex}.png"
            image.save(directory / filename, format="PNG")
        return filename
    except InvalidIconImage:
        raise
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise InvalidIconImage("Uploaded file is not a valid image") from exc
    finally:
        temp_path.unlink(missing_ok=True)
