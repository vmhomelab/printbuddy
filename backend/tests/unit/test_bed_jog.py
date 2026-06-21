"""Unit tests for the bed-jog and home-axes endpoints (#791).

Tests:
  POST /api/v1/printers/{printer_id}/bed-jog?distance=<mm>&force=<bool>
  POST /api/v1/printers/{printer_id}/home-axes?axes=<z|xy|all>
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient


class TestBedJogAPI:
    @pytest.mark.asyncio
    async def test_bed_jog_not_found(self, async_client: AsyncClient):
        response = await async_client.post("/api/v1/printers/99999/bed-jog?distance=10")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_bed_jog_zero_distance_rejected(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="P1")
        response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=0")
        assert response.status_code == 400
        assert "distance" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_bed_jog_too_large_rejected(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="P1")
        response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=500")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_bed_jog_not_connected(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Disconnected")
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = None
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=10")
            assert response.status_code == 400
            assert "not connected" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_bed_jog_send_failure(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="P1")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = False
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=10")
            assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_bed_jog_success_without_force(self, async_client: AsyncClient, printer_factory):
        """When force=false the M211 guard lines must not be emitted."""
        printer = await printer_factory(name="P1")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=10&force=false")
            assert response.status_code == 200
            sent_gcode = mock_client.send_gcode.call_args[0][0]
            assert "G91" in sent_gcode
            assert "G1 Z10.00" in sent_gcode
            assert "G90" in sent_gcode
            assert "M211" not in sent_gcode

    @pytest.mark.asyncio
    async def test_bed_jog_success_with_force(self, async_client: AsyncClient, printer_factory):
        """force=true must wrap the move in M211 S0 / M211 S1."""
        printer = await printer_factory(name="P1")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=-5&force=true")
            assert response.status_code == 200
            sent_gcode = mock_client.send_gcode.call_args[0][0]
            lines = sent_gcode.splitlines()
            assert lines[0] == "M211 S0"
            assert lines[-1] == "M211 S1"
            assert "G1 Z-5.00" in sent_gcode

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", ["X1C", "P1S", "H2D", "H2S", "H2C", "P2S"])
    async def test_bed_jog_bed_on_z_models_pass_distance_through(
        self, async_client: AsyncClient, printer_factory, model
    ):
        """On bed-on-Z printers the UI's signed distance maps directly to the
        G-code Z value — UI "Up" (negative) → bed up (G1 Z-) → less gap."""
        printer = await printer_factory(name=f"Test-{model}", model=model)
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=-10")
            assert response.status_code == 200
            sent_gcode = mock_client.send_gcode.call_args[0][0]
            # Negative distance from the UI → negative Z in the G-code: bed moves up.
            assert "G1 Z-10.00" in sent_gcode, f"{model}: expected G1 Z-10.00 in gcode, got {sent_gcode!r}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "model",
        ["A1", "A1 Mini", "A1MINI", "A1-MINI", "N1", "N2S"],  # display names + internal codes
    )
    async def test_bed_jog_a1_models_invert_z_sign(self, async_client: AsyncClient, printer_factory, model):
        """#1334 regression: on bed-slinger A1 / A1 Mini the Z axis is the
        TOOLHEAD, not the bed. The frontend sends negative distance for "Up"
        (decrease gap) expecting bed-on-Z semantics, but ``G1 Z-`` on A1
        drives the nozzle DOWN into the bed. The backend must invert the
        sign on these models so "Up" still decreases the gap by raising the
        toolhead (G1 Z+) rather than crashing it."""
        printer = await printer_factory(name=f"Test-{model}", model=model)
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            # UI sends -10 for "Up" → backend must emit G1 Z+10 on A1.
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=-10")
            assert response.status_code == 200
            sent_gcode = mock_client.send_gcode.call_args[0][0]
            assert "G1 Z10.00" in sent_gcode, f"{model}: expected G1 Z10.00 in gcode, got {sent_gcode!r}"
            assert "G1 Z-10" not in sent_gcode, f"{model}: must NOT emit negative Z for a UI 'Up' click"

    @pytest.mark.asyncio
    async def test_bed_jog_a1_down_arrow_drops_toolhead(self, async_client: AsyncClient, printer_factory):
        """Symmetric to the regression test: UI "Down" (positive distance,
        increase gap) on A1 must lower the toolhead via G1 Z-."""
        printer = await printer_factory(name="A1-Mini-Test", model="A1 Mini")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=10")
            assert response.status_code == 200
            sent_gcode = mock_client.send_gcode.call_args[0][0]
            assert "G1 Z-10.00" in sent_gcode


class TestAxisJogAPI:
    @pytest.mark.asyncio
    async def test_axis_jog_rejects_invalid_axis(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Klipper")
        response = await async_client.post(f"/api/v1/printers/{printer.id}/axis-jog?axis=e&distance=10")
        assert response.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("axis", "distance", "expected"),
        [("x", 10, "G1 X10.00 F3000"), ("y", -5, "G1 Y-5.00 F3000"), ("z", 1, "G1 Z1.00 F600")],
    )
    async def test_axis_jog_sends_relative_move(
        self, async_client: AsyncClient, printer_factory, axis, distance, expected
    ):
        printer = await printer_factory(name="Klipper", provider="klipper", model="Klipper/Moonraker")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(
                f"/api/v1/printers/{printer.id}/axis-jog?axis={axis}&distance={distance}"
            )
            assert response.status_code == 200
            sent_gcode = mock_client.send_gcode.call_args[0][0]
            assert sent_gcode.splitlines() == ["G91", expected, "G90"]


class TestDisableSteppersAPI:
    @pytest.mark.asyncio
    async def test_disable_steppers_uses_provider_gcode_transport(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Prusa MK4S", provider="prusalink", model="Prusa MK4S")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/disable-steppers")
            assert response.status_code == 200
            mock_client.send_gcode.assert_called_once_with("M84")


class TestTemperatureControlAPI:
    @pytest.mark.asyncio
    async def test_set_nozzle_temperature_uses_provider_helper(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Klipper", provider="klipper", model="Klipper/Moonraker")
        mock_client = MagicMock()
        mock_client.set_nozzle_temperature.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/nozzle?target=215")
            assert response.status_code == 200
            mock_client.set_nozzle_temperature.assert_called_once_with(215)

    @pytest.mark.asyncio
    async def test_set_bed_temperature_uses_provider_helper(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Klipper", provider="klipper", model="Klipper/Moonraker")
        mock_client = MagicMock()
        mock_client.set_bed_temperature.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/bed?target=60")
            assert response.status_code == 200
            mock_client.set_bed_temperature.assert_called_once_with(60)

    @pytest.mark.asyncio
    async def test_temperature_limits_are_validated(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Klipper")
        nozzle = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/nozzle?target=400")
        bed = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/bed?target=160")
        assert nozzle.status_code == 400
        assert bed.status_code == 400


class TestHomeAxesAPI:
    @pytest.mark.asyncio
    async def test_home_axes_not_found(self, async_client: AsyncClient):
        response = await async_client.post("/api/v1/printers/99999/home-axes?axes=z")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_home_axes_invalid(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="P1")
        response = await async_client.post(f"/api/v1/printers/{printer.id}/home-axes?axes=bogus")
        assert response.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("axes", ["x", "y", "z", "xy", "all"])
    async def test_home_axes_always_runs_full_home_for_bambu(self, async_client: AsyncClient, printer_factory, axes):
        # Regression for #1052: Bambu providers must always send a bare `G28` so the printer's
        # safe auto-home sequence (toolhead park → XY home → Z home) runs. Sending `G28 Z` alone
        # on H2C/H2D/H2S/X1 can crash the bed into the toolhead.
        printer = await printer_factory(name="P1", provider="bambu")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/home-axes?axes={axes}")
            assert response.status_code == 200
            mock_client.send_gcode.assert_called_once_with("G28")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("axes", "expected"),
        [("x", "G28 X"), ("y", "G28 Y"), ("z", "G28 Z"), ("xy", "G28 X Y"), ("all", "G28")],
    )
    async def test_home_axes_preserves_axes_for_prusalink(
        self, async_client: AsyncClient, printer_factory, axes, expected
    ):
        printer = await printer_factory(name="Prusa MK4S", provider="prusalink", model="Prusa MK4S")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/home-axes?axes={axes}")
            assert response.status_code == 200
            mock_client.send_gcode.assert_called_once_with(expected)


class TestExtrudeAPI:
    @pytest.mark.asyncio
    async def test_extrude_uses_provider_gcode_transport(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="Prusa MK4S", provider="prusalink", model="Prusa MK4S")
        mock_client = MagicMock()
        mock_client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = mock_client
            response = await async_client.post(f"/api/v1/printers/{printer.id}/extrude?length=10&speed=300")
            assert response.status_code == 200
            mock_client.send_gcode.assert_called_once_with("M83\nG1 E10.00 F300\nM82")

    @pytest.mark.asyncio
    async def test_home_axes_not_connected(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory(name="D")
        with patch("backend.app.api.routes.printers.printer_manager") as mock_pm:
            mock_pm.get_client.return_value = None
            response = await async_client.post(f"/api/v1/printers/{printer.id}/home-axes?axes=z")
            assert response.status_code == 400
