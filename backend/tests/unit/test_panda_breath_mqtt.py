import json

import pytest

from backend.app.schemas.settings import AppSettings
from backend.app.services.panda_breath_mqtt import PandaBreathMQTTService


def test_panda_breath_settings_default_to_native_topic():
    settings = AppSettings()

    assert settings.panda_breath_topic_prefix == "panda_breath"


def test_panda_breath_applies_community_mqtt_topics():
    service = PandaBreathMQTTService()
    service.topic_prefix = "panda_breath_mod"

    service.apply_message("ist", "42.5")
    service.apply_message("soll", "45")
    service.apply_message("panda_modus", "Automatik")
    service.apply_message("status", "Bereit")
    service.apply_message("panda_power", "ON")
    service.apply_message("slicer_priority_mode", "OFF")

    status = service.get_status()
    assert status["topic_prefix"] == "panda_breath_mod"
    assert status["state"]["chamber_actual"] == 42.5
    assert status["state"]["chamber_target"] == 45.0
    assert status["state"]["mode"] == "Automatik"
    assert status["state"]["status"] == "Bereit"
    assert status["state"]["power_on"] is True
    assert status["state"]["slicer_priority_mode"] is False
    assert status["state"]["last_seen"] is not None


def test_panda_breath_applies_native_state_json_from_device_payloads():
    service = PandaBreathMQTTService()

    service.apply_message(
        "9C139E456884/state",
        json.dumps(
            {
                "chamber_temp": 36.5,
                "work_on": "ON",
                "mode": "auto mode",
                "filament_drying_mode": "petg",
                "target_temp": 45,
                "filter_temp": 60,
                "heater_temp": 48,
                "custom_temp": 50,
                "custom_timer": 4,
                "drying_remaining_min": 120,
                "drying_running": "OFF",
                "printer_sn": "01S00C000000000",
                "printer_bind": "bind",
                "printer_ip": "192.168.1.55",
                "printer_name": "P1S",
            }
        ),
    )
    service.apply_message("9C139E456884/availability", "online")

    status = service.get_status()
    assert status["topic_prefix"] == "panda_breath"
    assert status["device_id"] == "9C139E456884"
    assert status["availability"] == "online"
    assert status["connected"] is True
    assert status["state"]["chamber_actual"] == 36.5
    assert status["state"]["work_on"] is True
    assert status["state"]["mode"] == "auto mode"
    assert status["state"]["filament_drying_mode"] == "petg"
    assert status["state"]["chamber_target"] == 45.0
    assert status["state"]["filter_activation_temp"] == 60.0
    assert status["state"]["heater_trigger_temp"] == 48.0
    assert status["state"]["custom_temp"] == 50.0
    assert status["state"]["custom_timer_hours"] == 4.0
    assert status["state"]["drying_remaining_min"] == 120.0
    assert status["state"]["drying_running"] is False
    assert status["state"]["printer_sn"] == "01S00C000000000"
    assert status["state"]["printer_ip"] == "192.168.1.55"
    assert status["state"]["printer_name"] == "P1S"
    assert status["state"]["raw"]["state_json"]["target_temp"] == 45
    assert status["devices"]["9C139E456884"]["chamber_actual"] == 36.5
    assert status["devices"]["9C139E456884"]["availability"] == "online"


def test_panda_breath_tracks_multiple_native_devices_independently():
    service = PandaBreathMQTTService()

    service.apply_message("DEVICE_A/state", json.dumps({"chamber_temp": 31.2, "target_temp": 45, "mode": "auto mode"}))
    service.apply_message("DEVICE_A/availability", "online")
    service.apply_message(
        "DEVICE_B/state", json.dumps({"chamber_temp": 42.8, "target_temp": 55, "mode": "filament drying"})
    )
    service.apply_message("DEVICE_B/availability", "offline")

    status = service.get_status()

    assert status["devices"]["DEVICE_A"]["chamber_actual"] == 31.2
    assert status["devices"]["DEVICE_A"]["chamber_target"] == 45.0
    assert status["devices"]["DEVICE_A"]["mode"] == "auto mode"
    assert status["devices"]["DEVICE_A"]["availability"] == "online"
    assert status["devices"]["DEVICE_B"]["chamber_actual"] == 42.8
    assert status["devices"]["DEVICE_B"]["chamber_target"] == 55.0
    assert status["devices"]["DEVICE_B"]["mode"] == "filament drying"
    assert status["devices"]["DEVICE_B"]["availability"] == "offline"
    assert status["state"]["device_id"] == "DEVICE_B"


def test_panda_breath_command_payloads_and_topics():
    service = PandaBreathMQTTService()
    service.topic_prefix = "panda_breath_mod"

    assert service.COMMAND_TOPICS["manual"] == "manual/set"
    assert service.COMMAND_TOPICS["auto"] == "auto/set"
    assert service.COMMAND_TOPICS["drying"] == "drying/set"
    assert service.COMMAND_TOPICS["stop"] == "heizung_stop/set"
    assert service.COMMAND_TOPICS["unlock"] == "unlock/set"
    assert service.COMMAND_TOPICS["chamber_target"] == "soll/set"

    assert service._payload_for_command("manual", None) == "PRESS"
    assert service._payload_for_command("power", True) == "ON"
    assert service._payload_for_command("slicer_priority_mode", "off") == "OFF"
    assert service._payload_for_command("chamber_target", 50) == "50"

    with pytest.raises(ValueError):
        service._payload_for_command("chamber_target", None)


def test_panda_breath_native_command_topic_and_payload():
    service = PandaBreathMQTTService()
    service.apply_message("9C139E456884/availability", "online")

    topic, payload = service._command_topic_payload("chamber_target", 50)
    assert topic == "panda_breath/9C139E456884/command"
    assert json.loads(payload) == {"target_temp": 50}

    topic, payload = service._command_topic_payload("mode", "filament drying")
    assert topic == "panda_breath/9C139E456884/command"
    assert json.loads(payload) == {"mode": "filament drying"}

    topic, payload = service._command_topic_payload("chamber_target", 45, device_id="DEVICE_B")
    assert topic == "panda_breath/DEVICE_B/command"
    assert json.loads(payload) == {"target_temp": 45}

    topic, payload = service._command_topic_payload("stop", None)
    assert topic == "panda_breath/9C139E456884/command"
    assert json.loads(payload) == {"work_on": "OFF"}


def test_panda_breath_native_command_requires_device_id_when_prefix_is_root():
    service = PandaBreathMQTTService()

    with pytest.raises(ValueError, match="device id is unknown"):
        service._command_topic_payload("chamber_target", 50)


def test_panda_breath_native_full_device_prefix_can_publish_before_state_seen():
    service = PandaBreathMQTTService()
    service.topic_prefix = "panda_breath/9C139E456884"

    topic, payload = service._command_topic_payload("filter_temp", 70)
    assert topic == "panda_breath/9C139E456884/command"
    assert json.loads(payload) == {"filter_temp": 70}
