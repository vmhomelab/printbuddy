"""Build Notify Live Activity payloads from Printbuddy print state."""

from __future__ import annotations

from typing import Any

_PRINTBUDDY_SYMBOL = "printer"
_ACTIVE_COLOR = "#16a34a"
_PAUSED_COLOR = "#f59e0b"
_FAILED_COLOR = "#dc2626"
_DONE_COLOR = "#2563eb"
_STOPPED_COLOR = "#64748b"


def build_start_content(
    *,
    printer_name: str,
    filename: str,
    progress: float | int | None = 0,
    remaining_time: int | None = None,
    layer_num: int | None = None,
    total_layers: int | None = None,
    state: str = "running",
) -> dict[str, Any]:
    """Build payload for creating a Live Activity."""
    return build_update_content(
        printer_name=printer_name,
        filename=filename,
        progress=progress,
        remaining_time=remaining_time,
        layer_num=layer_num,
        total_layers=total_layers,
        state=state,
    )


def build_update_content(
    *,
    printer_name: str,
    filename: str,
    progress: float | int | None,
    remaining_time: int | None = None,
    layer_num: int | None = None,
    total_layers: int | None = None,
    state: str = "running",
) -> dict[str, Any]:
    """Build payload for updating a Live Activity."""
    progress_value = _normalize_progress_percent(progress)
    state_key = (state or "running").lower()
    body = _progress_body(progress_value, layer_num=layer_num, total_layers=total_layers)

    content: dict[str, Any] = {
        "title": printer_name,
        "subtitle": filename or "Unknown print",
        "body": body,
        "progress": progress_value,
        "symbol": _PRINTBUDDY_SYMBOL,
        "tintColor": _ACTIVE_COLOR,
    }

    if state_key in {"pause", "paused"}:
        content["body"] = f"Paused · {int(progress_value)}%"
        content["tintColor"] = _PAUSED_COLOR
    elif remaining_time is not None and remaining_time > 0:
        content["endsIn"] = int(remaining_time)

    return content


def build_end_content(
    *,
    printer_name: str,
    filename: str,
    status: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build payload for ending a Live Activity."""
    status_key = (status or "completed").lower()
    if status_key == "failed":
        label = "Failed"
        color = _FAILED_COLOR
    elif status_key in {"aborted", "cancelled", "stopped"}:
        label = "Stopped"
        color = _STOPPED_COLOR
    else:
        label = "Completed"
        color = _DONE_COLOR

    body = label
    if reason:
        body = f"{label} · {reason}"

    return {
        "title": printer_name,
        "subtitle": filename or "Unknown print",
        "body": body,
        "progress": 100,
        "symbol": _PRINTBUDDY_SYMBOL,
        "tintColor": color,
    }


def _normalize_progress_percent(progress: float | int | None) -> float:
    if progress is None:
        return 0
    value = float(progress)
    if 0 < value <= 1:
        value *= 100
    return round(min(max(value, 0), 100), 2)


def _progress_body(progress: float, *, layer_num: int | None, total_layers: int | None) -> str:
    percent = int(progress)
    if layer_num is not None and total_layers:
        return f"{percent}% · Layer {layer_num} / {total_layers}"
    return f"{percent}%"
