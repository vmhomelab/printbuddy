"""Integration tests for Prometheus Metrics API endpoint.

Tests the /api/v1/metrics endpoint for Prometheus scraping.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient


class TestMetricsAPI:
    """Integration tests for /api/v1/metrics endpoint."""

    # ========================================================================
    # Metrics endpoint access control
    # ========================================================================

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_disabled_returns_404(self, async_client: AsyncClient):
        """Verify metrics endpoint returns 404 when disabled."""
        # Ensure prometheus is disabled
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": False})

        response = await async_client.get("/api/v1/metrics")

        assert response.status_code == 404
        assert "not enabled" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_enabled_without_token(self, async_client: AsyncClient):
        """Verify metrics endpoint works when enabled without token."""
        # Enable prometheus without token
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": ""})

        response = await async_client.get("/api/v1/metrics")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_with_token_requires_auth(self, async_client: AsyncClient):
        """Verify metrics endpoint requires auth when token is set."""
        # Enable prometheus with token
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": "secret123"})

        # Request without auth
        response = await async_client.get("/api/v1/metrics")
        assert response.status_code == 401

        # Request with wrong token
        response = await async_client.get("/api/v1/metrics", headers={"Authorization": "Bearer wrongtoken"})
        assert response.status_code == 401

        # Request with correct token
        response = await async_client.get("/api/v1/metrics", headers={"Authorization": "Bearer secret123"})
        assert response.status_code == 200

    # ========================================================================
    # Metrics content validation
    # ========================================================================

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_format(self, async_client: AsyncClient):
        """Verify metrics are in Prometheus text format."""
        # Enable prometheus
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": ""})

        response = await async_client.get("/api/v1/metrics")

        assert response.status_code == 200
        content = response.text

        # Check for Prometheus format markers
        assert "# HELP" in content
        assert "# TYPE" in content

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_contains_expected_metrics(self, async_client: AsyncClient):
        """Verify expected metrics are present."""
        # Enable prometheus
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": ""})

        response = await async_client.get("/api/v1/metrics")

        assert response.status_code == 200
        content = response.text

        # Check for key metrics
        assert "printbuddy_printers_connected" in content
        assert "printbuddy_printers_total" in content
        assert "printbuddy_prints_total" in content
        assert "printbuddy_filament_used_grams" in content
        assert "printbuddy_print_time_seconds" in content
        assert "printbuddy_queue_pending" in content

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_printer_metrics_when_no_printers(self, async_client: AsyncClient):
        """Verify printer metrics work when no printers configured."""
        # Enable prometheus
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": ""})

        response = await async_client.get("/api/v1/metrics")

        assert response.status_code == 200
        content = response.text

        # Should still have system metrics
        assert "printbuddy_printers_total" in content
        assert "printbuddy_printers_connected" in content

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_metrics_emits_every_reported_nozzle(self, async_client: AsyncClient, printer_factory):
        """Multi-toolhead printers export one current and target series per nozzle."""
        printer = await printer_factory(name="Snapmaker U1", model="Snapmaker U1")
        status = SimpleNamespace(
            connected=True,
            state="RUNNING",
            progress=42.0,
            remaining_time=8,
            layer_num=4,
            total_layers=20,
            temperatures={
                "nozzle": 201.0,
                "nozzle_target": 210.0,
                "nozzle_2": 202.0,
                "nozzle_2_target": 211.0,
                "nozzle_3": 203.0,
                "nozzle_3_target": 212.0,
                "nozzle_4": 204.0,
                "nozzle_4_target": 213.0,
            },
            wifi_signal=None,
        )
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": ""})

        with patch(
            "backend.app.api.routes.metrics.printer_manager.get_all_statuses", return_value={printer.id: status}
        ):
            response = await async_client.get("/api/v1/metrics")

        assert response.status_code == 200
        for nozzle_index, temperature, target in (
            (0, 201.0, 210.0),
            (1, 202.0, 211.0),
            (2, 203.0, 212.0),
            (3, 204.0, 213.0),
        ):
            nozzle_label = f'printer_id="{printer.id}",printer_name="Snapmaker U1",serial="{printer.serial_number}",nozzle="{nozzle_index}"'
            assert f"printbuddy_nozzle_temp_celsius{{{nozzle_label}}} {temperature:.1f}" in response.text
            assert f"printbuddy_nozzle_target_celsius{{{nozzle_label}}} {target:.1f}" in response.text

    # ========================================================================
    # Settings persistence
    # ========================================================================

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_prometheus_settings_persist(self, async_client: AsyncClient):
        """Verify prometheus settings are saved correctly."""
        # Update settings
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": True, "prometheus_token": "mytoken"})

        # Read back settings
        response = await async_client.get("/api/v1/settings/")
        settings = response.json()

        assert settings["prometheus_enabled"] is True
        assert settings["prometheus_token"] == "mytoken"

        # Disable and verify
        await async_client.put("/api/v1/settings/", json={"prometheus_enabled": False})
        response = await async_client.get("/api/v1/settings/")
        settings = response.json()

        assert settings["prometheus_enabled"] is False
