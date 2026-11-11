"""RFID refresh reports what the printer said, and falls back to M620 R (#3206).

An X1C on X1Plus (base 01.08.02.00) answers ams_get_rfid with
``result: FAIL, reason: ERROR STATE``, yet the refresh returned success and
scheduled the K-profile re-apply. The refresh now waits for the answer, sends
the legacy ``M620 R<global tray>`` gcode Bambu Studio uses for printers without
the new protocol when ams_get_rfid is refused, and reports a refusal of both.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.bambu_mqtt import BambuMQTTClient
from backend.app.utils.printer_models import uses_legacy_rfid_refresh


def _client(answers: dict[str, dict | None], model: str = "X1C") -> tuple[BambuMQTTClient, list[dict]]:
    """A connected, idle client whose printer answers each command per ``answers``.

    ``answers`` maps a command name to the result fields the printer sends
    back, or None for no answer at all. Returns the client and the list of
    commands it published.
    """
    client = BambuMQTTClient(ip_address="10.0.0.1", serial_number="X1C", access_code="c", model=model)
    client._client = MagicMock()
    client.state.connected = True
    client.state.tray_now = 255
    sent: list[dict] = []

    def publish(_topic, body, **_kw):
        command = json.loads(body)["print"]
        sent.append(command)
        answer = answers.get(command["command"])
        if answer is not None:
            client._process_message({"print": {**command, **answer}})

    client._client.publish.side_effect = publish
    return client, sent


ACCEPT = {"result": "SUCCESS", "reason": "SUCCESS"}
REFUSE = {"result": "FAIL", "reason": "ERROR STATE"}


class TestRfidRefreshAck:
    @pytest.mark.asyncio
    async def test_accepted_sends_only_ams_get_rfid(self):
        client, sent = _client({"ams_get_rfid": ACCEPT})

        ok, message = await client.ams_refresh_tray(0, 3)

        assert ok
        assert message == "Refreshing AMS 0 tray 3"
        assert [c["command"] for c in sent] == ["ams_get_rfid"]
        assert sent[0]["ams_id"] == 0 and sent[0]["slot_id"] == 3

    @pytest.mark.asyncio
    async def test_refused_falls_back_to_m620_with_the_global_tray(self):
        client, sent = _client({"ams_get_rfid": REFUSE, "gcode_line": ACCEPT})

        ok, message = await client.ams_refresh_tray(2, 1)

        assert ok
        assert "legacy" in message
        assert [c["command"] for c in sent] == ["ams_get_rfid", "gcode_line"]
        assert sent[1]["param"] == "M620 R9\n"

    @pytest.mark.asyncio
    async def test_both_refused_reports_the_printer_reason(self):
        client, _ = _client({"ams_get_rfid": REFUSE, "gcode_line": REFUSE})

        ok, message = await client.ams_refresh_tray(0, 3)

        assert not ok
        assert "ERROR STATE" in message

    @pytest.mark.asyncio
    async def test_no_fallback_for_units_without_a_legacy_index(self):
        # AMS-HT (128+) has no M620 R index; only firmware with ams_get_rfid has one.
        client, sent = _client({"ams_get_rfid": REFUSE})

        ok, message = await client.ams_refresh_tray(128, 0)

        assert not ok
        assert "ERROR STATE" in message
        assert [c["command"] for c in sent] == ["ams_get_rfid"]

    @pytest.mark.asyncio
    async def test_no_fallback_on_a_newer_protocol_model(self):
        # Bambu Studio never sends M620 R to these; a refusal there is reported.
        client, sent = _client({"ams_get_rfid": REFUSE}, model="H2D")

        ok, message = await client.ams_refresh_tray(0, 1)

        assert not ok
        assert "ERROR STATE" in message
        assert [c["command"] for c in sent] == ["ams_get_rfid"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["RUNNING", "PAUSE", "PREPARE", "SLICING"])
    async def test_no_fallback_during_a_job(self, state):
        # A gcode_line would be executed inside the running print.
        client, sent = _client({"ams_get_rfid": REFUSE})
        client.state.state = state

        ok, _ = await client.ams_refresh_tray(0, 1)

        assert not ok
        assert [c["command"] for c in sent] == ["ams_get_rfid"]

    @pytest.mark.asyncio
    async def test_no_answer_counts_as_accepted(self):
        client, sent = _client({})

        client._rfid_ack_timeout = 0.1
        ok, _ = await client.ams_refresh_tray(0, 0)

        assert ok
        assert [c["command"] for c in sent] == ["ams_get_rfid"]
        assert client._pending_rfid_acks == {}

    @pytest.mark.asyncio
    async def test_unrelated_gcode_line_ack_is_not_taken_for_ours(self):
        client, _ = _client({"ams_get_rfid": REFUSE})
        client._process_message({"print": {"command": "gcode_line", "sequence_id": "0", **REFUSE}})

        client._rfid_ack_timeout = 0.1
        ok, _ = await client.ams_refresh_tray(0, 0)

        # ams_get_rfid refused, M620 R sent but unanswered -> accepted.
        assert ok


class TestRefreshRoute:
    @pytest.mark.asyncio
    async def test_refused_refresh_is_400_and_schedules_no_pa_reapply(self):
        from fastapi import HTTPException

        from backend.app.api.routes import printers as printers_routes

        client, _ = _client({"ams_get_rfid": REFUSE, "gcode_line": REFUSE})
        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = MagicMock(id=1)

        async def execute(*_a, **_kw):
            return result

        db.execute = execute

        with (
            patch.object(printers_routes, "printer_manager") as pm,
            patch.object(printers_routes, "spawn_background_task") as spawn,
        ):
            pm.get_client.return_value = client
            with pytest.raises(HTTPException) as exc:
                await printers_routes.refresh_ams_slot(1, 0, 3, None, db)

        assert exc.value.status_code == 400
        assert "ERROR STATE" in exc.value.detail
        spawn.assert_not_called()


class TestLegacyRfidModels:
    @pytest.mark.parametrize("model", ["X1C", "X1", "X1E", "P1P", "P1S", "A1", "A1 Mini", "BL-P001", "C12", "N1"])
    def test_legacy(self, model):
        assert uses_legacy_rfid_refresh(model)

    @pytest.mark.parametrize("model", ["H2D", "H2C", "H2S", "P2S", "A2L", "X2D", "O1D", "N7", "", None])
    def test_not_legacy(self, model):
        assert not uses_legacy_rfid_refresh(model)
