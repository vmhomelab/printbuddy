"""Regression tests for the webhook printer-status / stop / cancel routes.

Pre-fix the routes treated ``printer_manager.get_status(...)``'s return value
as a dict and called ``.get(...)`` on it. The return is a provider state
object with attributes — for Bambu a ``PrinterState`` dataclass
(``backend/app/services/bambu_mqtt.py``) — so the call raised
``AttributeError`` and surfaced as a generic 500 for any printer that
actually had a status row. See #1584.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.app.services.bambu_mqtt import PrinterState


@dataclass
class DataclassPrinterState:
    connected: bool = True
    state: str = "RUNNING"
    current_print: str | None = "calibration_cube.3mf"
    progress: float | None = 42.5
    remaining_time: int | None = 37
    layer_num: int | None = 12
    total_layers: int | None = 80
    hms_errors: list[dict] | None = None
    subtask_id: str | None = "subtask-123"


@pytest.fixture
async def webhook_api_key(db_session):
    """Create an API key with status/control permissions for webhook routes."""
    from backend.app.core.auth import generate_api_key
    from backend.app.models.api_key import APIKey

    full_key, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        name="webhook-status-test-key",
        key_hash=key_hash,
        key_prefix=key_prefix,
        can_control_printer=True,
        can_read_status=True,
        enabled=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    return full_key


@pytest.fixture
async def webhook_printer(printer_factory):
    return await printer_factory(name="Webhook Status Printer")


class TestWebhookPrinterStateDataclass:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_status_route_reads_dataclass_state_by_attribute(
        self, async_client: AsyncClient, webhook_api_key, webhook_printer
    ):
        """Connected dataclass state should return 200 instead of AttributeError/500."""
        with patch("backend.app.api.routes.webhook.printer_manager") as mock_pm:
            mock_pm.get_status.return_value = DataclassPrinterState(
                hms_errors=[{"code": "0x0300", "attr": 50331648, "severity": 2}]
            )

            resp = await async_client.get(
                f"/api/v1/webhook/printer/{webhook_printer.id}/status",
                headers={"X-API-Key": webhook_api_key},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "id": webhook_printer.id,
            "name": "Webhook Status Printer",
            "connected": True,
            "state": "RUNNING",
            "current_print": "calibration_cube.3mf",
            "progress": 42.5,
            "remaining_time": 37,
            "layer_num": 12,
            "total_layers": 80,
            "hms_errors": [{"code": "0x0300", "attr": 50331648, "severity": 2}],
            "subtask_id": "subtask-123",
            "serial_number": webhook_printer.serial_number,
        }

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_stop_route_reads_dataclass_state_by_attribute(
        self, async_client: AsyncClient, webhook_api_key, webhook_printer
    ):
        """Stop should accept a connected RUNNING dataclass state."""
        with patch("backend.app.api.routes.webhook.printer_manager") as mock_pm:
            mock_pm.get_status.return_value = DataclassPrinterState(state="RUNNING")
            mock_pm.stop_print = AsyncMock()

            resp = await async_client.post(
                f"/api/v1/webhook/printer/{webhook_printer.id}/stop",
                headers={"X-API-Key": webhook_api_key},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": "Print stopped"}
        mock_pm.stop_print.assert_awaited_once_with(webhook_printer.id)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cancel_route_reads_dataclass_state_by_attribute(
        self, async_client: AsyncClient, webhook_api_key, webhook_printer
    ):
        """Cancel should accept a connected PAUSE dataclass state."""
        with patch("backend.app.api.routes.webhook.printer_manager") as mock_pm:
            mock_pm.get_status.return_value = DataclassPrinterState(state="PAUSE")
            mock_pm.cancel_print = AsyncMock()

            resp = await async_client.post(
                f"/api/v1/webhook/printer/{webhook_printer.id}/cancel",
                headers={"X-API-Key": webhook_api_key},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"message": "Print cancelled"}
        mock_pm.cancel_print.assert_awaited_once_with(webhook_printer.id)


@pytest.fixture
async def api_key_data(async_client: AsyncClient, db_session):
    """API key with read_status + control_printer scopes — covers status,
    stop, and cancel in a single fixture."""
    from backend.app.core.auth import generate_api_key
    from backend.app.models.api_key import APIKey

    full_key, key_hash, key_prefix = generate_api_key()
    api_key = APIKey(
        name="webhook-status-test-key",
        key_hash=key_hash,
        key_prefix=key_prefix,
        can_read_status=True,
        can_control_printer=True,
        enabled=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    return full_key


@pytest.fixture
async def printer_row(db_session):
    from backend.app.models.printer import Printer

    printer = Printer(
        name="StatusTest",
        ip_address="192.168.1.44",
        access_code="12345678",
        serial_number="00M00A000000010",
        model="P1S",
    )
    db_session.add(printer)
    await db_session.commit()
    return printer


class TestWebhookGetPrinterStatus:
    """``GET /api/v1/webhook/printer/{id}/status`` — the route reads the
    dataclass via attribute access, not ``.get(...)``. Pre-fix the call
    raised AttributeError → 500 for every printer with a status row.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_200_with_connected_dataclass_status(
        self,
        async_client: AsyncClient,
        api_key_data,
        printer_row,
    ):
        """A live PrinterState dataclass must yield a 200 with the
        attributes mapped into the response — this is the exact regression
        from #1584 where the dataclass crashed the ``.get(...)`` calls."""
        state = PrinterState(
            connected=True,
            state="RUNNING",
            current_print="bench.3mf",
            progress=42.0,
            remaining_time=1234,
        )
        with patch(
            "backend.app.api.routes.webhook.printer_manager.get_status",
            MagicMock(return_value=state),
        ):
            resp = await async_client.get(
                f"/api/v1/webhook/printer/{printer_row.id}/status",
                headers={"X-API-Key": api_key_data},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == printer_row.id
        assert body["name"] == "StatusTest"
        assert body["connected"] is True
        assert body["state"] == "RUNNING"
        assert body["current_print"] == "bench.3mf"
        assert body["progress"] == 42.0
        assert body["remaining_time"] == 1234

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_200_when_status_is_none(
        self,
        async_client: AsyncClient,
        api_key_data,
        printer_row,
    ):
        """A registered printer the manager hasn't seen yet returns None from
        ``get_status``; the response must still be 200 with sensible
        defaults rather than 500."""
        with patch(
            "backend.app.api.routes.webhook.printer_manager.get_status",
            MagicMock(return_value=None),
        ):
            resp = await async_client.get(
                f"/api/v1/webhook/printer/{printer_row.id}/status",
                headers={"X-API-Key": api_key_data},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == printer_row.id
        assert body["connected"] is False
        assert body["state"] is None
        assert body["current_print"] is None
        assert body["progress"] is None
        assert body["remaining_time"] is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_404_when_printer_does_not_exist(
        self,
        async_client: AsyncClient,
        api_key_data,
    ):
        resp = await async_client.get(
            "/api/v1/webhook/printer/99999/status",
            headers={"X-API-Key": api_key_data},
        )
        assert resp.status_code == 404


class TestWebhookStopPrint:
    """``POST /api/v1/webhook/printer/{id}/stop`` — same dataclass-shape
    fix applies to the connection / state precondition checks (#1584)."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_503_when_disconnected(
        self,
        async_client: AsyncClient,
        api_key_data,
        printer_row,
    ):
        state = PrinterState(connected=False, state="unknown")
        with patch(
            "backend.app.api.routes.webhook.printer_manager.get_status",
            MagicMock(return_value=state),
        ):
            resp = await async_client.post(
                f"/api/v1/webhook/printer/{printer_row.id}/stop",
                headers={"X-API-Key": api_key_data},
            )
        # Pre-fix this would have 500'd on `status.get(...)`. Now it
        # cleanly returns the documented 503.
        assert resp.status_code == 503

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_409_when_not_running(
        self,
        async_client: AsyncClient,
        api_key_data,
        printer_row,
    ):
        state = PrinterState(connected=True, state="FINISH")
        with patch(
            "backend.app.api.routes.webhook.printer_manager.get_status",
            MagicMock(return_value=state),
        ):
            resp = await async_client.post(
                f"/api/v1/webhook/printer/{printer_row.id}/stop",
                headers={"X-API-Key": api_key_data},
            )
        assert resp.status_code == 409


class TestWebhookCancelPrint:
    """``POST /api/v1/webhook/printer/{id}/cancel`` — same fix shape."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_503_when_disconnected(
        self,
        async_client: AsyncClient,
        api_key_data,
        printer_row,
    ):
        state = PrinterState(connected=False, state="unknown")
        with patch(
            "backend.app.api.routes.webhook.printer_manager.get_status",
            MagicMock(return_value=state),
        ):
            resp = await async_client.post(
                f"/api/v1/webhook/printer/{printer_row.id}/cancel",
                headers={"X-API-Key": api_key_data},
            )
        assert resp.status_code == 503

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_returns_409_when_not_running_or_paused(
        self,
        async_client: AsyncClient,
        api_key_data,
        printer_row,
    ):
        state = PrinterState(connected=True, state="IDLE")
        with patch(
            "backend.app.api.routes.webhook.printer_manager.get_status",
            MagicMock(return_value=state),
        ):
            resp = await async_client.post(
                f"/api/v1/webhook/printer/{printer_row.id}/cancel",
                headers={"X-API-Key": api_key_data},
            )
        assert resp.status_code == 409
