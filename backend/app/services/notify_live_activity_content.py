"""Build Notify Live Activity payloads from Printbuddy print state."""

from __future__ import annotations

import os
import re
from typing import Any

_PRINTBUDDY_SYMBOL = "printer"
_ACTIVE_COLOR = "#16a34a"
_PAUSED_COLOR = "#f59e0b"
_FAILED_COLOR = "#dc2626"
_DONE_COLOR = "#2563eb"
_STOPPED_COLOR = "#64748b"
_EXTENSIONS = (".gcode.3mf", ".gcode", ".3mf", ".stl")
_MEANINGLESS_NAME = re.compile(r"^plate[_\-]?\d+$", re.IGNORECASE)


def build_start_content(
    *,
    printer_name: str,
    filename: str,
    progress: float | int | None = 0,
    remaining_time: int | None = None,
    layer_num: int | None = None,
    total_layers: int | None = None,
    state: str = "running",
    compact_display: str = "eta",
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
        compact_display=compact_display,
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
    compact_display: str = "eta",
) -> dict[str, Any]:
    """Build payload for updating a Live Activity."""
    progress_value = _normalize_progress_percent(progress)
    percent_text = _percent_text(progress_value)
    state_key = (state or "running").lower()
    display_mode = _compact_display(compact_display)

    content: dict[str, Any] = {
        "title": printer_name,
        "body": _job_display_name(filename) or "Unknown print",
        "progress": progress_value,
        "status": _compact_progress_text(progress_value, layer_num=layer_num, total_layers=total_layers),
        "symbol": _PRINTBUDDY_SYMBOL,
        "tint": _ACTIVE_COLOR,
    }

    if state_key in {"pause", "paused"}:
        content["status"] = f"Paused · {percent_text}"
        content["trailing"] = f"Paused · {percent_text}"
        content["endsIn"] = None
        content["tint"] = _PAUSED_COLOR
    elif display_mode == "progress":
        content["status"] = percent_text
        content["endsIn"] = None
        content["trailing"] = _compact_progress_text(progress_value, layer_num=layer_num, total_layers=total_layers)
    elif remaining_time is not None and remaining_time > 0:
        content["endsIn"] = int(remaining_time)
        content["trailing"] = None
    else:
        content["trailing"] = _compact_progress_text(progress_value, layer_num=layer_num, total_layers=total_layers)

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
        "body": _job_display_name(filename) or "Unknown print",
        "status": body,
        "progress": 100,
        "symbol": _PRINTBUDDY_SYMBOL,
        "tint": color,
    }


def _normalize_progress_percent(progress: float | int | None) -> float:
    if progress is None:
        return 0
    value = float(progress)
    return round(min(max(value, 0), 100), 2)


def _percent_text(progress: float) -> str:
    return f"{int(progress)}%"


def _compact_progress_text(progress: float, *, layer_num: int | None, total_layers: int | None) -> str:
    percent = _percent_text(progress)
    if layer_num is not None and total_layers:
        return f"{percent} · L{layer_num}/{total_layers}"
    return percent


def _compact_display(value: str | None) -> str:
    return "progress" if str(value or "").lower() in {"progress", "percent", "percentage", "layer"} else "eta"


def _job_display_name(filename: str | None) -> str | None:
    if not filename or not filename.strip():
        return None
    base = os.path.basename(filename.strip().replace("\\", "/"))
    for extension in _EXTENSIONS:
        if base.lower().endswith(extension):
            base = base[: -len(extension)]
            break
    base = " ".join(base.split())
    if not base or _MEANINGLESS_NAME.match(base):
        return None
    return base
