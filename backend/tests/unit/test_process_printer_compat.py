"""Tests for process/filament ``compatible_printers`` rewrite.

When SliceModal sends a printer + process/filament pair, the sidecar
preflight (and Orca CLI for process) reject the job if ``compatible_printers``
does not list the printer's name. That surfaces for cross-vendor re-slices
(Bambu stock filament → Snapmaker U1 Orca Cloud clone).
"""

import json

from backend.app.api.routes.library import (
    _ensure_preset_compatible_with_printer,
    _ensure_process_compatible_with_printer,
)


class TestEnsureProcessCompatibleWithPrinter:
    def test_appends_printer_name_and_inherits(self):
        process = json.dumps(
            {
                "name": "0.20mm Standard @BBL P1S",
                "compatible_printers": ["Bambu Lab P1S 0.4 nozzle"],
            }
        )
        printer = json.dumps(
            {
                "name": "Snapmaker U1 0.4 nozzle",
                "inherits": "Snapmaker U1 0.4 nozzle",
            }
        )
        result = json.loads(_ensure_process_compatible_with_printer(process, printer))
        assert result["compatible_printers"] == [
            "Bambu Lab P1S 0.4 nozzle",
            "Snapmaker U1 0.4 nozzle",
        ]

    def test_noop_when_already_listed(self):
        process = json.dumps(
            {
                "name": "0.20mm Standard @Snapmaker U1",
                "compatible_printers": ["Snapmaker U1 0.4 nozzle"],
            }
        )
        printer = json.dumps({"name": "Snapmaker U1 0.4 nozzle"})
        original = process
        assert _ensure_process_compatible_with_printer(process, printer) == original

    def test_creates_compat_list_when_missing(self):
        process = json.dumps({"name": "Custom Process"})
        printer = json.dumps({"name": "Snapmaker U1 0.4 nozzle", "inherits": "fdm_u1"})
        result = json.loads(_ensure_process_compatible_with_printer(process, printer))
        assert result["compatible_printers"] == [
            "Snapmaker U1 0.4 nozzle",
            "fdm_u1",
        ]

    def test_returns_input_unchanged_when_json_invalid(self):
        bogus = "not json"
        assert _ensure_process_compatible_with_printer(bogus, '{"name":"X"}') is bogus
        assert _ensure_process_compatible_with_printer('{"name":"P"}', "not json") == '{"name":"P"}'

    def test_dedupes_name_matching_inherits(self):
        process = json.dumps({"name": "P", "compatible_printers": []})
        printer = json.dumps({"name": "Snapmaker U1 0.4 nozzle", "inherits": "Snapmaker U1 0.4 nozzle"})
        result = json.loads(_ensure_process_compatible_with_printer(process, printer))
        assert result["compatible_printers"] == ["Snapmaker U1 0.4 nozzle"]


class TestEnsureFilamentCompatibleWithPrinter:
    """Sidecar ``validateProfileCompatibility`` 400 for Bambu filament → Snapmaker."""

    def test_appends_snapmaker_copy_name_to_bambu_filament(self):
        filament = json.dumps(
            {
                "name": "Bambu PLA Basic",
                "compatible_printers": [
                    "Bambu Lab X1 Carbon 0.4 nozzle",
                    "Bambu Lab P1S 0.4 nozzle",
                ],
            }
        )
        printer = json.dumps(
            {
                "name": "Snapmaker U1 (0.4 nozzle) - Copy",
                "inherits": "Snapmaker U1 (0.4 nozzle)",
            }
        )
        result = json.loads(_ensure_preset_compatible_with_printer(filament, printer, kind="filament"))
        assert result["compatible_printers"] == [
            "Bambu Lab X1 Carbon 0.4 nozzle",
            "Bambu Lab P1S 0.4 nozzle",
            "Snapmaker U1 (0.4 nozzle) - Copy",
            "Snapmaker U1 (0.4 nozzle)",
        ]
