"""Tests for Notify Live Activity content payloads."""

from backend.app.services.notify_live_activity_content import (
    build_end_content,
    build_start_content,
    build_update_content,
)


def test_start_content_shows_job_name_in_body_and_eta_in_compact_slot_by_default():
    content = build_start_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=12,
        remaining_time=5400,
        layer_num=8,
        total_layers=120,
    )

    assert content["title"] == "Workshop P1S"
    assert "subtitle" not in content
    assert content["body"] == "dragon"
    assert content["progress"] == 12
    assert content["endsIn"] == 5400
    assert content["trailing"] is None
    assert content["status"] == "12%"
    assert content["symbol"] == "printer"
    assert content["tintColor"] == "#16a34a"


def test_update_content_can_show_percent_and_layer_in_dynamic_island_slot():
    content = build_update_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=12.75,
        remaining_time=5400,
        layer_num=8,
        total_layers=120,
        compact_display="progress",
    )

    assert content["title"] == "Workshop P1S"
    assert "subtitle" not in content
    assert content["body"] == "dragon"
    assert content["progress"] == 12.75
    assert content["endsIn"] is None
    assert content["trailing"] == "12% · L8/120"
    assert content["status"] == "12%"


def test_update_content_clamps_progress_and_omits_unknown_eta():
    content = build_update_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=150,
        remaining_time=None,
    )

    assert content["progress"] == 100
    assert "endsIn" not in content
    assert content["body"] == "dragon"
    assert content["status"] == "100%"


def test_update_content_marks_paused_without_countdown():
    content = build_update_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        progress=50,
        remaining_time=1200,
        state="paused",
    )

    assert content["body"] == "dragon"
    assert content["status"] == "Paused · 50%"
    assert content["trailing"] == "Paused · 50%"
    assert content["endsIn"] is None
    assert content["tintColor"] == "#f59e0b"


def test_end_content_uses_terminal_status_visual_state():
    content = build_end_content(
        printer_name="Workshop P1S",
        filename="dragon.3mf",
        status="failed",
        reason="Filament runout",
    )

    assert content["title"] == "Workshop P1S"
    assert "subtitle" not in content
    assert content["body"] == "dragon"
    assert content["status"] == "Failed · Filament runout"
    assert content["progress"] == 100
    assert content["tintColor"] == "#dc2626"
