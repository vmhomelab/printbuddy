"""Slicer "Device" tab dashboard served at /api/v1/vp-host/<id> (#52)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.app.api.routes.vp_device import _material_slots, _temperature_rows


@pytest.fixture
def no_sync():
    with patch(
        "backend.app.services.virtual_printer.virtual_printer_manager.sync_from_db",
        new=AsyncMock(),
    ):
        yield


async def _create_vp(client: AsyncClient, **body) -> dict:
    payload = {"name": "U1", "protocol": "moonraker", "enabled": True, **body}
    response = await client.post("/api/v1/virtual-printers", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


class TestDevicePage:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_host_url_serves_dashboard_without_key(self, async_client: AsyncClient, no_sync):
        vp = await _create_vp(async_client)
        base = vp["host_path"]

        for url in (base, f"{base}/"):
            response = await async_client.get(url)
            assert response.status_code == 200, url
            assert response.headers["content-type"].startswith("text/html")
            body = response.text
            assert f'src="{base}/device/app.js"' in body
            assert f'data-base="{base}"' in body
            assert "{{BASE}}" not in body

        js = await async_client.get(f"{base}/device/app.js")
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        css = await async_client.get(f"{base}/device/app.css")
        assert css.status_code == 200
        assert (await async_client.get(f"{base}/device/index.html")).status_code == 404
        assert (await async_client.get(f"{base}/device/..%2Fvp_device.py")).status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_state_shows_only_the_target_printer(self, async_client: AsyncClient, printer_factory, no_sync):
        await printer_factory(name="X1C")
        u1 = await printer_factory(name="Snapmaker U1", provider="klipper", model="Snapmaker U1")
        await printer_factory(name="Voron", provider="klipper")
        vp = await _create_vp(async_client, target_printer_id=u1.id)
        url = f"{vp['host_path']}/device/api/state"

        assert (await async_client.get(url)).status_code == 401
        assert (await async_client.get(url, headers={"X-API-Key": "nope"})).status_code == 401

        with patch("backend.app.services.printer_manager.printer_manager.get_status", return_value=None):
            response = await async_client.get(url, headers={"X-API-Key": vp["api_key"]})
            by_query = await async_client.get(f"{url}?apikey={vp['api_key']}")
            # A printer id from the client is ignored: no way to reach other printers.
            other = await async_client.get(f"{url}?printer_id=1", headers={"X-API-Key": vp["api_key"]})
        assert response.status_code == 200
        assert by_query.status_code == 200
        data = response.json()
        assert data["vp"]["id"] == vp["id"]
        assert "printers" not in data
        assert data["printer"]["id"] == u1.id
        assert data["printer"]["name"] == "Snapmaker U1"
        assert data["printer"]["connected"] is False
        assert data["printer"]["camera"]["stream_path"].endswith(f"/printers/{u1.id}/camera/stream")
        assert other.json()["printer"]["id"] == u1.id

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_state_without_target_printer(self, async_client: AsyncClient, printer_factory, no_sync):
        await printer_factory(name="Voron", provider="klipper")
        vp = await _create_vp(async_client)
        response = await async_client.get(f"{vp['host_path']}/device/api/state", headers={"X-API-Key": vp["api_key"]})
        assert response.status_code == 200
        assert response.json()["printer"] is None
        assert response.json()["vp"]["target_printer_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_inactive_target_is_not_shown(self, async_client: AsyncClient, printer_factory, db_session, no_sync):
        u1 = await printer_factory(name="U1", provider="klipper")
        vp = await _create_vp(async_client, target_printer_id=u1.id)
        u1.is_active = False
        await db_session.commit()
        response = await async_client.get(f"{vp['host_path']}/device/api/state", headers={"X-API-Key": vp["api_key"]})
        assert response.json()["printer"] is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_camera_token(self, async_client: AsyncClient, no_sync):
        vp = await _create_vp(async_client)
        url = f"{vp['host_path']}/device/api/camera-token"
        assert (await async_client.post(url)).status_code == 401
        response = await async_client.post(url, headers={"X-API-Key": vp["api_key"]})
        assert response.status_code == 200
        assert len(response.json()["token"]) > 20


class TestDeviceActions:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_actions_delegate_to_printer_routes(self, async_client: AsyncClient, printer_factory, no_sync):
        await printer_factory(name="Voron", provider="klipper")
        printer = await printer_factory(name="U1", provider="klipper")
        vp = await _create_vp(async_client, target_printer_id=printer.id)
        base = f"{vp['host_path']}/device/api/control"
        headers = {"X-API-Key": vp["api_key"]}
        ok = {"success": True}

        assert (await async_client.post(f"{base}/pause")).status_code == 401

        with (
            patch("backend.app.api.routes.printers.pause_print", new=AsyncMock(return_value=ok)) as pause,
            patch("backend.app.api.routes.printers.stop_print", new=AsyncMock(return_value=ok)) as stop,
            patch("backend.app.api.routes.printers.set_nozzle_temperature", new=AsyncMock(return_value=ok)) as nozzle,
            patch("backend.app.api.routes.printers.set_bed_temperature", new=AsyncMock(return_value=ok)) as bed,
            patch("backend.app.api.routes.printers.set_fan_speed", new=AsyncMock(return_value=ok)) as fan,
        ):
            assert (await async_client.post(f"{base}/pause", headers=headers)).status_code == 200
            assert (await async_client.post(f"{base}/stop", headers=headers)).status_code == 200
            response = await async_client.post(
                f"{base}/temperature", headers=headers, json={"heater": "nozzle", "target": 210}
            )
            assert response.status_code == 200
            assert (await async_client.post(f"{base}/cooldown", headers=headers)).status_code == 200
            response = await async_client.post(f"{base}/fan", headers=headers, json={"fan": "part", "speed": 150})
            assert response.status_code == 200

            bad = await async_client.post(f"{base}/temperature", headers=headers, json={"heater": "hotend"})
            assert bad.status_code == 400
            assert (await async_client.post(f"{base}/explode", headers=headers)).status_code == 404

        pause.assert_awaited_once()
        assert pause.await_args.kwargs["printer_id"] == printer.id
        stop.assert_awaited_once()
        assert [c.kwargs["target"] for c in nozzle.await_args_list] == [210, 0]
        assert [c.kwargs["target"] for c in bed.await_args_list] == [0]
        assert fan.await_args.kwargs["speed"] == 100  # clamped

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_actions_need_a_target_printer(self, async_client: AsyncClient, printer_factory, no_sync):
        await printer_factory(name="Voron", provider="klipper")
        vp = await _create_vp(async_client)
        headers = {"X-API-Key": vp["api_key"]}
        with patch("backend.app.api.routes.printers.pause_print", new=AsyncMock()) as pause:
            response = await async_client.post(f"{vp['host_path']}/device/api/control/pause", headers=headers)
            old_route = await async_client.post(f"{vp['host_path']}/device/api/printers/1/pause", headers=headers)
        assert response.status_code == 409
        assert response.json()["code"] == "no_target_printer"
        assert old_route.status_code in (404, 405)
        pause.assert_not_awaited()


class TestNormalisation:
    def test_multi_tool_klipper_temperatures(self):
        temps = {
            "nozzle": 170.0,
            "nozzle_target": 170,
            "bed": 60.04,
            "bed_target": 60,
            "extruder": {"temperature": 170.0, "target": 170},
            "extruder1": {"temperature": 140.2, "target": 0},
            "extruder2": {"temperature": 240.0, "target": 240},
            "heater_bed": {"temperature": 60.0, "target": 60},
            "temperature_sensor chamber": {"temperature": 34.5},
        }
        rows = _temperature_rows(temps)
        assert [(r["kind"], r["index"]) for r in rows] == [
            ("nozzle", 0),
            ("nozzle", 1),
            ("nozzle", 2),
            ("bed", None),
            ("chamber", None),
        ]
        assert rows[2]["target"] == 240
        assert rows[3]["current"] == 60.0

    def test_bambu_dual_nozzle_temperatures(self):
        rows = _temperature_rows({"nozzle": 220, "nozzle_target": 220, "nozzle_2": 30, "bed": 55, "chamber": 40})
        assert [(r["kind"], r["index"]) for r in rows] == [
            ("nozzle", 0),
            ("nozzle", 1),
            ("bed", None),
            ("chamber", None),
        ]
        assert _temperature_rows({"nozzle": 25, "bed": 22})[0]["index"] is None
        assert _temperature_rows(None) == []

    def test_material_slots(self):
        tray = lambda i, t, c: SimpleNamespace(id=i, tray_type=t, tray_sub_brands=None, tray_color=c)  # noqa: E731
        status = SimpleNamespace(
            tray_now=1,
            active_extruder=2,
            ams=[
                SimpleNamespace(
                    id=0, module_type="ams", tray=[tray(0, "PLA", "FF0000FF"), tray(1, "PETG", "00FF00FF")]
                ),
                SimpleNamespace(
                    id=1, module_type="snapmaker_u1", tray=[tray(2, "PLA", "#112233"), tray(3, None, None)]
                ),
            ],
            vt_tray=[],
            tool_slots=[],
        )
        slots = _material_slots(status)
        assert [(s["label"], s["color"], s["active"]) for s in slots] == [
            ("A1", "#ff0000", False),
            ("A2", "#00ff00", True),
            ("T2", "#112233", True),
        ]
