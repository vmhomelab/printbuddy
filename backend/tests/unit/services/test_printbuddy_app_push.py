"""Push notifications to the Printbuddy mobile app via Expo's push service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.notification_service import NotificationService

TOKEN = "ExponentPushToken[abcdefghij1234567890]"


def _response(status: int = 200, body: object | None = None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = str(body)
    return response


async def _send(response, **kwargs):
    service = NotificationService()
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    with patch.object(service, "_get_client", new_callable=AsyncMock, return_value=client):
        result = await service._send_printbuddy_app({"push_token": TOKEN}, "Print finished", "Benchy is done", **kwargs)
    return result, client


@pytest.mark.asyncio
async def test_sends_expo_message_with_event_and_printer():
    (ok, msg), client = await _send(
        _response(200, {"data": {"status": "ok", "id": "ticket"}}), event_type="print_complete", printer_id=3
    )
    assert ok, msg
    url = client.post.call_args.args[0]
    payload = client.post.call_args.kwargs["json"]
    assert url == "https://exp.host/--/api/v2/push/send"
    assert payload["to"] == TOKEN
    assert payload["title"] == "Print finished"
    assert payload["body"] == "Benchy is done"
    assert payload["channelId"] == "print-events"
    assert payload["data"] == {"event_type": "print_complete", "printer_id": 3}
    assert payload["priority"] == "default"


@pytest.mark.asyncio
async def test_failures_get_high_priority():
    (_, _), client = await _send(_response(200, {"data": {"status": "ok"}}), event_type="print_failed")
    assert client.post.call_args.kwargs["json"]["priority"] == "high"


@pytest.mark.asyncio
async def test_list_shaped_ticket_is_accepted():
    (ok, _), _client = await _send(_response(200, {"data": [{"status": "ok"}]}))
    assert ok


@pytest.mark.asyncio
async def test_device_not_registered_explains_what_to_do():
    (ok, msg), _client = await _send(
        _response(200, {"data": {"status": "error", "message": "gone", "details": {"error": "DeviceNotRegistered"}}})
    )
    assert not ok
    assert "no longer accepts notifications" in msg


@pytest.mark.asyncio
async def test_request_level_errors_and_http_errors():
    (ok, msg), _ = await _send(_response(200, {"errors": [{"code": "VALIDATION_ERROR", "message": "bad token"}]}))
    assert not ok and "bad token" in msg
    (ok, msg), _ = await _send(_response(503, {"oops": True}))
    assert not ok and "503" in msg


@pytest.mark.asyncio
async def test_missing_token_does_not_call_out():
    service = NotificationService()
    with patch.object(service, "_get_client", new_callable=AsyncMock) as get_client:
        ok, msg = await service._send_printbuddy_app({}, "t", "m")
    assert not ok and "token" in msg.lower()
    get_client.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_routes_printbuddy_app_and_passes_printer_id():
    service = NotificationService()
    provider = MagicMock()
    provider.provider_type = "printbuddy_app"
    provider.config = json.dumps({"push_token": TOKEN})
    provider.quiet_hours_enabled = False
    with patch.object(service, "_send_printbuddy_app", new_callable=AsyncMock, return_value=(True, "ok")) as send:
        ok, _ = await service._send_to_provider(provider, "T", "M", event_type="printer_error", printer_id=7)
    assert ok
    send.assert_awaited_once()
    assert send.call_args.kwargs == {"event_type": "printer_error", "printer_id": 7}


@pytest.mark.asyncio
async def test_test_notification_supports_printbuddy_app():
    service = NotificationService()
    with patch.object(service, "_send_printbuddy_app", new_callable=AsyncMock, return_value=(True, "ok")) as send:
        ok, _ = await service.send_test_notification("printbuddy_app", {"push_token": TOKEN})
    assert ok
    assert send.call_args.kwargs == {"event_type": "test"}


@pytest.mark.asyncio
async def test_unreachable_push_service_is_explained():
    import httpx

    service = NotificationService()
    client = AsyncMock()
    client.post = AsyncMock(side_effect=httpx.ProxyError("403 Forbidden"))
    with patch.object(service, "_get_client", new_callable=AsyncMock, return_value=client):
        ok, msg = await service._send_printbuddy_app({"push_token": TOKEN}, "t", "m")
    assert not ok
    assert "exp.host" in msg and "403 Forbidden" in msg
