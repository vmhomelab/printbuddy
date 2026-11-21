"""OctoEverywhere Gadget AI print-failure detection service (PB-35).

An optional second detection provider next to the self-hosted Obico service.
It is configured separately and does not touch any Obico setting or state.

Per monitored printer and print:
  1. create a Gadget context (free, uses the API key),
  2. upload JPEG snapshots at the interval Gadget asks for,
  3. act on rising edges of ``WarningSuggested`` (notify) and
     ``PauseSuggested`` (configured action: notify / pause / pause_and_off).

Gadget's temporal model already smooths results over the print, so there is
no client-side smoothing. Context IDs and process URLs are secrets: they are
kept in memory only and never logged or exposed through the status API.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.core.database import async_session
from backend.app.models.printer import Printer
from backend.app.models.settings import Settings
from backend.app.services import octoeverywhere_gadget as gadget
from backend.app.services.failure_detection_camera import NO_CAMERA, capture_detection_frame

logger = logging.getLogger(__name__)

SOURCE = "OctoEverywhere"
HISTORY_MAX = 50
TICK_ENABLED = 2.0  # seconds between scheduler ticks while enabled
TICK_DISABLED = 10.0
NO_CAMERA_RETRY = 60  # seconds before retrying a printer that has no camera
ACCOUNT_BLOCK_SECONDS = 3600  # back-off after a key/account error (free limit, IP restriction, ...)
ACTIVE_PRINT_STATES = ("RUNNING", "PAUSE")

KEY_ENABLED = "octoeverywhere_enabled"
KEY_API_KEY = "octoeverywhere_api_key"
KEY_SENSITIVITY = "octoeverywhere_sensitivity"
KEY_ACTION = "octoeverywhere_action"
KEY_POLL_INTERVAL = "octoeverywhere_poll_interval"
KEY_ENABLED_PRINTERS = "octoeverywhere_enabled_printers"
KEY_NOTIFY_ON_WARNING = "octoeverywhere_notify_on_warning"
ALL_KEYS = (
    KEY_ENABLED,
    KEY_API_KEY,
    KEY_SENSITIVITY,
    KEY_ACTION,
    KEY_POLL_INTERVAL,
    KEY_ENABLED_PRINTERS,
    KEY_NOTIFY_ON_WARNING,
)

SENSITIVITIES = ("low", "medium", "high")
ACTIONS = ("notify", "pause", "pause_and_off")
POLL_INTERVAL_AUTO = 0  # follow Gadget's recommended interval
POLL_INTERVAL_MIN = 5
POLL_INTERVAL_MAX = 120


def parse_enabled_printers(raw: str | None) -> list[int] | None:
    """'' / missing / invalid -> None (all printers); JSON int array -> list."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in parsed):
        return None
    return parsed


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else ""


async def load_settings() -> dict:
    """Read the OctoEverywhere settings; decrypts the API key."""
    from backend.app.core.encryption import mfa_decrypt

    async with async_session() as db:
        result = await db.execute(select(Settings).where(Settings.key.in_(ALL_KEYS)))
        rows = {r.key: r.value for r in result.scalars().all()}

    api_key = ""
    key_error = None
    stored_key = rows.get(KEY_API_KEY) or ""
    if stored_key:
        try:
            api_key = mfa_decrypt(stored_key)
        except RuntimeError:
            key_error = "Stored OctoEverywhere API key cannot be decrypted; re-enter it in Settings"

    sensitivity = rows.get(KEY_SENSITIVITY) or "medium"
    if sensitivity not in SENSITIVITIES:
        sensitivity = "medium"
    action = rows.get(KEY_ACTION) or "notify"
    if action not in ACTIONS:
        action = "notify"
    try:
        poll_interval = int(rows.get(KEY_POLL_INTERVAL) or POLL_INTERVAL_AUTO)
    except ValueError:
        poll_interval = POLL_INTERVAL_AUTO
    if poll_interval != POLL_INTERVAL_AUTO:
        poll_interval = max(POLL_INTERVAL_MIN, min(POLL_INTERVAL_MAX, poll_interval))

    return {
        "enabled": (rows.get(KEY_ENABLED) or "false").lower() == "true",
        "api_key": api_key,
        "has_api_key": bool(stored_key),
        "key_error": key_error,
        "sensitivity": sensitivity,
        "action": action,
        "poll_interval": poll_interval,
        "enabled_printers": parse_enabled_printers(rows.get(KEY_ENABLED_PRINTERS)),
        "notify_on_warning": (rows.get(KEY_NOTIFY_ON_WARNING) or "true").lower() == "true",
    }


