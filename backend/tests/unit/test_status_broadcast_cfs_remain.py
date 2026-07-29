from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app import main


def _state_with_cfs_remain(remain: int):
    return SimpleNamespace(
        connected=True,
        state="IDLE",
        progress=0,
        layer_num=0,
        temperatures={},
        stg_cur=0,
        cooling_fan_speed=None,
        big_fan1_speed=None,
        big_fan2_speed=None,
        chamber_light=None,
        active_extruder=None,
        tray_now=0,
        door_open=None,
        raw_data={
            "ams": [
                {
                    "id": 0,
                    "name": "CFS T1",
                    "module_type": "cfs",
                    "dry_time": 0,
                    "tray": [
                        {
                            "id": 0,
                            "slot": "T1A",
                            "tray_type": "PLA",
                            "tray_color": "#0A2989",
                            "remain": remain,
                            "active": True,
                            "state": 11,
                            "vendor": "unknown",
                        }
                    ],
                }
            ]
        },
    )


@pytest.mark.asyncio
async def test_printer_status_broadcasts_when_cfs_remain_changes():
    """CFS remain_len updates must reach the UI even if material/state stay stable."""

    main._last_status_broadcast.pop(4242, None)

    with (
        patch.object(main, "mqtt_relay") as mqtt_relay,
        patch.object(main, "printer_manager") as printer_manager,
        patch.object(main, "notification_service") as notification_service,
        patch.object(main, "smart_plug_manager") as smart_plug_manager,
        patch.object(main.ws_manager, "send_printer_status", new_callable=AsyncMock) as send_status,
        patch.object(main, "printer_state_to_dict", return_value={"connected": True}) as _state_to_dict,
    ):
        mqtt_relay.on_printer_status = AsyncMock()
        printer_manager.get_printer.return_value = None
        printer_manager.get_model.return_value = "K2 Plus"
        notification_service.on_print_progress = AsyncMock()
        smart_plug_manager.handle_print_state_change = AsyncMock()

        await main.on_printer_status_change(4242, _state_with_cfs_remain(100))
        await main.on_printer_status_change(4242, _state_with_cfs_remain(34))

    assert send_status.await_count == 2
