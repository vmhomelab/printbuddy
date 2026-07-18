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
        self.deleted_paths: list[str] = []
        self.start_options: list[dict[str, object]] = []
        self.file_info: dict[str, object] | None = None
        self.file_info_paths: list[str] = []

    def get_file_info(self, path: str) -> dict[str, object] | None:
        self.file_info_paths.append(path)
        return self.file_info

    def start_print(self, path: str, **kwargs) -> bool:
        self.started_paths.append(path)
        self.start_options.append(kwargs)
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

    def delete_file(self, remote_path: str) -> bool:
        self.deleted_paths.append(remote_path)
        normalized = "/" + remote_path.strip("/")
        self.files = [
            file
            for file in self.files
            if "/" + str(file.get("path") or file.get("name") or "").strip("/") != normalized
        ]
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
    assert fake_client.start_options == [{}]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_passes_elegoo_cc1_start_options_to_provider(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={
            "path": "/local/Love Paw Print.gcode",
            "bed_levelling": "true",
            "print_platform_type": "1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "path": "/local/Love Paw Print.gcode"}
    assert fake_client.started_paths == ["/local/Love Paw Print.gcode"]
    assert fake_client.start_options == [{"bed_levelling": True, "print_platform_type": 1}]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_registers_elegoo_direct_print_estimated_weight(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()
    fake_client.file_info = {
        "path": "/local/Love Paw Print.gcode",
        "estimated_weight_grams": 9.79,
        "estimated_time_seconds": 2608,
    }
    registered: list[tuple[int, str, float, int | None]] = []

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(
        printer_routes.direct_print_tracking,
        "register_direct_print_metadata",
        lambda printer_id, filename, estimated_weight_grams, estimated_time_seconds=None: registered.append(
            (printer_id, filename, estimated_weight_grams, estimated_time_seconds)
        ),
    )

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode"},
    )

    assert response.status_code == 200
    assert fake_client.file_info_paths == ["/local/Love Paw Print.gcode"]
    assert registered == [(printer.id, "/local/Love Paw Print.gcode", 9.79, 2608)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_does_not_register_metadata_when_start_fails(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()
    fake_client.file_info = {"estimated_weight_grams": 9.79}
    fake_client.start_print = lambda path, **kwargs: False
    registered: list[object] = []

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(
        printer_routes.direct_print_tracking,
        "register_direct_print_metadata",
        lambda *args, **kwargs: registered.append((args, kwargs)),
    )

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode"},
    )

    assert response.status_code == 500
    assert registered == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_rejects_invalid_print_platform_type(async_client: AsyncClient, printer_factory):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode", "print_platform_type": "2"},
    )

    assert response.status_code == 422


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
    fake_client.reveal_file_after_list_calls = 2
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 4,
    }

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
    fake_client.reveal_file_after_list_calls = 2
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 0,
    }

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
    fake_client.reveal_file_after_list_calls = 2
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 0,
    }

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_renames_existing_provider_file_when_requested(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 4},
        {"name": "Shoe_horn_thicker(1).gcode", "path": "/Shoe_horn_thicker(1).gcode", "type": "file", "size": 4},
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/", "conflict_strategy": "rename"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker(2).gcode",
        "filename": "Shoe_horn_thicker(2).gcode",
        "renamed": True,
        "original_filename": "Shoe_horn_thicker.gcode",
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker(2).gcode"]
    assert fake_client.deleted_paths == []
    assert fake_client.upload_overwrite_flags == [False]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_delete_replaces_existing_provider_file_when_requested(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 4}
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(printer_routes, "PROVIDER_UPLOAD_RECONCILE_INTERVAL_SECONDS", 0)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/", "conflict_strategy": "delete_replace"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
        "replaced": True,
    }
    assert fake_client.deleted_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.upload_overwrite_flags == [False]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_reports_existing_provider_file_without_strategy(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
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

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert fake_client.uploaded_paths == []
