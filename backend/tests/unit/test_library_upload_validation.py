import pytest
from fastapi import HTTPException

from backend.app.api.routes.library import validate_print_file_upload


def test_raw_gcode_allowed_for_provider_neutral_library_upload():
    """The File Manager is provider-neutral unless a target printer is supplied.

    A missing target printer used to be treated as Bambu, which rejected raw
    .gcode uploads even for PrusaLink/Core One users uploading to the library.
    """
    validate_print_file_upload("core-one-test.gcode", b"G28\nM104 S215\n", printer_provider=None)


@pytest.mark.parametrize("provider", ["prusalink", "klipper", "moonraker"])
def test_raw_gcode_allowed_for_non_bambu_provider(provider: str):
    validate_print_file_upload("job.gcode", b"G28\n", printer_provider=provider)


def test_raw_gcode_rejected_for_explicit_bambu_target():
    with pytest.raises(HTTPException) as exc_info:
        validate_print_file_upload("bad.gcode", b"G28\n", printer_provider="bambu")

    assert exc_info.value.status_code == 400
    assert "Bambu printers" in str(exc_info.value.detail)


def test_renamed_raw_gcode_3mf_still_rejected_for_all_providers():
    with pytest.raises(HTTPException) as exc_info:
        validate_print_file_upload("renamed.gcode.3mf", b"G28\n", printer_provider="prusalink")

    assert exc_info.value.status_code == 400
    assert "valid ZIP container" in str(exc_info.value.detail)
