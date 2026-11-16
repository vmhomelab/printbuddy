"""Action dispatch for Obico failure detection.

Separated from the detection loop so actions can be unit-tested and swapped.
"""

import logging

from sqlalchemy import select

from backend.app.core.database import async_session
from backend.app.models.printer import Printer

logger = logging.getLogger(__name__)


async def execute_action(
    printer_id: int,
    action: str,
    task_name: str,
    score: float,
    *,
    source: str = "Obico",
    detail: str | None = None,
    image_data: bytes | None = None,
) -> None:
    """Run the configured action for a detected print failure.

    action: 'notify' | 'pause' | 'pause_and_off'
    source: detection provider name, used in log lines only.
    detail/image_data: optional notification overrides (default: Obico wording, no image).
    """
    printer_name = await _get_printer_name(printer_id)

    if action in ("pause", "pause_and_off"):
        _pause_print(printer_id, source)

    if action == "pause_and_off":
        await _turn_off_linked_plugs(printer_id, source)

    await _notify(printer_id, printer_name, task_name, score, action, source, detail, image_data)


async def _get_printer_name(printer_id: int) -> str:
    async with async_session() as db:
        result = await db.execute(select(Printer).where(Printer.id == printer_id))
        printer = result.scalar_one_or_none()
    return printer.name if printer else f"Printer {printer_id}"


def _pause_print(printer_id: int, source: str = "Obico") -> None:
    from backend.app.services.printer_manager import printer_manager

    client = printer_manager.get_client(printer_id)
    if not client:
        logger.warning("%s pause: no MQTT client for printer %s", source, printer_id)
        return
    if not client.pause_print():
        logger.warning("%s pause: pause_print() returned False for printer %s", source, printer_id)


async def _turn_off_linked_plugs(printer_id: int, source: str = "Obico") -> None:
    from backend.app.services.smart_plug_manager import smart_plug_manager

    async with async_session() as db:
        plugs = await smart_plug_manager._get_plugs_for_printer(printer_id, db)
        for plug in plugs:
            if not plug.enabled:
                continue
            try:
                service = await smart_plug_manager.get_service_for_plug(plug, db)
                await service.turn_off(plug)
                logger.info("%s action: turned off plug %s for printer %s", source, plug.name, printer_id)
            except Exception as e:
                logger.error("%s action: failed to turn off plug %s: %s", source, plug.name, e)


async def _notify(
    printer_id: int,
    printer_name: str,
    task_name: str,
    score: float,
    action: str,
    source: str = "Obico",
    detail: str | None = None,
    image_data: bytes | None = None,
) -> None:
    from backend.app.services.notification_service import notification_service

    if detail is None:
        detail = (
            f"Possible print failure detected on '{task_name or 'current job'}' "
            f"(confidence {score:.2f}). Action taken: {action}."
        )
    async with async_session() as db:
        try:
            await notification_service.on_printer_error(
                printer_id=printer_id,
                printer_name=printer_name,
                error_type="ai_failure_detection",
                db=db,
                error_detail=detail,
                image_data=image_data,
            )
        except Exception as e:
            logger.error("%s notify failed for printer %s: %s", source, printer_id, e)
