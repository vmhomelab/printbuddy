"""Unit tests for bug report service and route."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBugReportService:
    """Tests for bug_report.submit_report()."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_submit_prepares_github_issue_without_external_relay(self):
        """Preparing a report returns a prefilled GitHub issue URL and performs no outbound relay call."""
        from backend.app.services.bug_report import submit_report

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with (
            patch("backend.app.services.bug_report.async_session") as mock_session,
            patch("backend.app.services.bug_report._rate_limit_timestamps", []),
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await submit_report(
                description="Test bug",
                reporter_email="user@test.com",
                screenshot_base64="abc123",
                support_info={"app_version": "1.2.3", "recent_logs": "sanitized log line"},
            )

        assert result["success"] is True
        assert result["issue_number"] is None
        assert result["issue_url"].startswith("https://github.com/vmhomelab/Printbuddy/issues/new?")
        assert "Test+bug" in result["issue_url"]
        assert "sanitized+log+line" in result["issue_url"]
        assert "screenshot" in result["message"].lower()
        mock_db.add.assert_called_once()
        saved_report = mock_db.add.call_args.args[0]
        assert saved_report.status == "prepared"
        assert saved_report.github_issue_number is None
        assert saved_report.email_sent is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_submit_rate_limited(self):
        """Returns failure when rate limit exceeded."""
        import time

        from backend.app.services.bug_report import submit_report

        timestamps = [time.time()] * 5  # Already at limit

        with patch("backend.app.services.bug_report._rate_limit_timestamps", timestamps):
            result = await submit_report(
                description="Test",
                reporter_email=None,
                screenshot_base64=None,
                support_info=None,
            )

        assert result["success"] is False
        assert "Rate limit" in result["message"]


class TestStartLogging:
    """Tests for the start-logging endpoint handler."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_enables_debug_when_not_already_enabled(self):
        """Debug logging is enabled and printers are pushed."""
        from backend.app.api.routes.bug_report import start_logging

        apply_calls = []
        mock_db = AsyncMock()

        with (
            patch("backend.app.api.routes.bug_report.async_session") as mock_session,
            patch("backend.app.api.routes.bug_report._get_debug_setting", return_value=(False, None)),
            patch("backend.app.api.routes.bug_report._set_debug_setting", new_callable=AsyncMock) as mock_set,
            patch(
                "backend.app.api.routes.bug_report._apply_log_level",
                side_effect=lambda v: apply_calls.append(v),
            ),
            patch("backend.app.api.routes.bug_report.printer_manager") as mock_pm,
        ):
            mock_pm._clients = {"printer1": MagicMock()}
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await start_logging()

        assert result.started is True
        assert result.was_debug is False
        assert apply_calls == [True]
        mock_set.assert_called_once()
        mock_pm.request_status_update.assert_called_once_with("printer1")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_skips_enable_when_already_debug(self):
        """Debug logging not toggled when already enabled."""
        mock_db = AsyncMock()

        from backend.app.api.routes.bug_report import start_logging

        with (
            patch("backend.app.api.routes.bug_report.async_session") as mock_session,
            patch("backend.app.api.routes.bug_report._get_debug_setting", return_value=(True, None)),
            patch("backend.app.api.routes.bug_report._set_debug_setting", new_callable=AsyncMock) as mock_set,
            patch("backend.app.api.routes.bug_report._apply_log_level") as mock_apply,
            patch("backend.app.api.routes.bug_report.printer_manager") as mock_pm,
        ):
            mock_pm._clients = {}
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await start_logging()

        assert result.started is True
        assert result.was_debug is True
        mock_apply.assert_not_called()
        mock_set.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_pushes_all_connected_printers(self):
        """Sends status update request to all connected printers."""
        mock_db = AsyncMock()

        from backend.app.api.routes.bug_report import start_logging

        with (
            patch("backend.app.api.routes.bug_report.async_session") as mock_session,
            patch("backend.app.api.routes.bug_report._get_debug_setting", return_value=(True, None)),
            patch("backend.app.api.routes.bug_report._set_debug_setting", new_callable=AsyncMock),
            patch("backend.app.api.routes.bug_report._apply_log_level"),
            patch("backend.app.api.routes.bug_report.printer_manager") as mock_pm,
        ):
            mock_pm._clients = {"printer1": MagicMock(), "printer2": MagicMock()}
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            await start_logging()

        assert mock_pm.request_status_update.call_count == 2


class TestStopLogging:
    """Tests for the stop-logging endpoint handler."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_collects_logs_and_restores_level(self):
        """Collects logs and restores log level when was_debug=False."""
        from backend.app.api.routes.bug_report import stop_logging

        apply_calls = []
        mock_db = AsyncMock()

        with (
            patch("backend.app.api.routes.bug_report.async_session") as mock_session,
            patch("backend.app.api.routes.bug_report._set_debug_setting", new_callable=AsyncMock) as mock_set,
            patch(
                "backend.app.api.routes.bug_report._apply_log_level",
                side_effect=lambda v: apply_calls.append(v),
            ),
            patch("backend.app.api.routes.bug_report._get_recent_sanitized_logs", return_value="DEBUG log line"),
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await stop_logging(was_debug=False)

        assert result.logs == "DEBUG log line"
        assert apply_calls == [False]
        mock_set.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_skips_restore_when_was_debug(self):
        """Does not restore log level when was_debug=True."""
        from backend.app.api.routes.bug_report import stop_logging

        with (
            patch("backend.app.api.routes.bug_report.async_session") as mock_session,
            patch("backend.app.api.routes.bug_report._set_debug_setting", new_callable=AsyncMock) as mock_set,
            patch("backend.app.api.routes.bug_report._apply_log_level") as mock_apply,
            patch("backend.app.api.routes.bug_report._get_recent_sanitized_logs", return_value="logs"),
        ):
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await stop_logging(was_debug=True)

        assert result.logs == "logs"
        mock_apply.assert_not_called()
        mock_set.assert_not_called()


class TestSubmitBugReportRoute:
    """Tests for the submit_bug_report route handler."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_uses_provided_debug_logs(self):
        """When debug_logs is provided, it is used as recent_logs."""
        from backend.app.api.routes.bug_report import BugReportRequest, submit_bug_report

        report = BugReportRequest(
            description="Test bug",
            debug_logs="pre-collected debug logs",
        )

        with (
            patch("backend.app.api.routes.bug_report._collect_support_info", return_value={"version": "1.0"}),
            patch("backend.app.api.routes.bug_report.submit_report", new_callable=AsyncMock) as mock_submit,
        ):
            mock_submit.return_value = {
                "success": True,
                "message": "Created",
                "issue_url": "https://github.com/vmhomelab/Printbuddy/issues/1",
                "issue_number": 1,
            }

            result = await submit_bug_report(report)

        assert result.success is True
        call_kwargs = mock_submit.call_args[1]
        assert call_kwargs["support_info"]["recent_logs"] == "pre-collected debug logs"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_no_logs_when_debug_logs_not_provided(self):
        """When debug_logs is None, recent_logs is not added."""
        from backend.app.api.routes.bug_report import BugReportRequest, submit_bug_report

        report = BugReportRequest(description="Test bug")

        with (
            patch("backend.app.api.routes.bug_report._collect_support_info", return_value={"version": "1.0"}),
            patch("backend.app.api.routes.bug_report.submit_report", new_callable=AsyncMock) as mock_submit,
        ):
            mock_submit.return_value = {
                "success": True,
                "message": "Created",
                "issue_url": None,
                "issue_number": None,
            }

            await submit_bug_report(report)

        call_kwargs = mock_submit.call_args[1]
        assert "recent_logs" not in call_kwargs["support_info"]


class TestRateLimit:
    """Tests for rate limiting in bug report service."""

    def test_check_rate_limit_allows_first(self):
        """First request within window is allowed."""
        from backend.app.services.bug_report import _check_rate_limit

        with patch("backend.app.services.bug_report._rate_limit_timestamps", []):
            assert _check_rate_limit() is True

    def test_check_rate_limit_blocks_at_max(self):
        """Requests at max limit are blocked."""
        import time

        from backend.app.services.bug_report import _check_rate_limit

        now = time.time()
        timestamps = [now] * 5

        with patch("backend.app.services.bug_report._rate_limit_timestamps", timestamps):
            assert _check_rate_limit() is False

    def test_check_rate_limit_clears_old(self):
        """Old timestamps outside window are cleared."""
        import time

        from backend.app.services.bug_report import _check_rate_limit

        old_time = time.time() - 7200  # 2 hours ago
        timestamps = [old_time] * 5

        with patch("backend.app.services.bug_report._rate_limit_timestamps", timestamps):
            assert _check_rate_limit() is True
