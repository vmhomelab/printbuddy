"""get_drying_targets must not crash for non-Bambu provider clients.

Only BambuMQTTClient keeps a ``_drying_targets`` cache. Provider clients
(Moonraker, PrusaLink, OctoPrint, ...) have no AMS drying, so the manager
must return None for them instead of raising AttributeError, which used to
kill every WebSocket connection and the printer status endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.services.printer_manager import PrinterManager


def test_drying_targets_none_for_client_without_cache():
    manager = PrinterManager()
    manager._clients[3] = SimpleNamespace()  # provider client: no _drying_targets
    assert manager.get_drying_targets(3) is None


def test_drying_targets_returned_for_bambu_client():
    manager = PrinterManager()
    targets = {0: {"filament": "PLA", "temp": 55}}
    manager._clients[1] = SimpleNamespace(_drying_targets=targets)
    assert manager.get_drying_targets(1) is targets


def test_drying_targets_none_when_not_connected():
    assert PrinterManager().get_drying_targets(99) is None
