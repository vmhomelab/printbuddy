"""Bug report service — prepares a GitHub issue URL without using an external relay."""

import json
import time
from urllib.parse import urlencode

from backend.app.core.config import GITHUB_REPO
from backend.app.core.database import async_session
from backend.app.models.bug_report import BugReport

# Rate limiting: max 5 prepared reports per hour
_rate_limit_window = 3600
_rate_limit_max = 5
_rate_limit_timestamps: list[float] = []


def _check_rate_limit() -> bool:
    """Check if rate limit allows a new report. Returns True if allowed."""
    now = time.time()
    _rate_limit_timestamps[:] = [t for t in _rate_limit_timestamps if now - t < _rate_limit_window]
    if len(_rate_limit_timestamps) >= _rate_limit_max:
        return False
    _rate_limit_timestamps.append(now)
    return True


def _format_support_info(support_info: dict | None) -> str:
    """Format sanitized support information for a GitHub issue body."""
    if not support_info:
        return "_No support information collected._"

    return "```json\n" + json.dumps(support_info, indent=2, sort_keys=True, default=str) + "\n```"


def _build_issue_body(
    description: str,
    reporter_email: str | None,
    screenshot_base64: str | None,
    support_info: dict | None,
) -> str:
    """Build the markdown body for a manually submitted GitHub issue."""
    email_section = reporter_email or "_Not provided._"
    screenshot_section = (
        "A screenshot was attached in the app, but automatic uploads are disabled. "
        "Please attach the screenshot manually to this GitHub issue."
        if screenshot_base64
        else "_No screenshot provided._"
    )

    return f"""## Bug description
{description}

## Reporter contact
{email_section}

## Screenshot
{screenshot_section}

## Support information
{_format_support_info(support_info)}
"""


def _build_issue_url(description: str, body: str) -> str:
    """Build a prefilled GitHub issue URL for manual submission."""
    title_seed = " ".join(description.split())[:80] or "Bug report"
    return f"https://github.com/{GITHUB_REPO}/issues/new?" + urlencode(
        {
            "title": f"Bug report: {title_seed}",
            "body": body,
        }
    )


async def submit_report(
    description: str,
    reporter_email: str | None,
    screenshot_base64: str | None,
    support_info: dict | None,
) -> dict:
    """Prepare a bug report for manual GitHub submission.

    This intentionally does not contact a hosted relay or create an issue with
    a PAT. The app returns a prefilled GitHub issue URL so the user can review
    and submit the report themselves.
    """
    if not _check_rate_limit():
        return {
            "success": False,
            "message": "Rate limit exceeded. Please try again later.",
            "issue_url": None,
            "issue_number": None,
        }

    issue_body = _build_issue_body(description, reporter_email, screenshot_base64, support_info)
    issue_url = _build_issue_url(description, issue_body)

    async with async_session() as db:
        report = BugReport(
            description=description,
            reporter_email=reporter_email,
            github_issue_number=None,
            # The full prefilled URL can exceed the DB column size; keep the
            # stable issue creation endpoint in history and return the full URL
            # only to the user in the response.
            github_issue_url=f"https://github.com/{GITHUB_REPO}/issues/new",
            status="prepared",
            email_sent=False,
        )
        db.add(report)
        await db.commit()

    message = "Bug report prepared. Review and submit it on GitHub."
    if screenshot_base64:
        message += " Please attach your screenshot manually on GitHub."

    return {
        "success": True,
        "message": message,
        "issue_url": issue_url,
        "issue_number": None,
    }
