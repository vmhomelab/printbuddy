"""WebSocket /api/v1/ws must authenticate when auth is enabled.

The HTTP auth middleware does not run for WebSocket handshakes, so the endpoint
checks credentials itself. httpx's ASGI transport cannot speak WebSocket, so
these tests drive the endpoint with a small fake socket.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.api.routes.websocket import websocket_endpoint
from backend.app.core.auth import WS_SUBPROTOCOL, create_access_token, generate_api_key
from backend.app.core.websocket import ConnectionManager, message_printer_id


class FakeWebSocket:
    """Just enough of starlette's WebSocket for the endpoint."""

    def __init__(self, headers: dict[str, str] | None = None, subprotocols: list[str] | None = None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.scope: dict[str, Any] = {"subprotocols": subprotocols or []}
        self.accepted_subprotocol: str | None = None
        self.accepted = False
        self.closed_code: int | None = None
        self.sent: list[dict[str, Any]] = []

    async def accept(self, subprotocol: str | None = None):
        self.accepted = True
        self.accepted_subprotocol = subprotocol

    async def close(self, code: int = 1000):
        self.closed_code = code

    async def send_json(self, data: dict[str, Any]):
        self.sent.append(data)

    async def send_text(self, data: str):
        import json

        self.sent.append(json.loads(data))

    async def receive_json(self):
        raise WebSocketDisconnect(code=1000)


def _state(printer_id: int):
    return MagicMock(name=f"state{printer_id}")


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def run(session_factory):
    """Run the endpoint against the test DB with two fake printers (ids 1 and 2)."""

    async def _run(ws: FakeWebSocket) -> FakeWebSocket:
        manager = ConnectionManager()
        pm = MagicMock()
        pm.get_all_statuses.return_value = {1: _state(1), 2: _state(2)}
        pm.get_model.return_value = "X1C"
        dispatch = MagicMock()
        dispatch.get_state = AsyncMock(return_value={"dispatched": 0, "processing": 0})
        with (
            patch("backend.app.core.database.async_session", session_factory),
            patch("backend.app.core.auth.async_session", session_factory),
            patch("backend.app.api.routes.websocket.ws_manager", manager),
            patch("backend.app.api.routes.websocket.printer_manager", pm),
            patch("backend.app.api.routes.websocket.background_dispatch", dispatch),
            patch(
                "backend.app.api.routes.websocket.printer_state_to_dict",
                lambda state, pid, model: {"connected": True, "id": pid},
            ),
        ):
            await websocket_endpoint(ws)
        return ws

    return _run


@pytest.fixture
async def auth_on(db_session):
    from backend.app.models.settings import Settings

    db_session.add(Settings(key="auth_enabled", value="true"))
    await db_session.commit()


@pytest.fixture
async def admin_token(db_session):
    from backend.app.core.auth import get_password_hash
    from backend.app.models.user import User

    db_session.add(User(username="admin", password_hash=get_password_hash("pw-123456"), role="admin", is_active=True))
    await db_session.commit()
    return create_access_token({"sub": "admin"})


async def _api_key(db_session, **scopes) -> str:
    from backend.app.models.api_key import APIKey

    full_key, key_hash, key_prefix = generate_api_key()
    db_session.add(
        APIKey(name="ws", key_hash=key_hash, key_prefix=key_prefix, enabled=True, **{"can_read_status": True, **scopes})
    )
    await db_session.commit()
    return full_key


def _printer_ids(ws: FakeWebSocket) -> list[int]:
    return sorted(m["printer_id"] for m in ws.sent if m.get("type") == "printer_status")


@pytest.mark.asyncio
@pytest.mark.integration
class TestWebSocketAuth:
    async def test_auth_disabled_allows_anonymous(self, run):
        ws = await run(FakeWebSocket())
        assert ws.accepted
        assert _printer_ids(ws) == [1, 2]

    async def test_auth_enabled_rejects_missing_credentials(self, run, auth_on):
        ws = await run(FakeWebSocket())
        assert not ws.accepted
        assert ws.closed_code == 1008
        assert ws.sent == []

    async def test_auth_enabled_rejects_garbage_token(self, run, auth_on):
        ws = await run(FakeWebSocket(subprotocols=[WS_SUBPROTOCOL, "bearer.not-a-jwt"]))
        assert not ws.accepted
        assert ws.sent == []

    async def test_auth_enabled_rejects_invalid_api_key(self, run, auth_on):
        ws = await run(FakeWebSocket(headers={"X-API-Key": "bb_doesnotexist"}))
        assert not ws.accepted

    async def test_jwt_in_subprotocol_is_accepted_and_not_echoed(self, run, auth_on, admin_token):
        ws = await run(FakeWebSocket(subprotocols=[WS_SUBPROTOCOL, f"bearer.{admin_token}"]))
        assert ws.accepted
        assert ws.accepted_subprotocol == WS_SUBPROTOCOL  # never the token
        assert _printer_ids(ws) == [1, 2]

    async def test_jwt_in_authorization_header(self, run, auth_on, admin_token):
        ws = await run(FakeWebSocket(headers={"Authorization": f"Bearer {admin_token}"}))
        assert ws.accepted
        assert ws.accepted_subprotocol is None

    async def test_user_without_printers_read_is_rejected(self, run, auth_on, db_session):
        from backend.app.core.auth import get_password_hash
        from backend.app.models.user import User

        db_session.add(
            User(username="nobody", password_hash=get_password_hash("pw-123456"), role="user", is_active=True)
        )
        await db_session.commit()
        token = create_access_token({"sub": "nobody"})
        ws = await run(FakeWebSocket(headers={"Authorization": f"Bearer {token}"}))
        assert not ws.accepted

    async def test_inactive_user_is_rejected(self, run, auth_on, db_session, admin_token):
        from sqlalchemy import update

        from backend.app.models.user import User

        await db_session.execute(update(User).where(User.username == "admin").values(is_active=False))
        await db_session.commit()
        ws = await run(FakeWebSocket(headers={"Authorization": f"Bearer {admin_token}"}))
        assert not ws.accepted

    async def test_api_key_header_is_accepted(self, run, auth_on, db_session):
        key = await _api_key(db_session)
        ws = await run(FakeWebSocket(headers={"X-API-Key": key}))
        assert ws.accepted
        assert _printer_ids(ws) == [1, 2]

    async def test_api_key_without_read_status_is_rejected(self, run, auth_on, db_session):
        key = await _api_key(db_session, can_read_status=False)
        ws = await run(FakeWebSocket(headers={"X-API-Key": key}))
        assert not ws.accepted

    async def test_api_key_scoped_to_printers_only_sees_those(self, run, auth_on, db_session):
        key = await _api_key(db_session, printer_ids=[2])
        ws = await run(FakeWebSocket(subprotocols=[WS_SUBPROTOCOL, f"bearer.{key}"]))
        assert ws.accepted
        assert _printer_ids(ws) == [2]


class TestConnectionManagerFilter:
    @pytest.mark.asyncio
    async def test_broadcast_respects_printer_filter(self):
        manager = ConnectionManager()
        everything, scoped = FakeWebSocket(), FakeWebSocket()
        await manager.connect(everything)
        await manager.connect(scoped, printer_ids=frozenset({2}))

        await manager.send_printer_status(1, {"x": 1})
        await manager.send_printer_status(2, {"x": 2})
        await manager.broadcast({"type": "archive_created", "data": {"printer_id": 1}})
        await manager.broadcast({"type": "inventory_changed"})

        assert [m.get("printer_id") or m.get("data", {}).get("printer_id") for m in everything.sent] == [1, 2, 1, None]
        assert [m["type"] for m in scoped.sent] == ["printer_status", "inventory_changed"]
        assert scoped.sent[0]["printer_id"] == 2

    @pytest.mark.asyncio
    async def test_disconnect_drops_filter(self):
        manager = ConnectionManager()
        ws = FakeWebSocket()
        await manager.connect(ws, printer_ids=frozenset({1}))
        await manager.disconnect(ws)
        assert ws not in manager._printer_filters

    def test_message_printer_id(self):
        assert message_printer_id({"printer_id": 3}) == 3
        assert message_printer_id({"data": {"printer_id": "4"}}) == 4
        assert message_printer_id({"type": "x"}) is None
        assert message_printer_id({"printer_id": "abc"}) is None
