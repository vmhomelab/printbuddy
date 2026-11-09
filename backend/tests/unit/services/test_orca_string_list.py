"""Parsing of OrcaSlicer's serialised string-vector options."""

import pytest

from backend.app.services.orca_cloud import parse_orca_string_list


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"Elegoo Elegoo Neptune 4 Pro 0.4 nozzle"', ["Elegoo Elegoo Neptune 4 Pro 0.4 nozzle"]),
        (['"Creality Creality CR-10 V2 0.4 nozzle"'], ["Creality Creality CR-10 V2 0.4 nozzle"]),
        ('"Printer A";"Printer B"', ["Printer A", "Printer B"]),
        ("Printer A;Printer B", ["Printer A", "Printer B"]),
        (["Bambu Lab P1S 0.4 nozzle", "  "], ["Bambu Lab P1S 0.4 nozzle"]),
        ('"Name with \\"quotes\\""', ['Name with "quotes"']),
        ("", []),
        ('""', []),
        (None, []),
        (42, []),
    ],
)
def test_parse_orca_string_list(value, expected):
    assert parse_orca_string_list(value) == expected
