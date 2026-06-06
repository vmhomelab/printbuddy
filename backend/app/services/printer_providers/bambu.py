from __future__ import annotations

from typing import Any

from backend.app.services.bambu_mqtt import BambuMQTTClient


def create_bambu_client(printer: Any, **callbacks: Any) -> BambuMQTTClient:
    """Create the existing Bambu MQTT client through the provider factory seam."""

    return BambuMQTTClient(
        ip_address=printer.ip_address,
        serial_number=printer.serial_number,
        access_code=printer.access_code,
        model=printer.model,
        **callbacks,
    )
