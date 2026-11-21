import asyncio
import json
from typing import Any

from fastapi import WebSocket


def message_printer_id(message: dict[str, Any]) -> int | None:
    """The printer a broadcast is about: top-level ``printer_id`` or ``data.printer_id``."""
    pid = message.get("printer_id")
    if pid is None and isinstance(message.get("data"), dict):
        pid = message["data"].get("printer_id")
    try:
        return int(pid) if pid is not None else None
    except (TypeError, ValueError):
        return None


class ConnectionManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        # Connections that may only see some printers (API keys scoped with
        # printer_ids). Connections not in this map see everything.
        self._printer_filters: dict[WebSocket, frozenset[int]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        *,
        subprotocol: str | None = None,
        printer_ids: frozenset[int] | None = None,
    ):
        """Accept a new WebSocket connection.

        ``printer_ids`` limits which printers' messages this connection gets;
        None means all printers.
        """
        await websocket.accept(subprotocol=subprotocol)
        async with self._lock:
            self.active_connections.append(websocket)
            if printer_ids is not None:
                self._printer_filters[websocket] = printer_ids

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            self._printer_filters.pop(websocket, None)

    def allows(self, websocket: WebSocket, message: dict[str, Any]) -> bool:
        """Whether a message may go to this connection under its printer filter."""
        allowed = self._printer_filters.get(websocket)
        if allowed is None:
            return True
        printer_id = message_printer_id(message)
        return printer_id is None or printer_id in allowed

    async def broadcast(self, message: dict[str, Any]):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        data = json.dumps(message)
        async with self._lock:
            disconnected = []
            for connection in self.active_connections:
                if not self.allows(connection, message):
                    continue
                try:
                    await connection.send_text(data)
                except Exception:
                    disconnected.append(connection)

            # Clean up disconnected clients
            for conn in disconnected:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)
                self._printer_filters.pop(conn, None)

    async def send_printer_status(self, printer_id: int, status: dict):
        """Send printer status update to all clients."""
        await self.broadcast(
            {
                "type": "printer_status",
                "printer_id": printer_id,
                "data": status,
            }
        )

    async def send_print_start(self, printer_id: int, data: dict):
        """Notify clients that a print has started."""
        await self.broadcast(
            {
                "type": "print_start",
                "printer_id": printer_id,
                "data": data,
            }
        )

    async def send_print_complete(self, printer_id: int, data: dict):
        """Notify clients that a print has completed."""
        await self.broadcast(
            {
                "type": "print_complete",
                "printer_id": printer_id,
                "data": data,
            }
        )

    async def send_archive_created(self, archive: dict):
        """Notify clients that a new archive was created."""
        await self.broadcast(
            {
                "type": "archive_created",
                "data": archive,
            }
        )

    async def send_archive_updated(self, archive: dict):
        """Notify clients that an archive was updated."""
        await self.broadcast(
            {
                "type": "archive_updated",
                "data": archive,
            }
        )

    async def send_missing_spool_assignment(
        self,
        printer_id: int,
        printer_name: str,
        missing_slots: list[dict[str, str]],
    ):
        """Notify clients that a print started with missing spool assignments."""
        await self.broadcast(
            {
                "type": "missing_spool_assignment",
                "printer_id": printer_id,
                "printer_name": printer_name,
                "missing_slots": missing_slots,
            }
        )


# Global connection manager
ws_manager = ConnectionManager()