@dataclass
class PrinterDetectionState:
    """Per-printer, per-print state. Reset whenever a new print starts."""

    task_key: str
    context: gadget.GadgetContext | None = None
    using_fallback: bool = False
    next_due: float = 0.0
    min_interval: int = gadget.DEFAULT_MIN_INTERVAL_SEC
    recommended_interval: int = gadget.DEFAULT_INTERVAL_SEC
    frame_count: int = 0
    print_quality: int | None = None
    score: int | None = None
    warning: bool = False
    pause: bool = False
    last_checked: str | None = None
    # Terminal reason for this print (context expired/cancelled/not found)
    stopped_reason: str | None = None
    # Last non-fatal problem for this printer (no_camera, viewer_busy, ...)
    last_issue: str | None = None


class OctoEverywhereDetectionService:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._states: dict[int, PrinterDetectionState] = {}
        self._inflight: dict[int, asyncio.Task] = {}
        self._history: deque = deque(maxlen=HISTORY_MAX)
        self._last_error: str | None = None
        # {"error_type", "until" (monotonic), "key_fp"}
        self._account_block: dict | None = None
        self._key_fp: str = ""

    # ---- lifecycle ----

    async def start(self):
        if self._task is not None:
            return
        logger.info("Starting OctoEverywhere detection service")
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        for task in self._inflight.values():
            task.cancel()
        self._inflight.clear()
        logger.info("Stopped OctoEverywhere detection service")

    # ---- main loop ----

    async def _loop(self):
        while True:
            try:
                settings = await load_settings()
                if not settings["enabled"] or not settings["api_key"]:
                    self._reset_all()
                    if settings["enabled"] and settings["key_error"]:
                        self._last_error = settings["key_error"]
                    await asyncio.sleep(TICK_DISABLED)
                    continue
                self._poll_once(settings)
                await asyncio.sleep(TICK_ENABLED)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("OctoEverywhere detection loop error: %s", e)
                self._last_error = str(e) or type(e).__name__
                await asyncio.sleep(30)

    def _reset_all(self):
        self._states.clear()
        self._account_block = None

    def _account_blocked(self) -> bool:
        block = self._account_block
        if block is None:
            return False
        if block["key_fp"] != self._key_fp or time.monotonic() >= block["until"]:
            self._account_block = None
            return False
        return True

    def _poll_once(self, settings: dict):
        """Schedule a check for every monitored printer that is due. Non-blocking."""
        from backend.app.services.printer_manager import printer_manager

        key_fp = _key_fingerprint(settings["api_key"])
        if key_fp != self._key_fp:
            # Contexts belong to the account that created them; start over on a new key.
            self._key_fp = key_fp
            self._states.clear()
            self._account_block = None
            self._last_error = None

        if self._account_blocked():
            return

        statuses = printer_manager.get_all_statuses()
        enabled_printers = settings["enabled_printers"]
        now = time.monotonic()

        for printer_id in list(self._states):
            if printer_id not in statuses:
                self._states.pop(printer_id, None)

        for printer_id, status in list(statuses.items()):
            if enabled_printers is not None and printer_id not in enabled_printers:
                self._states.pop(printer_id, None)
                continue
            if not printer_manager.is_connected(printer_id):
                continue
            state_name = getattr(status, "state", None) if status else None
            if state_name not in ACTIVE_PRINT_STATES:
                # Print ended: the next print gets a fresh context.
                self._states.pop(printer_id, None)
                continue

            task_key = _task_key(status)
            state = self._states.get(printer_id)
            if state is None or state.task_key != task_key:
                state = PrinterDetectionState(task_key=task_key)
                self._states[printer_id] = state

            # Keep the context while paused so a resumed print keeps its history,
            # but only inspect while actually printing.
            if state_name != "RUNNING" or state.stopped_reason or now < state.next_due:
                continue
            if printer_id in self._inflight:
                continue
            task = asyncio.create_task(self._check_printer(printer_id, state, settings))
            self._inflight[printer_id] = task
            task.add_done_callback(lambda _t, pid=printer_id: self._inflight.pop(pid, None))

    # ---- one inspection ----

    async def _check_printer(self, printer_id: int, state: PrinterDetectionState, settings: dict):
        now = time.monotonic()
        # Never hot-loop, whatever happens below.
        state.next_due = now + state.recommended_interval

        async with async_session() as db:
            printer = await db.get(Printer, printer_id)
        if printer is None:
            state.last_issue = "printer_not_found"
            return

        frame, reason = await capture_detection_frame(printer)
        if not frame:
            state.last_issue = reason
            if reason == NO_CAMERA:
                state.next_due = time.monotonic() + NO_CAMERA_RETRY
            return
        if len(frame) > gadget.MAX_IMAGE_BYTES:
            state.last_issue = "frame_too_large"
            return

        if state.context is None:
            try:
                state.context = await gadget.create_context(settings["api_key"], settings["sensitivity"])
            except gadget.GadgetError as e:
                self._handle_error(printer_id, state, e, during="create context")
                return

        url = state.context.fallback_url if state.using_fallback else state.context.process_url
        try:
            result = await gadget.process_frame(url, frame)
        except gadget.GadgetError as e:
            self._handle_error(printer_id, state, e, during="process snapshot")
            return

        self._apply_result(state, result, settings)
        self._last_error = None
        state.last_issue = None
        await self._handle_suggestions(printer_id, state, result, settings, frame)

    def _apply_result(self, state: PrinterDetectionState, result: gadget.GadgetResult, settings: dict):
        state.frame_count += 1
        state.print_quality = result.print_quality
        state.score = result.score
        state.min_interval = result.min_interval
        state.recommended_interval = result.recommended_interval
        state.last_checked = datetime.now(timezone.utc).isoformat()

        configured = settings["poll_interval"]
        if configured == POLL_INTERVAL_AUTO or result.faster_inspection_suggested:
            delay = result.recommended_interval
        else:
            delay = configured
        state.next_due = time.monotonic() + max(delay, result.min_interval)

    async def _handle_suggestions(
        self,
        printer_id: int,
        state: PrinterDetectionState,
        result: gadget.GadgetResult,
        settings: dict,
        frame: bytes,
    ):
        """Act on rising edges only: Gadget keeps the flags true while the issue lasts."""
        warning_rose = result.warning_suggested and not state.warning
        pause_rose = result.pause_suggested and not state.pause
        state.warning = result.warning_suggested
        state.pause = result.pause_suggested

        if result.warning_suggested or result.pause_suggested or (result.print_quality or 10) <= 5:
            self._history.appendleft(
                {
                    "printer_id": printer_id,
                    "task_name": state.task_key,
                    "timestamp": state.last_checked,
                    "print_quality": result.print_quality,
                    "score": result.score,
                    "warning": result.warning_suggested,
                    "pause": result.pause_suggested,
                }
            )

        if pause_rose:
            await self._dispatch(printer_id, state, settings["action"], "pause", result, frame)
        elif warning_rose and settings["notify_on_warning"]:
            await self._dispatch(printer_id, state, "notify", "warning", result, frame)

    async def _dispatch(
        self,
        printer_id: int,
        state: PrinterDetectionState,
        action: str,
        level: str,
        result: gadget.GadgetResult,
        frame: bytes,
    ):
        from backend.app.services.obico_actions import execute_action

        task_name = state.task_key or "current job"
        quality = f"{result.print_quality}/10" if result.print_quality is not None else "unknown"
        if level == "pause":
            detail = (
                f"OctoEverywhere AI: likely print failure on '{task_name}' "
                f"(print quality {quality}). Action taken: {action}."
            )
        else:
            detail = f"OctoEverywhere AI: possible print issue on '{task_name}' (print quality {quality})."
        logger.warning(
            "OctoEverywhere: %s suggested for printer %s (task=%r quality=%s score=%s) - action=%s",
            level,
            printer_id,
            state.task_key,
            result.print_quality,
            result.score,
            action,
        )
        try:
            await execute_action(
                printer_id,
                action,
                state.task_key,
                (result.score or 0) / 100,
                source=SOURCE,
                detail=detail,
                image_data=frame,
            )
        except Exception as e:
            self._last_error = f"Action dispatch failed: {e or type(e).__name__}"
            logger.error(self._last_error)

    def _handle_error(self, printer_id: int, state: PrinterDetectionState, err: gadget.GadgetError, during: str):
        now = time.monotonic()
        self._last_error = f"Printer {printer_id}: {during} failed: {err}"
        logger.warning("OctoEverywhere: %s", self._last_error)

        if err.is_account_error:
            self._account_block = {
                "error_type": err.error_type,
                "until": now + ACCOUNT_BLOCK_SECONDS,
                "key_fp": self._key_fp,
            }
            return
        if err.is_context_ended:
            state.stopped_reason = err.error_type
            return
        if err.error_type == "OE_CONTEXT_RATE_LIMITED":
            state.next_due = now + max(err.retry_after or 0, state.min_interval, state.recommended_interval)
            return
        if (
            err.is_connection_failure
            and during == "process snapshot"
            and state.context is not None
            and state.context.fallback_url
            and not state.using_fallback
        ):
            # Docs: switch to the fallback URL and keep using it for this context.
            state.using_fallback = True
        state.next_due = now + state.recommended_interval

    # ---- queries ----

    def get_status(self) -> dict:
        blocked = self._account_blocked()
        now = time.monotonic()
        return {
            "is_running": self._task is not None and not self._task.done(),
            "last_error": self._last_error,
            "account_error": self._account_block["error_type"] if blocked else None,
            "per_printer": {
                pid: {
                    "print_quality": st.print_quality,
                    "score": st.score,
                    "warning": st.warning,
                    "pause": st.pause,
                    "frame_count": st.frame_count,
                    "last_checked": st.last_checked,
                    "next_check_in": max(0, round(st.next_due - now)) if not st.stopped_reason else None,
                    "using_fallback": st.using_fallback,
                    "stopped_reason": st.stopped_reason,
                    "last_issue": st.last_issue,
                }
                for pid, st in self._states.items()
            },
            "history": list(self._history),
        }

    async def test_connection(self, api_key: str) -> dict:
        """Validate a key by creating (and immediately cancelling) a context.

        Creating a context is free; no snapshot is uploaded, so nothing is billed.
        """
        if not api_key:
            return {"ok": False, "error_type": None, "error": "API key is empty"}
        try:
            ctx = await gadget.create_context(api_key)
        except gadget.GadgetError as e:
            return {"ok": False, "error_type": e.error_type, "error": str(e)}
        await gadget.cancel_context(ctx.context_id)
        return {"ok": True, "error_type": None, "error": None}


def _task_key(status) -> str:
    return str(getattr(status, "task_name", None) or getattr(status, "subtask_name", "") or "")


octoeverywhere_detection_service = OctoEverywhereDetectionService()
