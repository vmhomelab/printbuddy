"""Multi-plate 3MF handling in ThreeMFParser / archive cost estimation.

A multi-plate project archived as a whole must report the totals of ALL
plates (time, weight, filament slots, object count, cost), while a print of a
single plate must report only that plate — previously both cases used the
first ``<plate>`` block of slice_info.config.
"""

import zipfile

import pytest
from defusedxml import ElementTree as ET

from backend.app.services.archive import (
    ThreeMFParser,
    estimate_filament_cost,
    parse_slice_info_plates,
    plate_number_from_print_data,
)

MULTI_PLATE_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header><header_item key="X-BBL-Client-Type" value="slicer"/></header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="printer_model_id" value="C11"/>
    <metadata key="prediction" value="3600"/>
    <metadata key="weight" value="50.5"/>
    <metadata key="curr_bed_type" value="Textured PEI Plate"/>
    <object identify_id="101" name="Part A" skipped="false"/>
    <object identify_id="102" name="Part B" skipped="false"/>
    <filament id="1" type="PLA" color="#FFFFFF" used_m="16.0" used_g="50.5"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="1800"/>
    <metadata key="weight" value="30.25"/>
    <metadata key="curr_bed_type" value="Textured PEI Plate"/>
    <object identify_id="201" name="Part C" skipped="false"/>
    <object identify_id="202" name="Part D" skipped="true"/>
    <filament id="1" type="PLA" color="#FFFFFF" used_m="5.0" used_g="10.25"/>
    <filament id="2" type="PETG" color="#000000" used_m="6.0" used_g="20"/>
  </plate>
  <plate>
    <metadata key="index" value="3"/>
    <metadata key="prediction" value="600"/>
    <metadata key="weight" value="9"/>
    <object identify_id="301" name="Part E" skipped="false"/>
    <filament id="2" type="PETG" color="#000000" used_m="3.0" used_g="9"/>
  </plate>
</config>
"""

SINGLE_PLATE_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="3"/>
    <metadata key="prediction" value="600"/>
    <metadata key="weight" value="9"/>
    <object identify_id="301" name="Part E" skipped="false"/>
    <filament id="2" type="PETG" color="#000000" used_m="3.0" used_g="9"/>
  </plate>
</config>
"""


def _make_3mf(tmp_path, slice_info: str, name: str = "model.3mf", extra: dict | None = None):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Metadata/slice_info.config", slice_info)
        for member, data in (extra or {}).items():
            zf.writestr(member, data)
    return path


class TestParseSliceInfoPlates:
    def test_parses_every_plate(self):
        plates = parse_slice_info_plates(ET.fromstring(MULTI_PLATE_SLICE_INFO))

        assert sorted(plates) == [1, 2, 3]
        assert plates[2]["prediction"] == 1800
        assert plates[2]["weight"] == 30.25
        assert [f["slot_id"] for f in plates[2]["filaments"]] == [1, 2]
        # Skipped object is excluded from printable objects but kept in names
        assert plates[2]["printable_objects"] == {201: "Part C"}
        assert plates[2]["object_names"] == ["Part C", "Part D"]

    def test_plate_without_index_uses_position(self):
        xml = "<config><plate><metadata key='prediction' value='10'/></plate></config>"
        plates = parse_slice_info_plates(ET.fromstring(xml))
        assert list(plates) == [1]
        assert plates[1]["prediction"] == 10


