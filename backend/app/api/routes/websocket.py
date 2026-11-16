import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from backend.app.core import database
from backend.app.core.auth import (
    WS_SUBPROTOCOL,
    authenticate_websocket_credential,
    is_auth_enabled,
    websocket_credential,
)
from backend.app.core.websocket import ws_manager
from backend.app.services.background_dispatch import background_dispatch
from backend.app.services.printer_manager import printer_manager, printer_state_to_dict

logger = logging.getLogger(__name__)
router = APIRouter()


async def _auth_enabled() -> bool:
    # Looked up through the module so tests can swap the session factory.
    async with database.async_session() as db:
        return await is_auth_enabled(db)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates.

    The HTTP auth middleware does not run for WebSockets, so this endpoint
    authenticates the handshake itself when auth is enabled. Credentials:
    ``Authorization: Bearer``/``X-API-Key`` headers, or (for browsers) the
    subprotocol ``bearer.<token>`` next to ``printbuddy.v1``.
    """
    offered: list[str] = list(websocket.scope.get("subprotocols") or [])
    subprotocol = WS_SUBPROTOCOL if WS_SUBPROTOCOL in offered else None

    printer_ids: frozenset[int] | None = None
    if await _auth_enabled():
        principal = await authenticate_websocket_credential(websocket_credential(websocket.headers, offered))
        if principal is None:
            logger.info("WebSocket connection rejected: missing or invalid credentials")
            # Closing before accept() rejects the handshake (HTTP 403).
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        printer_ids = principal.printer_ids

    await ws_manager.connect(websocket, subprotocol=subprotocol, printer_ids=printer_ids)
    logger.info("WebSocket client connected")

    def visible(printer_id: int) -> bool:
        return printer_ids is None or printer_id in printer_ids

    try:
        # Send initial status of the printers this client may see
        statuses = printer_manager.get_all_statuses()
        for printer_id, state in statuses.items():
            if not visible(printer_id):
                continue
            await websocket.send_json(
                {
                    "type": "printer_status",
                    "printer_id": printer_id,
                    "data": printer_state_to_dict(state, printer_id, printer_manager.get_model(printer_id)),
                }
            )

        dispatch_state = await background_dispatch.get_state()
        if printer_ids is None and (dispatch_state.get("dispatched", 0) + dispatch_state.get("processing", 0)) > 0:
            await websocket.send_json(
                {
                    "type": "background_dispatch",
                    "data": dispatch_state,
                }
            )
        logger.info("Sent initial status for %s printers", len(statuses))

        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_json()

            # Handle ping/pong for keepalive
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

            # Handle status request
            elif data.get("type") == "get_status":
                printer_id = data.get("printer_id")
                if printer_id and visible(printer_id):
                    state = printer_manager.get_status(printer_id)
                    if state:
                        await websocket.send_json(
                            {
                                "type": "printer_status",
                                "printer_id": printer_id,
                                "data": printer_state_to_dict(state, printer_id, printer_manager.get_model(printer_id)),
                            }
                        )

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        await ws_manager.disconnect(websocket)
