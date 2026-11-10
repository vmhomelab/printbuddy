"""Unit tests for the OctoEverywhere Gadget failure-detection provider (PB-35)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.app.services import octoeverywhere_gadget as gadget
from backend.app.services.failure_detection_camera import (
    CAPTURE_FAILED,
    NO_CAMERA,
    VIEWER_BUSY,
    capture_detection_frame,
)
from backend.app.services.octoeverywhere_detection import (
    NO_CAMERA_RETRY,
    OctoEverywhereDetectionService,
    PrinterDetectionState,
    parse_enabled_printers,
)

FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
SECRET_ID = "uYZkEP0g22nPZwtCj6ASWef9Lpmh81Ahs1mnAdw4Z7PlDFbOK6"
PROCESS_URL = f"https://gadget-eu.octoeverywhere.com/api/gadget/v1/process/{SECRET_ID}"
FALLBACK_URL = f"https://gadget-pv1-oeapi.octoeverywhere.com/api/gadget/v1/process/{SECRET_ID}"
CONTEXT = gadget.GadgetContext(context_id=SECRET_ID, process_url=PROCESS_URL, fallback_url=FALLBACK_URL)


def _settings(**overrides) -> dict:
    base = {
        "enabled": True,
        "api_key": "prod_TESTKEY",
        "has_api_key": True,
        "key_error": None,
        "sensitivity": "medium",
        "action": "pause",
        "poll_interval": 0,
        "enabled_printers": None,
        "notify_on_warning": True,
    }
    base.update(overrides)
    return base


def _result(**overrides) -> gadget.GadgetResult:
    base = {
        "print_quality": 9,
        "score": 5,
        "warning_suggested": False,
        "pause_suggested": False,
        "faster_inspection_suggested": False,
        "min_interval": 5,
        "recommended_interval": 20,
    }
    base.update(overrides)
    return gadget.GadgetResult(**base)


def _mock_transport(handler):
    """Patch target for httpx.AsyncClient that routes requests to ``handler``."""
    real = httpx.AsyncClient

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def _session_returning(printer):
    session = MagicMock()
    session.get = AsyncMock(return_value=printer)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


# ---------------------------------------------------------------- Gadget client


class TestGadgetClient:
    def test_parse_response_uses_documented_fields(self):
        r = gadget.parse_process_response(
            {
                "NextProcessIntervalSec": {"Minimum": 5, "Recommended": 20},
                "FasterInspectionSuggested": True,
                "PrintQuality": 3,
                "WarningSuggested": True,
                "PauseSuggested": False,
                "Score": 71,
            }
        )
        assert (r.print_quality, r.score, r.warning_suggested, r.pause_suggested) == (3, 71, True, False)
        assert r.faster_inspection_suggested is True
        assert (r.min_interval, r.recommended_interval) == (5, 20)

    def test_parse_response_defaults_missing_fields(self):
        r = gadget.parse_process_response({})
        assert r.faster_inspection_suggested is False
        assert r.warning_suggested is False and r.pause_suggested is False
        assert r.min_interval == 5
        assert r.recommended_interval == 20

    def test_parse_response_never_recommends_below_minimum(self):
        r = gadget.parse_process_response({"NextProcessIntervalSec": {"Minimum": 30, "Recommended": 10}})
        assert r.min_interval == 30
        assert r.recommended_interval == 30

    @pytest.mark.asyncio
    async def test_create_context_sends_key_and_confidence(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("X-API-Key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "ContextId": SECRET_ID,
                    "ProcessRequestUrl": PROCESS_URL,
                    "FallbackProcessRequestUrl": FALLBACK_URL,
                },
            )

        with patch.object(gadget.httpx, "AsyncClient", _mock_transport(handler)):
            ctx = await gadget.create_context("prod_KEY", "high")

        assert seen["url"] == gadget.CREATE_CONTEXT_URL
        assert seen["key"] == "prod_KEY"
        assert seen["body"] == {"WarningConfidenceLevel": 2, "PauseConfidenceLevel": 2}
        assert ctx == CONTEXT

    @pytest.mark.asyncio
    async def test_error_body_is_parsed_with_retry_after(self):
        def handler(request):
            return httpx.Response(
                429,
                json={"ErrorType": "OE_CONTEXT_RATE_LIMITED", "ErrorDetails": "slow down"},
                headers={"Retry-After": "12"},
            )

        with (
            patch.object(gadget.httpx, "AsyncClient", _mock_transport(handler)),
            pytest.raises(gadget.GadgetError) as exc,
        ):
            await gadget.process_frame(PROCESS_URL, FAKE_JPEG)

        assert exc.value.error_type == "OE_CONTEXT_RATE_LIMITED"
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 12

    @pytest.mark.asyncio
    async def test_process_uploads_multipart_jpeg_without_api_key(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["ctype"] = request.headers["content-type"]
            seen["has_key"] = "x-api-key" in request.headers
            seen["body"] = request.content
            return httpx.Response(
                200, json={"PrintQuality": 8, "NextProcessIntervalSec": {"Minimum": 5, "Recommended": 20}}
            )

        with patch.object(gadget.httpx, "AsyncClient", _mock_transport(handler)):
            r = await gadget.process_frame(PROCESS_URL, FAKE_JPEG)

        assert seen["ctype"].startswith("multipart/form-data")
        assert seen["has_key"] is False
        assert FAKE_JPEG in seen["body"]
        assert r.print_quality == 8

    @pytest.mark.asyncio
    async def test_connection_error_message_never_contains_context_url(self):
        def handler(request):
            raise httpx.ConnectError(f"cannot connect to {request.url}")

        with (
            patch.object(gadget.httpx, "AsyncClient", _mock_transport(handler)),
            pytest.raises(gadget.GadgetError) as exc,
        ):
            await gadget.process_frame(PROCESS_URL, FAKE_JPEG)

        assert exc.value.is_connection_failure
        assert SECRET_ID not in str(exc.value)

    @pytest.mark.asyncio
    async def test_non_json_4xx_is_not_treated_as_outage(self):
        def handler(request):
            return httpx.Response(413, text="too large")

        with (
            patch.object(gadget.httpx, "AsyncClient", _mock_transport(handler)),
            pytest.raises(gadget.GadgetError) as exc,
        ):
            await gadget.process_frame(PROCESS_URL, FAKE_JPEG)

        assert not exc.value.is_connection_failure


# ---------------------------------------------------------------- settings helpers


class TestParseEnabledPrinters:
    @pytest.mark.parametrize("raw", [None, "", "not json", '{"a": 1}', '["1"]', "[true]"])
    def test_invalid_or_empty_means_all(self, raw):
        assert parse_enabled_printers(raw) is None

    def test_int_list(self):
        assert parse_enabled_printers("[1, 3]") == [1, 3]


# ---------------------------------------------------------------- scheduling / scoping


def _printer_manager(statuses: dict, connected: set[int] | None = None):
    pm = MagicMock()
    pm.get_all_statuses.return_value = statuses
    pm.is_connected.side_effect = lambda pid: connected is None or pid in connected
    return pm


class TestPollScheduling:
    def _poll(self, svc, settings, pm):
        with (
            patch("backend.app.services.printer_manager.printer_manager", pm),
            patch.object(svc, "_check_printer", new=MagicMock()) as check,
            patch("backend.app.services.octoeverywhere_detection.asyncio.create_task") as create_task,
        ):
            create_task.return_value = MagicMock()
            svc._poll_once(settings)
        return check

    def test_only_enabled_printers_are_checked(self):
        svc = OctoEverywhereDetectionService()
        pm = _printer_manager(
            {
                1: MagicMock(state="RUNNING", task_name="a"),
                2: MagicMock(state="RUNNING", task_name="b"),
            }
        )
        check = self._poll(svc, _settings(enabled_printers=[2]), pm)
        assert [c.args[0] for c in check.call_args_list] == [2]
        assert set(svc._states) == {2}

    def test_disconnected_printer_is_skipped(self):
        svc = OctoEverywhereDetectionService()
        pm = _printer_manager({1: MagicMock(state="RUNNING", task_name="a")}, connected=set())
        check = self._poll(svc, _settings(), pm)
        check.assert_not_called()

    def test_finished_print_resets_state(self):
        svc = OctoEverywhereDetectionService()
        svc._states[1] = PrinterDetectionState(task_key="a", context=CONTEXT)
        pm = _printer_manager({1: MagicMock(state="FINISH", task_name="a")})
        self._poll(svc, _settings(), pm)
        assert 1 not in svc._states

    def test_paused_print_keeps_context_but_is_not_inspected(self):
        svc = OctoEverywhereDetectionService()
        svc._key_fp = "x"
        svc._states[1] = PrinterDetectionState(task_key="a", context=CONTEXT)
        pm = _printer_manager({1: MagicMock(state="PAUSE", task_name="a")})
        with patch("backend.app.services.octoeverywhere_detection._key_fingerprint", return_value="x"):
            check = self._poll(svc, _settings(), pm)
        check.assert_not_called()
        assert svc._states[1].context is CONTEXT

    def test_new_print_gets_fresh_state(self):
        svc = OctoEverywhereDetectionService()
        svc._key_fp = "x"  # pretend a key was already in use
        svc._states[1] = PrinterDetectionState(task_key="old", context=CONTEXT, pause=True)
        pm = _printer_manager({1: MagicMock(state="RUNNING", task_name="new")})
        with patch("backend.app.services.octoeverywhere_detection._key_fingerprint", return_value="x"):
            self._poll(svc, _settings(), pm)
        assert svc._states[1].task_key == "new"
        assert svc._states[1].context is None
        assert svc._states[1].pause is False

    def test_not_due_printer_is_not_checked(self):
        svc = OctoEverywhereDetectionService()
        svc._key_fp = "x"
        svc._states[1] = PrinterDetectionState(task_key="a", next_due=time.monotonic() + 60)
        pm = _printer_manager({1: MagicMock(state="RUNNING", task_name="a")})
        with patch("backend.app.services.octoeverywhere_detection._key_fingerprint", return_value="x"):
            check = self._poll(svc, _settings(), pm)
        check.assert_not_called()

    def test_account_block_pauses_all_checks(self):
        svc = OctoEverywhereDetectionService()
        svc._key_fp = "x"
        svc._account_block = {
            "error_type": "OE_FREE_USAGE_LIMIT_REACHED",
            "until": time.monotonic() + 60,
            "key_fp": "x",
        }
        pm = _printer_manager({1: MagicMock(state="RUNNING", task_name="a")})
        with patch("backend.app.services.octoeverywhere_detection._key_fingerprint", return_value="x"):
            check = self._poll(svc, _settings(), pm)
        check.assert_not_called()
        assert svc.get_status()["account_error"] == "OE_FREE_USAGE_LIMIT_REACHED"

    def test_new_api_key_clears_account_block_and_contexts(self):
        svc = OctoEverywhereDetectionService()
        svc._key_fp = "old"
        svc._states[1] = PrinterDetectionState(task_key="a", context=CONTEXT)
        svc._account_block = {"error_type": "OE_INVALID_API_KEY", "until": time.monotonic() + 60, "key_fp": "old"}
        pm = _printer_manager({1: MagicMock(state="RUNNING", task_name="a")})
        check = self._poll(svc, _settings(api_key="prod_NEW"), pm)
        assert svc._account_block is None
        assert svc._states[1].context is None
        check.assert_called_once()


# ---------------------------------------------------------------- one inspection


class TestCheckPrinter:
    async def _run(
        self, svc, state, settings, *, frame=(FAKE_JPEG, None), result=None, process_error=None, create=None
    ):
        printer = MagicMock(id=1)
        process = AsyncMock(side_effect=process_error) if process_error else AsyncMock(return_value=result or _result())
        create_mock = create or AsyncMock(return_value=CONTEXT)
        with (
            patch(
                "backend.app.services.octoeverywhere_detection.async_session", return_value=_session_returning(printer)
            ),
            patch(
                "backend.app.services.octoeverywhere_detection.capture_detection_frame",
                new=AsyncMock(return_value=frame),
            ),
            patch.object(gadget, "create_context", new=create_mock),
            patch.object(gadget, "process_frame", new=process),
            patch("backend.app.services.obico_actions.execute_action", new=AsyncMock()) as action,
        ):
            await svc._check_printer(1, state, settings)
        return create_mock, process, action

    @pytest.mark.asyncio
    async def test_no_camera_skips_api_and_backs_off(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a")
        create, process, action = await self._run(svc, state, _settings(), frame=(None, NO_CAMERA))
        create.assert_not_called()
        process.assert_not_called()
        assert state.last_issue == NO_CAMERA
        assert state.next_due >= time.monotonic() + NO_CAMERA_RETRY - 1

    @pytest.mark.asyncio
    async def test_context_created_once_and_reused(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a")
        create, process, _ = await self._run(svc, state, _settings(sensitivity="low"))
        create.assert_awaited_once_with("prod_TESTKEY", "low")
        process.assert_awaited_once_with(PROCESS_URL, FAKE_JPEG)
        create2, _, _ = await self._run(svc, state, _settings())
        create2.assert_not_called()
        assert state.frame_count == 2

    @pytest.mark.asyncio
    async def test_auto_interval_follows_recommended(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        await self._run(svc, state, _settings(poll_interval=0), result=_result(recommended_interval=40))
        assert 38 <= state.next_due - time.monotonic() <= 40

    @pytest.mark.asyncio
    async def test_fixed_interval_respects_minimum_and_faster_hint(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        await self._run(svc, state, _settings(poll_interval=5), result=_result(min_interval=15))
        assert 13 <= state.next_due - time.monotonic() <= 15
        await self._run(
            svc,
            state,
            _settings(poll_interval=60),
            result=_result(faster_inspection_suggested=True, recommended_interval=10),
        )
        assert 8 <= state.next_due - time.monotonic() <= 10

    @pytest.mark.asyncio
    async def test_warning_notifies_once_while_flag_stays_true(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        _, _, action = await self._run(svc, state, _settings(), result=_result(warning_suggested=True, print_quality=4))
        action.assert_awaited_once()
        assert action.await_args.args[1] == "notify"
        assert action.await_args.kwargs["source"] == "OctoEverywhere"
        assert action.await_args.kwargs["image_data"] == FAKE_JPEG
        _, _, action2 = await self._run(svc, state, _settings(), result=_result(warning_suggested=True))
        action2.assert_not_called()
        assert svc.get_status()["history"][0]["warning"] is True

    @pytest.mark.asyncio
    async def test_warning_notification_can_be_disabled(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        _, _, action = await self._run(
            svc, state, _settings(notify_on_warning=False), result=_result(warning_suggested=True)
        )
        action.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_runs_configured_action_once(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        _, _, action = await self._run(
            svc,
            state,
            _settings(action="pause_and_off"),
            result=_result(warning_suggested=True, pause_suggested=True, score=90, print_quality=1),
        )
        # Pause supersedes the warning: exactly one dispatch, with the configured action
        action.assert_awaited_once()
        assert action.await_args.args[1] == "pause_and_off"
        assert action.await_args.args[3] == pytest.approx(0.9)
        _, _, action2 = await self._run(
            svc, state, _settings(action="pause_and_off"), result=_result(pause_suggested=True)
        )
        action2.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_rearms_after_flag_clears(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT, pause=True)
        await self._run(svc, state, _settings(), result=_result(pause_suggested=False))
        _, _, action = await self._run(svc, state, _settings(), result=_result(pause_suggested=True))
        action.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_account_error_blocks_provider(self):
        svc = OctoEverywhereDetectionService()
        svc._key_fp = "x"
        state = PrinterDetectionState(task_key="a")
        err = gadget.GadgetError(
            "OE_FREE_USAGE_LIMIT_REACHED", error_type="OE_FREE_USAGE_LIMIT_REACHED", status_code=429
        )
        await self._run(svc, state, _settings(), create=AsyncMock(side_effect=err))
        assert svc._account_blocked()
        assert "OE_FREE_USAGE_LIMIT_REACHED" in svc.get_status()["last_error"]

    @pytest.mark.asyncio
    async def test_expired_context_stops_this_print(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        svc._states[1] = state
        err = gadget.GadgetError("OE_CONTEXT_EXPIRED", error_type="OE_CONTEXT_EXPIRED", status_code=410)
        await self._run(svc, state, _settings(), process_error=err)
        assert state.stopped_reason == "OE_CONTEXT_EXPIRED"
        assert svc.get_status()["per_printer"][1]["next_check_in"] is None

    @pytest.mark.asyncio
    async def test_rate_limit_waits_retry_after(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        err = gadget.GadgetError("x", error_type="OE_CONTEXT_RATE_LIMITED", status_code=429, retry_after=90)
        await self._run(svc, state, _settings(), process_error=err)
        assert state.next_due - time.monotonic() >= 88

    @pytest.mark.asyncio
    async def test_connection_failure_switches_to_fallback_url(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        await self._run(svc, state, _settings(), process_error=gadget.GadgetError("Connection failed: ConnectError"))
        assert state.using_fallback is True
        _, process, _ = await self._run(svc, state, _settings())
        process.assert_awaited_once_with(FALLBACK_URL, FAKE_JPEG)

    @pytest.mark.asyncio
    async def test_frame_error_does_not_switch_or_stop(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        err = gadget.GadgetError("OE_IMAGE_DECODE_FAILED", error_type="OE_IMAGE_DECODE_FAILED", status_code=400)
        await self._run(svc, state, _settings(), process_error=err)
        assert state.using_fallback is False
        assert state.stopped_reason is None
        assert not svc._account_blocked()

    @pytest.mark.asyncio
    async def test_status_never_exposes_context_secrets(self):
        svc = OctoEverywhereDetectionService()
        state = PrinterDetectionState(task_key="a", context=CONTEXT)
        svc._states[1] = state
        await self._run(svc, state, _settings(), result=_result(warning_suggested=True))
        dumped = json.dumps(svc.get_status())
        assert SECRET_ID not in dumped
        assert "prod_TESTKEY" not in dumped


class TestTestConnection:
    @pytest.mark.asyncio
    async def test_empty_key(self):
        res = await OctoEverywhereDetectionService().test_connection("")
        assert res["ok"] is False

    @pytest.mark.asyncio
    async def test_success_cancels_the_probe_context(self):
        with (
            patch.object(gadget, "create_context", new=AsyncMock(return_value=CONTEXT)),
            patch.object(gadget, "cancel_context", new=AsyncMock()) as cancel,
        ):
            res = await OctoEverywhereDetectionService().test_connection("prod_KEY")
        assert res == {"ok": True, "error_type": None, "error": None}
        cancel.assert_awaited_once_with(SECRET_ID)

    @pytest.mark.asyncio
    async def test_invalid_key_reports_error_type(self):
        err = gadget.GadgetError("OE_INVALID_API_KEY", error_type="OE_INVALID_API_KEY", status_code=401)
        with patch.object(gadget, "create_context", new=AsyncMock(side_effect=err)):
            res = await OctoEverywhereDetectionService().test_connection("prod_BAD")
        assert res["ok"] is False
        assert res["error_type"] == "OE_INVALID_API_KEY"


# ---------------------------------------------------------------- camera capture


def _camera_printer(**overrides):
    base = {
        "id": 1,
        "provider": "bambu",
        "external_camera_enabled": False,
        "external_camera_url": None,
        "external_camera_type": None,
        "external_camera_snapshot_url": None,
        "ip_address": "192.168.1.10",
        "access_code": "12345678",
        "model": "X1C",
        "provider_options": None,
    }
    base.update(overrides)
    return MagicMock(**base)


class TestCaptureDetectionFrame:
    @pytest.mark.asyncio
    async def test_non_bambu_printer_without_camera_reports_no_camera(self):
        printer = _camera_printer(provider="octoprint")
        with patch("backend.app.services.camera.capture_camera_frame_bytes", new=AsyncMock()) as fresh:
            frame, reason = await capture_detection_frame(printer)
        assert (frame, reason) == (None, NO_CAMERA)
        fresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_reuses_live_viewer_frame(self):
        with (
            patch("backend.app.api.routes.camera.try_get_active_buffered_frame", return_value=FAKE_JPEG),
            patch("backend.app.services.camera.capture_camera_frame_bytes", new=AsyncMock()) as fresh,
        ):
            frame, reason = await capture_detection_frame(_camera_printer())
        assert (frame, reason) == (FAKE_JPEG, None)
        fresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_never_opens_competing_socket_while_viewer_attached(self):
        with (
            patch("backend.app.api.routes.camera.try_get_active_buffered_frame", return_value=None),
            patch("backend.app.api.routes.camera.is_stream_active", return_value=True),
            patch("backend.app.services.camera.capture_camera_frame_bytes", new=AsyncMock()) as fresh,
        ):
            frame, reason = await capture_detection_frame(_camera_printer())
        assert (frame, reason) == (None, VIEWER_BUSY)
        fresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_bambu_fresh_capture(self):
        with (
            patch("backend.app.api.routes.camera.try_get_active_buffered_frame", return_value=None),
            patch("backend.app.api.routes.camera.is_stream_active", return_value=False),
            patch("backend.app.services.camera.capture_camera_frame_bytes", new=AsyncMock(return_value=FAKE_JPEG)),
        ):
            assert await capture_detection_frame(_camera_printer()) == (FAKE_JPEG, None)

    @pytest.mark.asyncio
    async def test_external_camera_used_for_any_provider(self):
        printer = _camera_printer(
            provider="octoprint",
            external_camera_enabled=True,
            external_camera_url="http://cam.local/stream",
            external_camera_type="mjpeg",
        )
        with (
            patch("backend.app.api.routes.camera.try_get_active_buffered_frame", return_value=None),
            patch("backend.app.api.routes.camera.is_stream_active", return_value=False),
            patch("backend.app.services.external_camera.capture_frame", new=AsyncMock(return_value=FAKE_JPEG)) as ext,
        ):
            assert await capture_detection_frame(printer) == (FAKE_JPEG, None)
        assert ext.await_args.args[0] == "http://cam.local/stream"

    @pytest.mark.asyncio
    async def test_failed_capture(self):
        with (
            patch("backend.app.api.routes.camera.try_get_active_buffered_frame", return_value=None),
            patch("backend.app.api.routes.camera.is_stream_active", return_value=False),
            patch("backend.app.services.camera.capture_camera_frame_bytes", new=AsyncMock(return_value=None)),
        ):
            assert await capture_detection_frame(_camera_printer()) == (None, CAPTURE_FAILED)
