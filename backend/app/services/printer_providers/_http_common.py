"""Shared building blocks for HTTP-polled printer providers.

PrusaLink and OctoPrint expose a request/response status API that Printbuddy
polls. Neither pushes print lifecycle events, so the client has to derive
"print started" / "print finished" from consecutive status samples. The
edge detection for that lives here so each provider only has to map its own
API payloads onto ``self.state``.
"""

from __future__ import annotations

import time
from typing import Any


def minutes_from_seconds(value: Any) -> int:
    try:
        return int(max(float(value or 0), 0) // 60)
    except (TypeError, ValueError):
        return 0


def float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class PolledLifecycleMixin:
    """Derive print start/complete callbacks from polled printer state.

    Hosts provide ``state`` (with ``state``, ``progress``, ``remaining_time``,
    ``temperatures``, ``raw_data`` and the filename fields), the ``on_*``
    callbacks, and initialise ``_last_bed_temp`` and
    ``_current_print_started_at`` to ``None``.
    """

    # States that count as "a print job is active". A transition into this set
    # fires on_print_start, a transition out of it fires on_print_complete.
    LIFECYCLE_ACTIVE_STATES: frozenset[str] = frozenset({"RUNNING", "PAUSE"})

    state: Any
    on_state_change: Any
    on_print_start: Any
    on_print_complete: Any
    on_bed_temp_update: Any
    _last_bed_temp: float | None
    _current_print_started_at: float | None

    def _build_lifecycle_payload(self) -> dict[str, Any]:
        filename = self.state.subtask_name or self.state.current_print or self.state.gcode_file or "Unknown"
        payload = {
            "filename": filename,
            "subtask_name": filename,
            "progress": self.state.progress,
            "remaining_time": self.state.remaining_time * 60 if self.state.remaining_time else None,
            "status": self.state.state,
        }
        file_metadata = self.state.raw_data.get("file_metadata") if isinstance(self.state.raw_data, dict) else None
        if file_metadata:
            payload["file_metadata"] = file_metadata
        return payload

    def _completion_status(self, current_state: str) -> str:
        """Map the state a print ended in to an archive status."""
        if current_state == "FAILED":
            return "failed"
        if current_state == "FINISH":
            return "completed"
        if current_state == "IDLE":
            return "completed" if self.state.progress >= 99 else "stopped"
        return "stopped"

    def _emit_status_callbacks(self, previous_state: str | None) -> None:
        if self.on_state_change:
            self.on_state_change(self.state)

        bed_temp = self.state.temperatures.get("bed") if self.state.temperatures else None
        if isinstance(bed_temp, (int, float)) and bed_temp != self._last_bed_temp:
            self._last_bed_temp = float(bed_temp)
            if self.on_bed_temp_update:
                self.on_bed_temp_update(float(bed_temp))

        current_state = self.state.state
        previous_running = previous_state in self.LIFECYCLE_ACTIVE_STATES
        current_running = current_state in self.LIFECYCLE_ACTIVE_STATES

        # No synthetic start on the very first poll: if Printbuddy starts while
        # a print is already running, the restart-recovery path owns that case.
        if previous_state is not None and not previous_running and current_running:
            self._current_print_started_at = time.monotonic()
            if self.on_print_start:
                self.on_print_start(self._build_lifecycle_payload())
        elif previous_running and not current_running:
            payload = self._build_lifecycle_payload()
            if self._current_print_started_at is not None:
                payload["actual_time_seconds"] = max(1, int(time.monotonic() - self._current_print_started_at))
                self._current_print_started_at = None
            payload["status"] = self._completion_status(current_state)
            if self.on_print_complete:
                self.on_print_complete(payload)
