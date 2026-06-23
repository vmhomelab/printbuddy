"""Regression tests for direct printer-file start endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class _FakeProviderClient:
    def __init__(self) -> None:
        self.started_paths: list[str] = []
        self.uploaded_paths: list[str] = []
        self.upload_overwrite_flags: list[bool] = []
        self.files: list[dict[str, object]] = []
        self.upload_exception: Exception | None = None
        self.list_files_calls = 0
        self.reveal_file_after_list_calls: int | None = None
        self.revealed_file: dict[str, object] | None = None
        self.preserve_files_on_upload = False

    def start_print(self, path: str) -> bool:
        self.started_paths.append(path)
        return True

    def upload_file(self, local_path, remote_path: str, *, overwrite: bool = False) -> bool:
        self.uploaded_paths.append(remote_path)
        self.upload_overwrite_flags.append(overwrite)
        if self.upload_exception is not None:
            raise self.upload_exception
        if self.preserve_files_on_upload:
            return True
        self.files.append(
            {
                "name": remote_path.rsplit("/", 1)[-1],
                "path": remote_path,
                "type": "file",
                "size": local_path.stat().st_size,
            }
        )
        return True

    def list_files(self, _path: str = "/") -> list[dict[str, object]]:
        self.list_files_calls += 1
        if (
            self.reveal_file_after_list_calls is not None
            and self.revealed_file is not None
            and self.list_files_calls >= self.reveal_file_after_list_calls
        ):
            self.files = [self.revealed_file]
        return self.files


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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_delegates_to_provider_client(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.upload_overwrite_flags == [False]
    assert fake_client.started_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_reconciles_provider_timeout_when_file_appears(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.upload_exception = httpx.ReadTimeout("printer still writing to USB")
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 4}
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
        "reconciled": True,
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.started_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_waits_for_provider_file_to_appear_after_timeout(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.upload_exception = httpx.ReadTimeout("printer still writing to USB")
    fake_client.reveal_file_after_list_calls = 3
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 4,
    }

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(printer_routes, "PROVIDER_UPLOAD_RECONCILE_INTERVAL_SECONDS", 0)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
        "reconciled": True,
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.upload_overwrite_flags == [False]
    assert fake_client.list_files_calls == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_rejects_zero_byte_provider_placeholder(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.preserve_files_on_upload = True
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 0}
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(printer_routes, "PROVIDER_UPLOAD_RECONCILE_INTERVAL_SECONDS", 0)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 502
    assert "0-byte placeholder" in response.json()["detail"]
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_reports_zero_byte_placeholder_on_conflict(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    request = httpx.Request("PUT", "http://printer/api/v1/files/usb/Shoe_horn_thicker.gcode")
    response = httpx.Response(409, request=request)
    fake_client.upload_exception = httpx.HTTPStatusError("Conflict", request=request, response=response)
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 0}
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/", "overwrite": "true"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert "0-byte placeholder" in response.json()["detail"]
    assert fake_client.upload_overwrite_flags == [True]
