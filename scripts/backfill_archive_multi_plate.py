#!/usr/bin/env python3
"""Recompute time / weight / cost / quantity of archives made from multi-plate 3MFs.

Older versions of the 3MF parser only read the FIRST ``<plate>`` block of
``slice_info.config``. Archives of multi-plate projects therefore show the
print time, filament weight, cost and part count of plate 1 only — both for
projects archived as a whole and for prints of a later plate.

This script re-parses every archived 3MF that contains more than one plate:

* Printed archives (MQTT recorded which plate ran) get that plate's values.
* Archives without a known plate (manual archive / upload) get the totals
  over all plates.

Safety rules:

* ``cost`` is only recomputed when the archive has no spool usage history —
  spool-tracked costs come from real consumption and are left alone.
* ``quantity`` is only updated when it still equals the old auto-detected
  value (objects on plate 1), so manual edits survive.

Usage:
    # From the printbuddy directory:
    python scripts/backfill_archive_multi_plate.py

    # Or via docker:
    docker exec -it printbuddy python scripts/backfill_archive_multi_plate.py

    # Preview without writing:
    python scripts/backfill_archive_multi_plate.py --dry-run
"""

import argparse
import asyncio
import os
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_dotenv() -> Path | None:
    """Populate os.environ from project-root .env (before importing backend.app,
    whose config reads DATABASE_URL at import time)."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return None
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env_file


_loaded_env = _load_dotenv()

from defusedxml import ElementTree as ET  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.core.database import async_session, init_db  # noqa: E402
from backend.app.models.archive import PrintArchive  # noqa: E402
from backend.app.models.spool_usage_history import SpoolUsageHistory  # noqa: E402
from backend.app.services.archive import (  # noqa: E402
    ThreeMFParser,
    estimate_filament_cost,
    load_filament_cost_catalog,
    parse_slice_info_plates,
    plate_number_from_print_data,
)

# extra_data keys refreshed from the new parse
_EXTRA_KEYS = ("filament_slots", "printable_objects", "plates", "plate_count")


def _describe_db() -> str:
    """Redact credentials from a DATABASE_URL for safe display."""
    url = settings.database_url
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        creds, host = rest.split("@", 1)
        return f"{scheme}://{creds.split(':', 1)[0]}:***@{host}"
    return url


def read_plates(file_path: Path) -> dict[int, dict]:
    """All plates from the 3MF's slice_info.config ({} when unreadable)."""
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "Metadata/slice_info.config" not in zf.namelist():
                return {}
            return parse_slice_info_plates(ET.fromstring(zf.read("Metadata/slice_info.config").decode()))
    except Exception:
        return {}


def _fmt(value) -> str:
    return "-" if value is None else str(value)


async def backfill(dry_run: bool = False):
    print("=" * 60)
    print("Archive multi-plate backfill")
    print("=" * 60)
    print(f"Database: {_describe_db()}")
    print(f".env loaded: {_loaded_env}" if _loaded_env else ".env: not found (using shell env only)")
    print()
    if dry_run:
        print("DRY RUN MODE - No changes will be written")
        print()

    await init_db()

    async with async_session() as db:
        catalog, default_cost_per_kg = await load_filament_cost_catalog(db)
        tracked_result = await db.execute(
            select(SpoolUsageHistory.archive_id)
            .where(SpoolUsageHistory.archive_id.is_not(None))
            .group_by(SpoolUsageHistory.archive_id)
            .having(func.sum(SpoolUsageHistory.cost) > 0)
        )
        spool_tracked = {row[0] for row in tracked_result}

        result = await db.execute(select(PrintArchive).where(PrintArchive.file_path.is_not(None)))
        archives = result.scalars().all()

        scanned = updated = skipped_missing = 0
        for archive in archives:
            if not archive.file_path.lower().endswith(".3mf"):
                continue
            file_path = settings.base_dir / archive.file_path
            if not file_path.is_file():
                skipped_missing += 1
                continue
            scanned += 1

            plates = read_plates(file_path)
            if len(plates) < 2:
                continue

            extra = dict(archive.extra_data) if isinstance(archive.extra_data, dict) else {}
            print_data = extra.get("_print_data")
            plate_number = plate_number_from_print_data(print_data if isinstance(print_data, dict) else None)
            metadata = ThreeMFParser(file_path, plate_number=plate_number).parse()

            changes: dict[str, tuple] = {}

            def change(field: str, new, archive=archive, changes=changes):
                old = getattr(archive, field)
                if new is not None and new != old:
                    changes[field] = (old, new)

            change("print_time_seconds", metadata.get("print_time_seconds"))
            change("filament_used_grams", metadata.get("filament_used_grams"))
            change("filament_type", metadata.get("filament_type"))
            change("filament_color", metadata.get("filament_color"))

            # Quantity: only if it is still the old auto-detected value
            first_plate = plates[min(plates)]
            old_auto_quantity = len(first_plate["printable_objects"]) or 1
            new_objects = metadata.get("printable_objects") or {}
            if new_objects and archive.quantity == old_auto_quantity:
                change("quantity", len(new_objects))

            # Cost: only catalog-based estimates are recomputed
            if archive.id not in spool_tracked:
                change(
                    "cost",
                    estimate_filament_cost(
                        metadata.get("filament_used_grams") or archive.filament_used_grams,
                        metadata.get("filament_type") or archive.filament_type,
                        metadata.get("filament_slots"),
                        catalog,
                        default_cost_per_kg,
                    ),
                )

            new_extra = dict(extra)
            for key in _EXTRA_KEYS:
                if key in metadata:
                    new_extra[key] = metadata[key]
            # JSON round-trip turns int keys into str; compare like with like
            extra_changed = any(
                key in metadata and str(extra.get(key)) != str(_json_safe(metadata[key])) for key in _EXTRA_KEYS
            )

            if not changes and not extra_changed:
                continue

            scope = f"plate {plate_number}" if plate_number in plates else f"all {len(plates)} plates"
            print(f"  [{archive.id}] {archive.print_name or archive.filename} ({scope})")
            for field, (old, new) in changes.items():
                print(f"      {field}: {_fmt(old)} -> {_fmt(new)}")
            if archive.id in spool_tracked:
                print("      cost: kept (spool-tracked)")

            if not dry_run:
                for field, (_old, new) in changes.items():
                    setattr(archive, field, new)
                archive.extra_data = _json_safe(new_extra)
            updated += 1

        if not dry_run:
            await db.commit()

        print()
        print("-" * 60)
        print(f"Scanned 3MF archives: {scanned}")
        print(f"Updated: {updated}")
        print(f"Skipped (file missing): {skipped_missing}")
        if dry_run and updated:
            print()
            print("Run without --dry-run to apply.")


def _json_safe(value):
    """Mirror how the JSON column stores dicts (string keys)."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def main():
    parser = argparse.ArgumentParser(description="Recompute archives created from multi-plate 3MF files")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()
    asyncio.run(backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
