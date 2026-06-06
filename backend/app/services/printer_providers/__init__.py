"""Printer provider adapters for Printbuddy.

Bambu support is inherited from Bambuddy. Klipper and Mainsail use the Moonraker API
surface and are introduced behind this provider boundary so the rest of the app can
move away from hard-coded Bambu MQTT assumptions incrementally.
"""

from backend.app.services.printer_providers.factory import SUPPORTED_PROVIDERS, create_printer_client

__all__ = ["SUPPORTED_PROVIDERS", "create_printer_client"]
