from pathlib import Path

import pytest

from backend.app.services import background_dispatch as bg
from backend.app.services.background_dispatch import PrintDispatchJob, background_dispatch


class FakeProviderClient:
    def __init__(self):
        self.uploads: list[tuple[Path, str]] = []
        self.deletes: list[str] = []

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        self.uploads.append((local_path, remote_path))
        return True

    def delete_file(self, remote_path: str) -> bool:
        self.deletes.append(remote_path)
        return True


def _job() -> PrintDispatchJob:
    return PrintDispatchJob(
        id=42,
        kind="print_library_file",
        source_id=7,
        source_name="Cable Holder.gcode",
        printer_id=3,
        printer_name="Core One",
    )


def test_remote_filename_preserves_gcode_for_prusalink_and_moonraker():
    assert background_dispatch._remote_filename_for_provider("Cable Holder.gcode", "prusalink") == "Cable_Holder.gcode"
    assert (
        background_dispatch._remote_filename_for_provider("Cable Holder.bgcode", "prusalink") == "Cable_Holder.bgcode"
    )
    assert background_dispatch._remote_filename_for_provider("Cable Holder.gcode", "fluidd") == "Cable_Holder.gcode"
    assert (
        background_dispatch._remote_filename_for_provider("Cable Holder.gcode", "elegoo_sdcp") == "Cable_Holder.gcode"
    )


def test_remote_filename_keeps_bambu_3mf_rewrite():
    assert background_dispatch._remote_filename_for_provider("Cable Holder.gcode.3mf", "bambu") == "Cable_Holder.3mf"
    assert background_dispatch._remote_filename_for_provider("Cable Holder.3mf", "bambu") == "Cable_Holder.3mf"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["prusalink", "elegoo_sdcp"])
async def test_provider_upload_uses_client_not_bambu_ftp(monkeypatch, tmp_path, provider: str):
    local_file = tmp_path / "Cable Holder.gcode"
    local_file.write_text("G28\n", encoding="utf-8")
    client = FakeProviderClient()

    monkeypatch.setattr(bg.printer_manager, "get_client", lambda printer_id: client)

    async def fail_bambu_upload(*args, **kwargs):  # pragma: no cover - failure path assertion
        raise AssertionError("Bambu FTP upload must not be used for provider dispatch")

    monkeypatch.setattr(bg, "upload_file_async", fail_bambu_upload)

    uploaded = await background_dispatch._upload_file_for_provider(
        job=_job(),
        provider=provider,
        printer_name="Provider Printer",
        printer_ip="192.0.2.10",
        printer_access_code="unused",
        file_path=local_file,
        remote_path="/Cable_Holder.gcode",
        printer_model="core_one",
        ftp_retry_enabled=True,
        ftp_retry_count=3,
        ftp_retry_delay=0,
        ftp_timeout=1,
        operation_name="Upload for print to Provider Printer",
        progress_callback=lambda uploaded, total: None,
    )

    assert uploaded is True
    assert client.uploads == [(local_file, "/Cable_Holder.gcode")]


@pytest.mark.asyncio
async def test_prusalink_provider_delete_uses_client_not_bambu_ftp(monkeypatch):
    client = FakeProviderClient()
    monkeypatch.setattr(bg.printer_manager, "get_client", lambda printer_id: client)

    async def fail_bambu_delete(*args, **kwargs):  # pragma: no cover - failure path assertion
        raise AssertionError("Bambu FTP delete must not be used for PrusaLink dispatch")

    monkeypatch.setattr(bg, "delete_file_async", fail_bambu_delete)

    await background_dispatch._delete_remote_file_for_provider(
        printer_id=3,
        provider="prusalink",
        printer_ip="192.0.2.10",
        printer_access_code="unused",
        remote_path="/Cable_Holder.gcode",
        printer_model="core_one",
        ftp_timeout=1,
    )

    assert client.deletes == ["/Cable_Holder.gcode"]


@pytest.mark.asyncio
async def test_bambu_provider_upload_still_uses_ftp(monkeypatch, tmp_path):
    local_file = tmp_path / "Cable Holder.gcode.3mf"
    local_file.write_bytes(b"PK\x03\x04")
    calls = []

    async def fake_bambu_upload(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(bg, "upload_file_async", fake_bambu_upload)

    uploaded = await background_dispatch._upload_file_for_provider(
        job=_job(),
        provider="bambu",
        printer_name="X1C",
        printer_ip="192.0.2.20",
        printer_access_code="secret",
        file_path=local_file,
        remote_path="/Cable_Holder.3mf",
        printer_model="x1c",
        ftp_retry_enabled=False,
        ftp_retry_count=0,
        ftp_retry_delay=0,
        ftp_timeout=1,
        operation_name="Upload for print to X1C",
        progress_callback=lambda uploaded, total: None,
    )

    assert uploaded is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:4] == ("192.0.2.20", "secret", local_file, "/Cable_Holder.3mf")
    assert kwargs["printer_model"] == "x1c"
