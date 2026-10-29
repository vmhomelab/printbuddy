"""``discover_plate_indices`` — plate list for SliceModal / plates APIs."""

from __future__ import annotations

import io
import zipfile

from backend.app.utils.threemf_tools import discover_plate_indices


def _zip(entries: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r")


def test_prefers_gcode_over_model_settings():
    model = (
        b'<config><plate><metadata key="plater_id" value="1"/></plate>'
        b'<plate><metadata key="plater_id" value="2"/></plate></config>'
    )
    with _zip(
        {
            "Metadata/plate_5.gcode": b"; gcode",
            "Metadata/model_settings.config": model,
        }
    ) as zf:
        assert discover_plate_indices(zf) == [5]


def test_falls_back_to_preview_png():
    with _zip(
        {
            "Metadata/plate_1.png": b"png",
            "Metadata/plate_2.png": b"png",
            "Metadata/plate_1_small.png": b"skip",
            "Metadata/plate_no_light_1.png": b"skip",
        }
    ) as zf:
        assert discover_plate_indices(zf) == [1, 2]


def test_falls_back_to_model_settings_when_previews_missing():
    """Snapmaker/Orca converted projects: plates in model_settings only."""
    model = (
        b'<?xml version="1.0"?>\n<config>\n'
        b'  <plate><metadata key="plater_id" value="1"/>'
        b'<model_instance><metadata key="object_id" value="2"/></model_instance></plate>\n'
        b'  <plate><metadata key="plater_id" value="2"/>'
        b'<model_instance><metadata key="object_id" value="4"/></model_instance></plate>\n'
        b'  <plate><metadata key="plater_id" value="3"/>'
        b'<model_instance><metadata key="object_id" value="6"/></model_instance></plate>\n'
        b"</config>"
    )
    with _zip({"Metadata/model_settings.config": model}) as zf:
        assert discover_plate_indices(zf) == [1, 2, 3]


def test_empty_when_no_plate_metadata():
    with _zip({"Metadata/project_settings.config": b"{}"}) as zf:
        assert discover_plate_indices(zf) == []
