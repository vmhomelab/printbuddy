"""Command line utilities for Printbuddy.

    python -m backend.app.cli spoolman-sync-locations

sets the Spoolman location of every spool assigned to a slot to its printer's
name and its slot field to "<printer> · <slot>", keeping the location it had
before (see ``spoolman_location_sync``).

    python -m backend.app.cli spoolman-migrate-fields

moves spools off the old ``bambu_*`` extra keys to the ``printbuddy_*`` ones and
deletes the old field definitions (see ``spoolman_extra_keys``); Printbuddy
also does this on every start.

Both are safe to run more than once.
"""

from __future__ import annotations

import argparse
import asyncio
import logging


async def _with_spoolman(action, *, need_location_sync: bool) -> int:
    from backend.app.api.routes.settings import get_setting
    from backend.app.core.database import async_session
    from backend.app.services.inventory_mode import spoolman_owns_assignments
    from backend.app.services.spoolman import close_spoolman_client, init_spoolman_client
    from backend.app.services.spoolman_location_sync import is_enabled

    async with async_session() as db:
        if need_location_sync and not await is_enabled(db):
            print("Spoolman mode is off, or spoolman_sync_location is disabled: nothing to do.")
            return 1
        if not need_location_sync and not await spoolman_owns_assignments(db):
            print("Spoolman mode is off: nothing to do.")
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
            await action(db, client)
        finally:
            await close_spoolman_client()
    return 0


async def _spoolman_sync_locations() -> int:
    from backend.app.services.spoolman_location_sync import backfill_spool_locations

    async def action(db, client) -> None:
        written = await backfill_spool_locations(db=db, client=client)
        print(f"Updated the location of {written} Spoolman spool(s).")

    return await _with_spoolman(action, need_location_sync=True)


async def _spoolman_migrate_fields() -> int:
    from backend.app.services.spoolman_extra_keys import migrate_legacy_extra_fields

    result: dict = {}

    async def action(db, client) -> None:
        result.update(await migrate_legacy_extra_fields(client))
        print(
            f"Moved {result['spools_moved']} spool(s), {result['spools_failed']} failed, "
            f"deleted {result['fields_deleted']} old field(s), named {result['fields_named']} field(s)."
        )

    code = await _with_spoolman(action, need_location_sync=False)
    return 1 if code or result.get("spools_failed") else 0


COMMANDS = {
    "spoolman-sync-locations": (
        _spoolman_sync_locations,
        "Set each assigned Spoolman spool's location and slot field from its printer (idempotent)",
    ),
    "spoolman-migrate-fields": (
        _spoolman_migrate_fields,
        "Move Spoolman spools from the old bambu_* extra keys to printbuddy_* (idempotent)",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Printbuddy command line utilities")
    commands = parser.add_subparsers(dest="command")
    for name, (_, help_text) in COMMANDS.items():
        commands.add_parser(name, help=help_text)
    args = parser.parse_args(argv)
    if args.command in COMMANDS:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        # Load the database module before any service: it imports the models in
        # the order they need. A service imported first (e.g. location sync ->
        # models.printer) hits a circular import when run from the command line.
        import backend.app.core.database  # noqa: F401

        return asyncio.run(COMMANDS[args.command][0]())
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
