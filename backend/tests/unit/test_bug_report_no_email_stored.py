"""A bug report's email goes into the prefilled issue and is not kept locally.

Every submission was stored in ``bug_reports`` with the reporter's email, and
nothing ever read or purged that table. Printbuddy sends no report to a relay:
the email goes into the prefilled GitHub issue the reporter submits (it is how
the report gets answered); the local row keeps the outcome only, and the
emails already stored are cleared at startup.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from backend.app.services.bug_report import submit_report

EMAIL = "reporter@example.invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("screenshot", [None, "aGVsbG8="], ids=["no-screenshot", "screenshot"])
async def test_the_stored_report_has_no_email(screenshot):
    db = AsyncMock()
    db.add = MagicMock()
    session = MagicMock()
    session.return_value.__aenter__ = AsyncMock(return_value=db)
    session.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("backend.app.services.bug_report.async_session", session),
        patch("backend.app.services.bug_report._rate_limit_timestamps", []),
    ):
        result = await submit_report(
            description="It broke", reporter_email=EMAIL, screenshot_base64=screenshot, support_info=None
        )

    stored = db.add.call_args.args[0]
    assert stored.reporter_email is None
    assert EMAIL not in (stored.github_issue_url or "")
    body = parse_qs(urlparse(result["issue_url"]).query)["body"][0]
    assert EMAIL in body


@pytest.mark.asyncio
async def test_emails_stored_before_are_cleared():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import backend.app.models  # noqa: F401 - populate Base.metadata
    from backend.app.core.database import Base, _migrate_clear_bug_report_emails

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text(
                    "INSERT INTO bug_reports (description, reporter_email, status, email_sent) VALUES ('x', :e, 'failed', 0)"
                ),
                {"e": EMAIL},
            )
            await _migrate_clear_bug_report_emails(conn)
            await _migrate_clear_bug_report_emails(conn)  # again at the next start: harmless

            emails = (await conn.execute(text("SELECT reporter_email FROM bug_reports"))).scalars().all()
        assert emails == [None]
    finally:
        await engine.dispose()
