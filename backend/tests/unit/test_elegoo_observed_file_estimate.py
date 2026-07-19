"""Regression tests for CC1 EstWeight lookup on observed/external starts."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_observed_elegoo_print_registers_est_weight_from_running_filename(monkeypatch: pytest.MonkeyPatch):
    """Externally started CC1 prints must query Cmd 260 once Printbuddy sees RUNNING."""
    from backend.app import main
    from backend.app.services import direct_print_tracking

    calls: list[str] = []

    def get_file_info(path: str):
        calls.append(path)
        if path == "/local/external.gcode":
            return {
                "path": "/local/external.gcode",
                "estimated_weight_grams": 42.5,
                "estimated_time_seconds": 3600,
            }
        return None

    monkeypatch.setattr(
        main.printer_manager,
        "get_printer",
        lambda printer_id: SimpleNamespace(provider="elegoo_sdcp", model="Elegoo Centauri Carbon"),
    )
    monkeypatch.setattr(
        main.printer_manager, "get_client", lambda printer_id: SimpleNamespace(get_file_info=get_file_info)
    )

    await main._register_elegoo_observed_file_estimate(
        123,
        {"filename": "external.gcode", "subtask_name": "external"},
    )

    assert calls == ["external.gcode", "/external.gcode", "/local/external.gcode"]
    metadata = direct_print_tracking.pop_direct_print_metadata(123, "external.gcode")
    assert metadata is not None
    assert metadata.filename == "/local/external.gcode"
    assert metadata.estimated_weight_grams == pytest.approx(42.5)
    assert metadata.estimated_time_seconds == 3600


@pytest.mark.asyncio
async def test_observed_est_weight_lookup_ignores_non_elegoo_printers(monkeypatch: pytest.MonkeyPatch):
    from backend.app import main

    client = SimpleNamespace(get_file_info=lambda path: pytest.fail("non-Elegoo printer should not query file info"))
    monkeypatch.setattr(
        main.printer_manager,
        "get_printer",
        lambda printer_id: SimpleNamespace(provider="bambu", model="P1S"),
    )
    monkeypatch.setattr(main.printer_manager, "get_client", lambda printer_id: client)

    await main._register_elegoo_observed_file_estimate(123, {"filename": "external.gcode"})
