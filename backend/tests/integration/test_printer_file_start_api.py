"""Regression tests for direct printer-file start endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class _FakeProviderClient:
    def __init__(self) -> None:
        self.started_paths: list[str] = []

    def start_print(self, path: str) -> bool:
        self.started_paths.append(path)
        return True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_delegates_to_provider_client(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/Love Paw Print.gcode"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "path": "/Love Paw Print.gcode"}
    assert fake_client.started_paths == ["/Love Paw Print.gcode"]
