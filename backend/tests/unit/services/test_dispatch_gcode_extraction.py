"""Dispatch of .gcode.3mf files to G-code (non-Bambu) printers.

Moonraker/Klipper, PrusaLink, OctoPrint and Elegoo printers cannot start a
``.gcode.3mf`` project, so the dispatch paths upload the selected plate's
G-code as ``<name>.gcode`` instead. Bambu printers keep receiving the 3MF.
"""

from __future__ import annotations

import zipfile
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.background_dispatch import BackgroundDispatchService, PrintDispatchJob

BD = "backend.app.services.background_dispatch"


class RecordingClient:
    """Provider client that keeps a copy of every uploaded file."""

    def __init__(self):
        self.uploads: list[tuple[str, bytes]] = []
        self.deletes: list[str] = []

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        self.uploads.append((remote_path, Path(local_path).read_bytes()))
        return True

    def delete_file(self, remote_path: str) -> bool:
        self.deletes.append(remote_path)
        return True


def _make_3mf(path: Path, plates: dict[int, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        for number, gcode in plates.items():
            archive.writestr(f"Metadata/plate_{number}.gcode", gcode)
    return path


def _session_factory(db):
    @asynccontextmanager
    async def factory():
        yield db

    return factory


def _printer(provider: str):
    return SimpleNamespace(
        id=10, name="Voron", ip_address="192.0.2.5", access_code="", model="Voron 2.4", provider=provider
    )


def _job(kind: str, plate_id: int | None = None) -> PrintDispatchJob:
    return PrintDispatchJob(
        id=1,
        kind=kind,
        source_id=99,
        source_name="Bracket.gcode.3mf",
        printer_id=10,
        printer_name="Voron",
        options={"plate_id": plate_id} if plate_id else {},
        requested_by_user_id=None,
        requested_by_username=None,
    )


def _common_patches(stack: ExitStack, client: RecordingClient, start_print: MagicMock) -> None:
    stack.enter_context(patch.object(BackgroundDispatchService, "_verify_print_response", AsyncMock(return_value=True)))
    stack.enter_context(patch(f"{BD}.printer_manager.is_connected", return_value=True))
    stack.enter_context(patch(f"{BD}.printer_manager.get_client", return_value=client))
    stack.enter_context(patch(f"{BD}.printer_manager.get_status", return_value=None))
    stack.enter_context(patch(f"{BD}.printer_manager.start_print", start_print))
    stack.enter_context(patch(f"{BD}.get_ftp_retry_settings", new_callable=AsyncMock, return_value=(False, 0, 0, 30.0)))
    stack.enter_context(
        patch(f"{BD}.upload_file_async", AsyncMock(side_effect=AssertionError("Bambu FTP must not be used")))
    )
    stack.enter_context(patch(f"{BD}.ws_manager.broadcast", new_callable=AsyncMock))
    stack.enter_context(patch("backend.app.main.register_expected_print"))


@pytest.mark.asyncio
async def test_reprint_archive_uploads_selected_plate_gcode_to_moonraker(tmp_path):
    archive_file = _make_3mf(tmp_path / "bracket.3mf", {1: "; plate 1\n", 2: "; plate 2\nG28\n"})
    archive = SimpleNamespace(id=99, filename="Bracket.gcode.3mf", file_path=str(archive_file))
    db = MagicMock()
    db.scalar = AsyncMock(return_value=_printer("moonraker"))
    archive_service = MagicMock()
    archive_service.get_archive = AsyncMock(return_value=archive)
    client = RecordingClient()
    start_print = MagicMock(return_value=True)

    with ExitStack() as stack:
        stack.enter_context(patch(f"{BD}.async_session", _session_factory(db)))
        stack.enter_context(patch(f"{BD}.ArchiveService", return_value=archive_service))
        _common_patches(stack, client, start_print)
        await BackgroundDispatchService()._run_reprint_archive(_job("reprint_archive", plate_id=2))

    assert client.uploads == [("/Bracket_plate_2.gcode", b"; plate 2\nG28\n")]
    assert start_print.call_args.args[1] == "Bracket_plate_2.gcode"
    # The archive itself is left untouched.
    assert archive_file.exists()


@pytest.mark.asyncio
async def test_library_print_without_gcode_for_plate_fails_before_creating_archive(tmp_path):
    src = _make_3mf(tmp_path / "bracket.3mf", {1: "; plate 1\n"})
    lib_file = SimpleNamespace(id=22, filename="Bracket.gcode.3mf", file_path=str(src))
    db = MagicMock()
    db.scalar = AsyncMock(side_effect=[lib_file, _printer("prusalink")])
    archive_service = MagicMock()
    archive_service.archive_print = AsyncMock()
    client = RecordingClient()
    start_print = MagicMock(return_value=True)

    with ExitStack() as stack:
        stack.enter_context(patch(f"{BD}.async_session", _session_factory(db)))
        stack.enter_context(patch(f"{BD}.ArchiveService", return_value=archive_service))
        stack.enter_context(patch(f"{BD}.LibraryFile"))
        stack.enter_context(patch(f"{BD}.settings", SimpleNamespace(base_dir=tmp_path)))
        _common_patches(stack, client, start_print)
        with pytest.raises(RuntimeError, match=r"Plate 3 .* not sliced"):
            await BackgroundDispatchService()._run_print_library_file(_job("print_library_file", plate_id=3))

    archive_service.archive_print.assert_not_called()
    assert client.uploads == []
    start_print.assert_not_called()


@pytest.mark.asyncio
async def test_reprint_archive_still_uploads_the_3mf_to_bambu(tmp_path):
    archive_file = _make_3mf(tmp_path / "bracket.3mf", {1: "; plate 1\n"})
    archive = SimpleNamespace(id=99, filename="Bracket.gcode.3mf", file_path=str(archive_file))
    db = MagicMock()
    db.scalar = AsyncMock(return_value=_printer("bambu"))
    archive_service = MagicMock()
    archive_service.get_archive = AsyncMock(return_value=archive)
    start_print = MagicMock(return_value=True)
    ftp_upload = AsyncMock(return_value=True)

    with ExitStack() as stack:
        stack.enter_context(patch(f"{BD}.async_session", _session_factory(db)))
        stack.enter_context(patch(f"{BD}.ArchiveService", return_value=archive_service))
        _common_patches(stack, RecordingClient(), start_print)
        stack.enter_context(patch(f"{BD}.upload_file_async", ftp_upload))
        stack.enter_context(patch(f"{BD}.delete_file_async", new_callable=AsyncMock))
        stack.enter_context(patch(f"{BD}.cache_3mf_download"))
        await BackgroundDispatchService()._run_reprint_archive(_job("reprint_archive"))

    args = ftp_upload.call_args.args
    assert args[2] == archive_file
    assert args[3] == "/Bracket.3mf"
    assert start_print.call_args.args[1] == "Bracket.3mf"
