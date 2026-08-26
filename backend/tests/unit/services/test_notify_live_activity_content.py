"""Tests for Notify Live Activity content payloads."""

from backend.app.services.notify_live_activity_content import (
    build_end_content,
    build_start_content,
    build_update_content,
)


def test_start_content_normalizes_progress_eta_and_layers():
    content = build_start_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=12,
        remaining_time=5400,
        layer_num=8,
        total_layers=120,
    )

    assert content["title"] == "Workshop P1S"
    assert content["subtitle"] == "dragon.3mf"
    assert content["progress"] == 12
    assert content["endsIn"] == 5400
    assert content["body"] == "12% · Layer 8 / 120"
    assert content["symbol"] == "printer"
    assert content["tintColor"] == "#16a34a"


def test_update_content_clamps_progress_and_omits_unknown_eta():
    content = build_update_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=150,
        remaining_time=None,
    )

    assert content["progress"] == 100
    assert "endsIn" not in content
    assert content["body"] == "100%"


def test_update_content_marks_paused_without_countdown():
    content = build_update_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=50,
        remaining_time=1200,
        state="paused",
    )

    assert content["body"] == "Paused · 50%"
    assert "endsIn" not in content
    assert content["tintColor"] == "#f59e0b"


def test_end_content_uses_terminal_status_visual_state():
    content = build_end_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        status="failed",
        reason="Filament runout",
    )

    assert content["title"] == "Workshop P1S"
    assert content["subtitle"] == "dragon.3mf"
    assert content["body"] == "Failed · Filament runout"
    assert content["progress"] == 100
    assert content["tintColor"] == "#dc2626"
