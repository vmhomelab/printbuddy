"""Integration tests for the shared location filter (print log, archive export, maintenance overview)."""

import csv
import io

import pytest
from httpx import AsyncClient


async def _two_sites(printer_factory, archive_factory):
    printer_a = await printer_factory(name="Printer A", location="Site A")
    printer_b = await printer_factory(name="Printer B", location="Site B")
    printer_none = await printer_factory(name="Printer None")
    await archive_factory(printer_a.id, print_name="Print At A")
    await archive_factory(printer_b.id, print_name="Print At B")
    await archive_factory(printer_none.id, print_name="Print Without Location")
    return printer_a, printer_b, printer_none


class TestPrintLogLocationFilter:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_filters_by_printer_location(self, async_client: AsyncClient, printer_factory, archive_factory):
        await _two_sites(printer_factory, archive_factory)

        response = await async_client.get("/api/v1/print-log/", params={"location": "Site A"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert [e["print_name"] for e in data["items"]] == ["Print At A"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_without_location_returns_all(self, async_client: AsyncClient, printer_factory, archive_factory):
        await _two_sites(printer_factory, archive_factory)

        response = await async_client.get("/api/v1/print-log/")
        assert response.status_code == 200
        assert response.json()["total"] == 3

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unknown_location_returns_nothing(self, async_client: AsyncClient, printer_factory, archive_factory):
        await _two_sites(printer_factory, archive_factory)

        response = await async_client.get("/api/v1/print-log/", params={"location": "Nowhere"})
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0}

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_combines_with_printer_filter(self, async_client: AsyncClient, printer_factory, archive_factory):
        _, printer_b, _ = await _two_sites(printer_factory, archive_factory)

        response = await async_client.get(
            "/api/v1/print-log/", params={"location": "Site A", "printer_id": printer_b.id}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0


class TestArchiveExportLocationFilter:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_csv_export_filters_by_location(self, async_client: AsyncClient, printer_factory, archive_factory):
        await _two_sites(printer_factory, archive_factory)

        response = await async_client.get("/api/v1/archives/export", params={"format": "csv", "location": "Site B"})
        assert response.status_code == 200
        text = response.content.decode("utf-8-sig")
        assert "Print At B" in text
        assert "Print At A" not in text
        assert "Print Without Location" not in text
        rows = list(csv.reader(io.StringIO(text)))
        assert len(rows) == 2  # header + one archive


class TestMaintenanceOverviewLocation:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_overview_includes_printer_location(self, async_client: AsyncClient, printer_factory):
        await printer_factory(name="Located", location="Site A")
        await printer_factory(name="Unlocated")

        response = await async_client.get("/api/v1/maintenance/overview")
        assert response.status_code == 200
        by_name = {o["printer_name"]: o for o in response.json()}
        assert by_name["Located"]["printer_location"] == "Site A"
        assert by_name["Unlocated"]["printer_location"] is None
