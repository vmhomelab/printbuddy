from backend.app.services.printer_manager import supports_chamber_temp


def test_elegoo_centauri_carbon_supports_chamber_temp():
    assert supports_chamber_temp("Centauri Carbon") is True
    assert supports_chamber_temp("Elegoo Centauri Carbon") is True
    assert supports_chamber_temp("centauri-carbon") is True


def test_bambu_models_without_real_chamber_sensor_remain_filtered():
    assert supports_chamber_temp("P1S") is False
    assert supports_chamber_temp("A1 Mini") is False
