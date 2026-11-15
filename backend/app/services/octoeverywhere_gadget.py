"""Thin HTTP client for the OctoEverywhere Gadget AI failure-detection API.

Gadget works per print: Printbuddy creates a *context* with the account API key,
then uploads JPEG snapshots to the returned ``ProcessRequestUrl``. The context ID
inside that URL authorizes processing, so the API key is only sent to
``createcontext``. Both the context ID and the process URLs are secrets and must
never be logged or returned by Printbuddy's API.

Docs: https://docs.octoeverywhere.com/ai-failure-detection-apis/developer-docs/overview/
"""

from dataclasses import dataclass

import httpx

GADGET_API_BASE = "https://gadget-pv1-oeapi.octoeverywhere.com/api/gadget/v1"
CREATE_CONTEXT_URL = f"{GADGET_API_BASE}/createcontext"
CANCEL_CONTEXT_URL = f"{GADGET_API_BASE}/cancelcontext"

REQUEST_TIMEOUT = 30.0
# Process API limits: 6 MiB upload, <= 8192 px per side, <= 20 MP.
MAX_IMAGE_BYTES = 6 * 1024 * 1024
DEFAULT_INTERVAL_SEC = 20
DEFAULT_MIN_INTERVAL_SEC = 5

# ErrorTypes documented as "wait and retry at the next interval".
RETRYABLE_ERRORS = frozenset({"OE_CONTEXT_RATE_LIMITED", "OE_BACKEND_THROTTLED", "OE_INTERNAL_ERROR"})
# ErrorTypes that are a property of the account / API key: retrying with a new
# context or the fallback URL does not help, so the whole provider backs off.
ACCOUNT_ERRORS = frozenset(
    {
        "OE_INVALID_API_KEY",
        "OE_API_KEY_DISABLED",
        "OE_API_KEY_BLOCKED_PAYMENT_FAILED",
        "OE_API_KEY_IP_RESTRICTED",
        "OE_FREE_USAGE_LIMIT_REACHED",
    }
)
# ErrorTypes that end the current print's context for good.
CONTEXT_ENDED_ERRORS = frozenset({"OE_CONTEXT_NOT_FOUND", "OE_CONTEXT_EXPIRED", "OE_CONTEXT_CANCELLED"})
# ErrorTypes caused by the uploaded frame; the next frame may succeed.
FRAME_ERRORS = frozenset({"OE_BAD_ARGS", "OE_IMAGE_DECODE_FAILED", "OE_ARGS_PARSE_FAILED"})

# Sensitivity -> Gadget confidence level (1 = act sooner, 5 = needs more confidence).
CONFIDENCE_BY_SENSITIVITY = {"low": 4, "medium": 3, "high": 2}


class GadgetError(Exception):
    """A Gadget call failed.

    Messages never contain request URLs (the process URL embeds the secret
    context ID), so they are safe to log and to show in the status API.

    ``error_type`` is the documented ``ErrorType`` (``None`` for connection
    failures, timeouts and non-JSON responses, which are the cases where the
    fallback URL should be tried).
    """

    def __init__(
        self,
        message: str,
        *,
        error_type: str | None = None,
        status_code: int | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.retry_after = retry_after

    @property
    def is_connection_failure(self) -> bool:
        return self.error_type is None

    @property
    def is_account_error(self) -> bool:
        return self.error_type in ACCOUNT_ERRORS

    @property
    def is_context_ended(self) -> bool:
        return self.error_type in CONTEXT_ENDED_ERRORS


@dataclass
class GadgetContext:
    context_id: str
    process_url: str
    fallback_url: str | None


@dataclass
class GadgetResult:
    print_quality: int | None
    score: int | None
    warning_suggested: bool
    pause_suggested: bool
    faster_inspection_suggested: bool
    min_interval: int
    recommended_interval: int


def _parse_retry_after(resp: httpx.Response) -> int | None:
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return None


def _error_from_response(resp: httpx.Response) -> GadgetError:
    error_type = None
    details = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            error_type = body.get("ErrorType") or None
            details = str(body.get("ErrorDetails") or "")
    except ValueError:
        pass
    label = error_type or f"HTTP {resp.status_code}"
    message = f"{label}: {details}" if details else label
    return GadgetError(
        message,
        error_type=error_type,
        status_code=resp.status_code,
        retry_after=_parse_retry_after(resp),
    )


def _as_int(value, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_process_response(body: dict) -> GadgetResult:
    intervals = body.get("NextProcessIntervalSec") or {}
    minimum = max(DEFAULT_MIN_INTERVAL_SEC, _as_int(intervals.get("Minimum"), DEFAULT_MIN_INTERVAL_SEC))
    recommended = max(minimum, _as_int(intervals.get("Recommended"), DEFAULT_INTERVAL_SEC))
    return GadgetResult(
        print_quality=_as_int(body.get("PrintQuality"), None),
        score=_as_int(body.get("Score"), None),
        warning_suggested=bool(body.get("WarningSuggested", False)),
        pause_suggested=bool(body.get("PauseSuggested", False)),
        # Docs: treat a missing field as false.
        faster_inspection_suggested=bool(body.get("FasterInspectionSuggested", False)),
        min_interval=minimum,
        recommended_interval=recommended,
    )


async def create_context(api_key: str, sensitivity: str = "medium") -> GadgetContext:
    """Create a per-print context. Free of charge; validates the API key."""
    level = CONFIDENCE_BY_SENSITIVITY.get(sensitivity, 3)
    payload = {"WarningConfidenceLevel": level, "PauseConfidenceLevel": level}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(
                CREATE_CONTEXT_URL,
                json=payload,
                headers={"X-API-Key": api_key},
            )
    except httpx.HTTPError as e:
        raise GadgetError(f"Connection failed: {type(e).__name__}") from e
    if resp.status_code != 200:
        raise _error_from_response(resp)
    try:
        body = resp.json()
        context_id = body["ContextId"]
        process_url = body["ProcessRequestUrl"]
    except (ValueError, KeyError, TypeError) as e:
        raise GadgetError("Unexpected createcontext response") from e
    return GadgetContext(
        context_id=context_id,
        process_url=process_url,
        fallback_url=body.get("FallbackProcessRequestUrl") or None,
    )


async def process_frame(process_url: str, jpeg: bytes) -> GadgetResult:
    """Upload one JPEG snapshot to a context's process URL."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(
                process_url,
                files={"image": ("snapshot.jpg", jpeg, "image/jpeg")},
            )
    except httpx.HTTPError as e:
        raise GadgetError(f"Connection failed: {type(e).__name__}") from e
    if resp.status_code != 200:
        err = _error_from_response(resp)
        if err.error_type is None and resp.status_code < 500:
            # A non-JSON 4xx is not a server outage; don't trigger a fallback switch.
            err.error_type = "OE_HTTP_ERROR"
        raise err
    try:
        body = resp.json()
    except ValueError as e:
        raise GadgetError("Unexpected process response (not JSON)", error_type="OE_HTTP_ERROR") from e
    if not isinstance(body, dict):
        raise GadgetError("Unexpected process response", error_type="OE_HTTP_ERROR")
    return parse_process_response(body)


async def cancel_context(context_id: str) -> None:
    """Best-effort cancel of a context we no longer need (e.g. connection test)."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            await client.post(f"{CANCEL_CONTEXT_URL}/{context_id}")
    except httpx.HTTPError:
        pass
