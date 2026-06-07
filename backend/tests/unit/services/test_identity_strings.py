"""Regression tests for outbound client identity strings."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.bambu_mqtt import BambuMQTTClient
from backend.app.services.mqtt_relay import MQTTRelayService
from backend.app.services.mqtt_smart_plug import MQTTSmartPlugService


def _client_id_from_mock(mock_client) -> str:
    _, kwargs = mock_client.call_args
    return kwargs["client_id"]


def test_printer_mqtt_client_id_identifies_as_printbuddy():
    with patch("backend.app.services.bambu_mqtt.mqtt.Client") as mock_client:
        client = BambuMQTTClient(
            ip_address="192.0.2.10",
            serial_number="TESTSERIAL",
            access_code="12345678",
        )
        client.connect(asyncio.new_event_loop())

    client_id = _client_id_from_mock(mock_client)
    assert client_id.startswith("printbuddy_TESTSERIAL_")
    assert "bambuddy" not in client_id.lower()


@pytest.mark.asyncio
async def test_mqtt_relay_client_id_identifies_as_printbuddy():
    with patch("backend.app.services.mqtt_relay.mqtt.Client") as mock_client:
        service = MQTTRelayService()
        await service._connect("mqtt.example", 1883, "", "", False)

    client_id = _client_id_from_mock(mock_client)
    assert client_id.startswith("printbuddy-")
    assert "bambuddy" not in client_id.lower()


@pytest.mark.asyncio
async def test_mqtt_smart_plug_client_id_identifies_as_printbuddy():
    with patch("backend.app.services.mqtt_smart_plug.mqtt.Client") as mock_client:
        service = MQTTSmartPlugService()
        service._broker = "mqtt.example"
        service._port = 1883
        await service._connect()

    client_id = _client_id_from_mock(mock_client)
    assert client_id.startswith("printbuddy-smartplug-")
    assert "bambuddy" not in client_id.lower()
