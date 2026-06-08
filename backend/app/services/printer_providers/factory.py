from __future__ import annotations

from typing import Any

from backend.app.services.printer_providers.bambu import create_bambu_client
from backend.app.services.printer_providers.moonraker import create_moonraker_client
from backend.app.services.printer_providers.prusaconnect import create_prusa_connect_mobile_client
from backend.app.services.printer_providers.prusalink import create_prusalink_client

SUPPORTED_PROVIDERS = {"bambu", "klipper", "mainsail", "fluidd", "prusalink", "prusaconnect"}
MOONRAKER_PROVIDERS = {"klipper", "mainsail", "fluidd"}


def normalize_provider(provider: object | None) -> str:
    if provider is None or not isinstance(provider, str):
        return "bambu"

    normalized = provider.strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported printer provider: {provider!r}")
    return normalized


def create_printer_client(printer: Any, **callbacks: Any) -> Any:
    """Create a provider-specific printer client.

    Bambu remains the default for backwards compatibility. Klipper/Mainsail/
    Fluidd all use Moonraker because those are UIs on top of a
    Moonraker-enabled Klipper printer. PrusaLink uses Prusa's local HTTP API;
    Prusa Connect Mobile uses Prusa's cloud mobile API.
    """

    provider = normalize_provider(getattr(printer, "provider", "bambu"))
    if provider == "bambu":
        return create_bambu_client(printer, **callbacks)
    if provider in MOONRAKER_PROVIDERS:
        return create_moonraker_client(printer, **callbacks)
    if provider == "prusalink":
        return create_prusalink_client(printer, **callbacks)
    if provider == "prusaconnect":
        return create_prusa_connect_mobile_client(printer, **callbacks)
    raise ValueError(f"Unsupported printer provider: {provider!r}")
