"""Command line utilities for Printbuddy.

    python -m backend.app.cli spoolman-sync-locations

sets the Spoolman location of every spool assigned to a slot to its printer's
name, keeping the location it had before (see ``spoolman_location_sync``).
Safe to run more than once: spools already at their printer are left alone.
"""

from __future__ import annotations

import argparse
import asyncio
import logging


async def _spoolman_sync_locations() -> int:
    from backend.app.api.routes.settings import get_setting
    from backend.app.core.database import async_session
    from backend.app.services.spoolman import close_spoolman_client, init_spoolman_client
    from backend.app.services.spoolman_location_sync import backfill_spool_locations, is_enabled

    async with async_session() as db:
        if not await is_enabled(db):
            print("Spoolman mode is off, or spoolman_sync_location is disabled: nothing to do.")
            return 1
        url = (await get_setting(db, "spoolman_url") or "").strip()
        if not url:
            print("spoolman_url is not set.")
            return 1
        client = await init_spoolman_client(url)
        try:
            if not await client.health_check():
                print(f"Spoolman at {url} is not reachable.")
                return 1
            written = await backfill_spool_locations(db=db, client=client)
        finally:
            await close_spoolman_client()
    print(f"Updated the location of {written} Spoolman spool(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Printbuddy command line utilities")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "spoolman-sync-locations",
        help="Set each assigned Spoolman spool's location to its printer's name (idempotent)",
    )
    args = parser.parse_args(argv)
    if args.command == "spoolman-sync-locations":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        return asyncio.run(_spoolman_sync_locations())
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
