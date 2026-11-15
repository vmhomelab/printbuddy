"""Report finished prints of GyroidVault imports back to GyroidVault.

When the GyroidVault integration has "report prints" switched on, every
completed or failed print whose file can be traced back to a GyroidVault import
adds an entry to that model's GyroidVault print history
(``POST /api/models/:id/prints``).

Tracing a print to its GyroidVault model:

1. The printed library file comes from the queue item (``library_file_id``) or,
   for direct prints from the File Manager, from the archive's ``content_hash``
   (the archive is a byte copy of the library file, so it matches
   ``LibraryFile.file_hash``).
2. If that file was sliced inside Printbuddy, ``file_metadata.sliced_from_library_file_id``
   is followed back to the source model (a few hops at most).
3. The first file with ``source_type == "gyroidvault"`` and a source URL that
   points at the *currently configured* instance yields the model id.

Everything here is best effort: it runs as a background task after
``on_print_complete`` and only logs on failure, so GyroidVault being down can
never break print-completion handling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import async_session
from backend.app.models.library import LibraryFile
from backend.app.services.gyroidvault import (
    GyroidVaultClient,
    GyroidVaultError,
    normalize_base_url,
    parse_source_url,
)

logger = logging.getLogger(__name__)

SOURCE_TYPE = "gyroidvault"
REPORTED_FLAG = "gyroidvault_reported_model_id"
_MAX_SLICE_HOPS = 5
_MAX_HASH_CANDIDATES = 20

# Print outcome → GyroidVault ``successful`` flag. Cancelled/aborted prints are
# deliberately not reported: they say nothing about whether the model prints.
_OUTCOMES = {"completed": True, "failed": False}


async def _setting(db: AsyncSession, key: str) -> str:
    from backend.app.api.routes.settings import get_setting

    return await get_setting(db, key) or ""


async def _trace_to_gyroidvault(db: AsyncSession, lib_file: LibraryFile, base_url: str) -> int | None:
    """Follow ``sliced_from_library_file_id`` until a GyroidVault import is found."""
    seen: set[int] = set()
    current: LibraryFile | None = lib_file
    for _ in range(_MAX_SLICE_HOPS + 1):
        if current is None or current.id in seen:
            return None
        seen.add(current.id)
        if current.source_type == SOURCE_TYPE:
            parsed = parse_source_url(current.source_url)
            if parsed and normalize_base_url(parsed[0]) == base_url:
                return parsed[1]
            return None
        parent_id = (current.file_metadata or {}).get("sliced_from_library_file_id")
        if not isinstance(parent_id, int):
            return None
        current = await db.get(LibraryFile, parent_id)
    return None


async def resolve_gyroidvault_model(
    db: AsyncSession,
    *,
    base_url: str,
    library_file_id: int | None,
    content_hash: str | None,
) -> int | None:
    """Return the GyroidVault model id behind a print, or ``None``."""
    base_url = normalize_base_url(base_url)
    if library_file_id is not None:
        lib_file = await db.get(LibraryFile, library_file_id)
        if lib_file is not None:
            return await _trace_to_gyroidvault(db, lib_file, base_url)
    if content_hash:
        result = await db.execute(
            select(LibraryFile)
            .where(LibraryFile.file_hash == content_hash, LibraryFile.deleted_at.is_(None))
            .order_by(LibraryFile.id.desc())
            .limit(_MAX_HASH_CANDIDATES)
        )
        for candidate in result.scalars().all():
            model_id = await _trace_to_gyroidvault(db, candidate, base_url)
            if model_id is not None:
                return model_id
    return None


def _notes(printer_name: str | None, print_name: str | None) -> str:
    parts = ["Printbuddy"]
    if printer_name:
        parts.append(printer_name)
    if print_name:
        parts.append(print_name)
    return " · ".join(parts)


async def report_print_completion(
    *,
    printer_id: int,
    status: str | None,
    archive_id: int | None,
    queue_item_id: int | None,
    printer_name: str | None = None,
) -> int | None:
    """Report one finished print. Returns the GyroidVault model id it was reported to."""
    successful = _OUTCOMES.get(status or "")
    if successful is None:
        return None
    try:
        return await _report(
            printer_id=printer_id,
            successful=successful,
            archive_id=archive_id,
            queue_item_id=queue_item_id,
            printer_name=printer_name,
        )
    except Exception:  # noqa: BLE001 — must never break print-complete handling
        logger.exception("[GYROIDVAULT] Reporting print on printer %s failed", printer_id)
        return None


async def _report(
    *,
    printer_id: int,
    successful: bool,
    archive_id: int | None,
    queue_item_id: int | None,
    printer_name: str | None,
) -> int | None:
    from backend.app.core.encryption import mfa_decrypt
    from backend.app.models.archive import PrintArchive
    from backend.app.models.print_queue import PrintQueueItem

    async with async_session() as db:
        if (await _setting(db, "gyroidvault_enabled")).lower() != "true":
            return None
        if (await _setting(db, "gyroidvault_report_prints")).lower() != "true":
            return None
        base_url = normalize_base_url(await _setting(db, "gyroidvault_url"))
        stored_key = await _setting(db, "gyroidvault_api_key")
        if not base_url or not stored_key:
            return None

        archive = await db.get(PrintArchive, archive_id) if archive_id else None
        if archive is not None and (archive.extra_data or {}).get(REPORTED_FLAG):
            return None  # already reported (e.g. duplicate completion event)

        library_file_id = None
        if queue_item_id is not None:
            item = await db.get(PrintQueueItem, queue_item_id)
            library_file_id = item.library_file_id if item else None

        model_id = await resolve_gyroidvault_model(
            db,
            base_url=base_url,
            library_file_id=library_file_id,
            content_hash=archive.content_hash if archive else None,
        )
        if model_id is None:
            return None

        print_name = archive.print_name if archive else None
        api_key = mfa_decrypt(stored_key)

        async with GyroidVaultClient(base_url, api_key) as client:
            try:
                await client.add_print(
                    model_id,
                    successful=successful,
                    notes=_notes(printer_name, print_name),
                    printed_at=datetime.now(timezone.utc).isoformat(),
                )
            except GyroidVaultError as exc:
                logger.warning(
                    "[GYROIDVAULT] Could not add print to model %s (printer %s): %s", model_id, printer_id, exc
                )
                return None

        if archive is not None:
            archive.extra_data = {**(archive.extra_data or {}), REPORTED_FLAG: model_id}
            await db.commit()
        logger.info(
            "[GYROIDVAULT] Reported %s print on printer %s to model %s",
            "successful" if successful else "failed",
            printer_id,
            model_id,
        )
        return model_id
