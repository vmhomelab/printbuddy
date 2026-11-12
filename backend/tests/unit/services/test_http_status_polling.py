"""Background status polling for HTTP printer providers.

HTTP providers (Moonraker, OctoPrint, PrusaLink, ...) used to fetch their
status synchronously on every ``get_status()`` call, which blocked the asyncio
event loop and stalled the whole backend behind slow printers. These tests
pin the replacement: a per-printer poller thread, cached status reads, and a
Moonraker client that reuses its HTTP connection and object list.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services import printer_manager as pm_module
from backend.app.services.printer_manager import PrinterManager, _StatusPoller, init_printer_connections
from backend.app.services.printer_providers._http_common import serialized_status_update
from backend.app.services.printer_providers.moonraker import MoonrakerPrinterClient


def _http_printer(printer_id=1, provider="klipper"):
    return SimpleNamespace(
        id=printer_id,
        name=f"Printer {printer_id}",
        serial_number=f"SN{printer_id}",
        model="X-Max 4",
        provider=provider,
        ip_address="192.168.1.50",
        access_code="",
    )


def _http_client():
    client = MagicMock()
    client.state = SimpleNamespace(connected=True, state="IDLE")
    client.on_state_change = None
    return client


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestPrinterManagerPolling:
    @pytest.mark.asyncio
    async def test_http_provider_gets_poller_and_status_reads_cache(self):
        manager = PrinterManager()
        client = _http_client()
        with (
            patch.object(pm_module, "create_printer_client", return_value=client),
            patch.object(pm_module.asyncio, "sleep", return_value=None),
        ):
            assert await manager.connect_printer(_http_printer()) is True

        try:
            assert 1 in manager._pollers
            client.check_staleness.reset_mock()

            assert manager.get_status(1) is client.state
            assert manager.is_connected(1) is True
            assert manager.get_all_statuses() == {1: client.state}
            client.check_staleness.assert_not_called()
        finally:
            manager.disconnect_printer(1)

        assert 1 not in manager._pollers

    @pytest.mark.asyncio
    async def test_http_connect_runs_off_the_event_loop(self):
        manager = PrinterManager()
        client = _http_client()
        loop_thread = threading.get_ident()
        connect_threads = []
        client.connect.side_effect = lambda: connect_threads.append(threading.get_ident())
        with (
            patch.object(pm_module, "create_printer_client", return_value=client),
            patch.object(pm_module.asyncio, "sleep", return_value=None),
        ):
            await manager.connect_printer(_http_printer())
        manager.disconnect_printer(1)

        assert connect_threads and connect_threads[0] != loop_thread

    def test_bambu_clients_keep_checking_staleness(self):
        manager = PrinterManager()
        client = MagicMock()
        client.check_staleness.return_value = False
        manager._clients[1] = client

        assert manager.is_connected(1) is False
        client.check_staleness.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_connects_printers_concurrently(self):
        printers = [_http_printer(1), _http_printer(2), _http_printer(3)]
        result = MagicMock()
        result.scalars.return_value.all.return_value = printers
        db = MagicMock()

        async def execute(_query):
            return result

        db.execute = execute
        active = 0
        peak = 0

        async def slow_connect(_printer):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return True

        with patch.object(pm_module.printer_manager, "connect_printer", side_effect=slow_connect):
            await init_printer_connections(db)

        assert peak == 3


class TestStatusPoller:
    def test_polls_until_stopped(self):
        client = _http_client()
        poller = _StatusPoller(client, 0.01, "test")
        poller.start()
        try:
            assert _wait_until(lambda: client.request_status_update.call_count >= 3)
        finally:
            poller.stop()

    def test_marks_offline_after_consecutive_failures_and_notifies(self):
        client = _http_client()
        client.request_status_update.side_effect = RuntimeError("timeout")
        notified = []
        client.on_state_change = lambda state: notified.append(state.connected)
        poller = _StatusPoller(client, 0.01, "test")
        poller.start()
        try:
            assert _wait_until(lambda: client.state.connected is False)
        finally:
            poller.stop()

        assert notified[:1] == [False]
        assert client.request_status_update.call_count >= pm_module.HTTP_POLL_FAILURES_BEFORE_OFFLINE


class TestSerializedStatusUpdate:
    def test_overlapping_updates_do_not_interleave(self):
        class Client:
            def __init__(self):
                self.active = 0
                self.peak = 0

            @serialized_status_update
            def request_status_update(self):
                self.active += 1
                self.peak = max(self.peak, self.active)
                time.sleep(0.02)
                self.active -= 1
                return True

        client = Client()
        threads = [threading.Thread(target=client.request_status_update) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert client.peak == 1

    def test_lock_is_reentrant(self):
        class Client:
            @serialized_status_update
            def request_status_update(self, depth=0):
                return True if depth else self.request_status_update(depth=1)

        assert Client().request_status_update() is True


class TestMoonrakerHttpReuse:
    def test_object_list_is_cached_between_lookups(self, monkeypatch):
        client = MoonrakerPrinterClient("http://qidi.local:7125")
        calls = []

        def fake_get(path, *, base_url=None):  # noqa: ARG001
            calls.append(path)
            return {"objects": ["extruder", "output_pin LED"]}

        monkeypatch.setattr(client, "_get", fake_get)

        assert client._available_objects() == ["extruder", "output_pin LED"]
        assert client._available_objects() == ["extruder", "output_pin LED"]
        assert calls == ["printer/objects/list"]

        client._invalidate_objects_cache()
        client._available_objects()
        assert calls == ["printer/objects/list", "printer/objects/list"]

    def test_object_cache_dropped_when_klippy_not_ready(self, monkeypatch):
        client = MoonrakerPrinterClient("http://qidi.local:7125")
        client._objects_cache = ["stale"]
        client._objects_cache_at = time.monotonic()
        monkeypatch.setattr(client, "_query_objects", lambda names: {"webhooks": {"state": "startup"}})
        monkeypatch.setattr(client, "_available_objects", lambda: [])

        client.request_status_update()

        assert client._objects_cache is None

    def test_object_cache_dropped_when_status_poll_fails(self, monkeypatch):
        client = MoonrakerPrinterClient("http://qidi.local:7125")
        client._objects_cache = ["stale"]

        def fail(_names):
            raise RuntimeError("klippy restarting")

        monkeypatch.setattr(client, "_query_objects", fail)

        with pytest.raises(RuntimeError):
            client.request_status_update()
        assert client._objects_cache is None

    def test_http_client_is_reused_and_closed_on_disconnect(self):
        client = MoonrakerPrinterClient("http://qidi.local:7125")
        first = client._http_client()
        assert client._http_client() is first

        client.disconnect()

        assert first.is_closed
        assert client._http_client() is not first
        client.disconnect()