class TestThreeMFParserMultiPlate:
    def test_whole_project_aggregates_all_plates(self, tmp_path):
        metadata = ThreeMFParser(_make_3mf(tmp_path, MULTI_PLATE_SLICE_INFO)).parse()

        assert metadata["print_time_seconds"] == 3600 + 1800 + 600
        assert metadata["filament_used_grams"] == pytest.approx(50.5 + 30.25 + 9)
        assert metadata["filament_type"] == "PLA, PETG"
        assert metadata["filament_color"] == "#FFFFFF,#000000"
        assert metadata["filament_slots"] == [
            {"slot_id": 1, "used_g": 60.75, "type": "PLA", "color": "#FFFFFF"},
            {"slot_id": 2, "used_g": 29.0, "type": "PETG", "color": "#000000"},
        ]
        assert set(metadata["printable_objects"]) == {101, 102, 201, 301}
        assert metadata["bed_type"] == "Textured PEI Plate"
        assert metadata["plate_count"] == 3
        assert [p["index"] for p in metadata["plates"]] == [1, 2, 3]
        assert metadata["plates"][1]["print_time_seconds"] == 1800
        assert metadata["plates"][1]["object_count"] == 1

    def test_whole_project_name_not_suffixed_with_plate(self, tmp_path):
        model = (
            '<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
            '<metadata name="Title">Big Model</metadata><resources/><build/></model>'
        )
        path = _make_3mf(tmp_path, MULTI_PLATE_SLICE_INFO, extra={"3D/3dmodel.model": model})
        metadata = ThreeMFParser(path).parse()
        assert "Plate" not in (metadata.get("print_name") or "")

    def test_known_printed_plate_uses_only_that_plate(self, tmp_path):
        path = _make_3mf(
            tmp_path,
            MULTI_PLATE_SLICE_INFO,
            extra={"Metadata/plate_2.png": b"plate2", "Metadata/plate_1.png": b"plate1"},
        )
        metadata = ThreeMFParser(path, plate_number=2).parse()

        assert metadata["print_time_seconds"] == 1800
        assert metadata["filament_used_grams"] == pytest.approx(30.25)
        assert metadata["filament_type"] == "PLA, PETG"
        assert metadata["filament_slots"] == [
            {"slot_id": 1, "used_g": 10.25, "type": "PLA", "color": "#FFFFFF"},
            {"slot_id": 2, "used_g": 20.0, "type": "PETG", "color": "#000000"},
        ]
        assert metadata["printable_objects"] == {201: "Part C"}
        assert metadata["_thumbnail_data"] == b"plate2"
        # Breakdown of the whole file is still kept for reference
        assert metadata["plate_count"] == 3

    def test_unknown_plate_number_falls_back_to_aggregate(self, tmp_path):
        metadata = ThreeMFParser(_make_3mf(tmp_path, MULTI_PLATE_SLICE_INFO), plate_number=9).parse()
        assert metadata["print_time_seconds"] == 6000

    def test_single_plate_export_adopts_its_index(self, tmp_path):
        parser = ThreeMFParser(_make_3mf(tmp_path, SINGLE_PLATE_SLICE_INFO))
        metadata = parser.parse()

        assert parser.plate_number == 3
        assert metadata["print_time_seconds"] == 600
        assert metadata["filament_used_grams"] == 9
        assert metadata["filament_slots"] == [{"slot_id": 2, "used_g": 9.0, "type": "PETG", "color": "#000000"}]
        assert "plates" not in metadata
        assert "plate_count" not in metadata

    def test_filaments_outside_plate_still_parsed(self, tmp_path):
        xml = '<config><filament id="1" type="PLA" color="#FF0000" used_g="12"/></config>'
        metadata = ThreeMFParser(_make_3mf(tmp_path, xml)).parse()
        assert metadata["filament_type"] == "PLA"
        assert metadata["filament_slots"] == [{"slot_id": 1, "used_g": 12.0, "type": "PLA", "color": "#FF0000"}]


class TestPlateNumberFromPrintData:
    @pytest.mark.parametrize(
        ("print_data", "expected"),
        [
            (None, None),
            ({}, None),
            ({"filename": None}, None),
            ({"filename": "/data/Metadata/plate_5.gcode"}, 5),
            ({"filename": "model.3mf"}, None),
        ],
    )
    def test_extracts_plate(self, print_data, expected):
        assert plate_number_from_print_data(print_data) == expected


class TestEstimateFilamentCost:
    CATALOG = {"PLA": 20.0, "PETG": 30.0}

    def test_prices_each_material_separately(self):
        slots = [{"used_g": 60, "type": "PLA"}, {"used_g": 40, "type": "petg"}]
        # 60g @ 20/kg + 40g @ 30/kg = 1.20 + 1.20
        assert estimate_filament_cost(100, "PLA, PETG", slots, self.CATALOG, 25.0) == 2.4

    def test_unknown_material_uses_default(self):
        slots = [{"used_g": 100, "type": "ASA"}]
        assert estimate_filament_cost(100, "ASA", slots, self.CATALOG, 25.0) == 2.5

    def test_blended_rate_applied_to_total_weight(self):
        # Total weight corrected after the print (e.g. actual usage) — the
        # per-material mix still drives the price per kg.
        slots = [{"used_g": 50, "type": "PLA"}, {"used_g": 50, "type": "PETG"}]
        assert estimate_filament_cost(200, "PLA, PETG", slots, self.CATALOG, 25.0) == 5.0

    def test_without_slots_uses_primary_type(self):
        assert estimate_filament_cost(100, "PETG, PLA", None, self.CATALOG, 25.0) == 3.0

    def test_no_weight_or_no_type(self):
        assert estimate_filament_cost(None, "PLA", None, self.CATALOG, 25.0) is None
        assert estimate_filament_cost(0, "PLA", None, self.CATALOG, 25.0) is None
        assert estimate_filament_cost(100, None, None, self.CATALOG, 25.0) is None
