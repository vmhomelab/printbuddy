import pytest

from backend.app.services.panda_breath_mqtt import PandaBreathMQTTService


def test_panda_breath_applies_community_mqtt_topics():
    service = PandaBreathMQTTService()

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


def test_panda_breath_command_payloads_and_topics():
    service = PandaBreathMQTTService()

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
