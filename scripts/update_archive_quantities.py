#!/usr/bin/env python3
"""Update archive quantities from 3MF files.

This script updates the quantity field on existing archives by parsing
their 3MF files to count the number of printable objects.

Run this once after upgrading to add proper parts tracking to your projects.

Usage:
    # From the printbuddy directory:
    python scripts/update_archive_quantities.py

    # Or with docker:
    docker exec -it printbuddy python scripts/update_archive_quantities.py

    # Dry run (show what would be updated without changing anything):
    python scripts/update_archive_quantities.py --dry-run
"""

import argparse
import asyncio
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.core.database import async_session
from backend.app.models.archive import PrintArchive


def extract_object_count_from_3mf(file_path: Path) -> int | None:
    """Extract the number of printable objects from a 3MF file.

    Returns the count of non-skipped objects, or None if parsing fails.
    """
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "Metadata/slice_info.config" not in zf.namelist():
                return None

            content = zf.read("Metadata/slice_info.config").decode()
            root = ET.fromstring(content)

            # Find the plate (use first plate)
            plate = root.find(".//plate")
            if plate is None:
                return None

            # Count non-skipped objects
            count = 0
            for obj in plate.findall("object"):
                skipped = obj.get("skipped", "false")
                if skipped.lower() != "true":
                    count += 1

            return count if count > 0 else None

    except Exception as e:
        print(f"  Error parsing {file_path.name}: {e}")
        return None


async def update_archive_quantities(dry_run: bool = False):
    """Update quantity field on archives based on 3MF object count."""

    print("=" * 60)
    print("Archive Quantity Updater")
    print("=" * 60)
    print()

    if dry_run:
        print("DRY RUN MODE - No changes will be made")
        print()

    async with async_session() as db:
        # Get all archives with quantity=1 (the default)
        result = await db.execute(select(PrintArchive).where(PrintArchive.quantity == 1))
        archives = result.scalars().all()

        print(f"Found {len(archives)} archives with quantity=1")
        print()

        updated = 0
        skipped = 0
        errors = 0

        for archive in archives:
            # Skip if no file path
            if not archive.file_path:
                skipped += 1
                continue

            file_path = settings.base_dir / archive.file_path

            # Skip if file doesn't exist
            if not file_path.exists():
                print(f"  [{archive.id}] File not found: {archive.file_path}")
                skipped += 1
                continue

            # Extract object count
            object_count = extract_object_count_from_3mf(file_path)

            if object_count is None:
                skipped += 1
                continue

            if object_count == 1:
                # No change needed
                skipped += 1
                continue

            # Update the archive
            print(f"  [{archive.id}] {archive.print_name}: 1 -> {object_count} parts")

            if not dry_run:
                archive.quantity = object_count
                updated += 1
            else:
                updated += 1

        if not dry_run:
            await db.commit()

        print()
        print("-" * 60)
        print(f"Updated: {updated}")
        print(f"Skipped: {skipped} (no change needed or file not found)")
        print(f"Errors:  {errors}")
        print()

        if dry_run and updated > 0:
            print("Run without --dry-run to apply these changes.")


def main():
    parser = argparse.ArgumentParser(description="Update archive quantities from 3MF files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    args = parser.parse_args()

    asyncio.run(update_archive_quantities(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
