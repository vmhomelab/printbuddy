"""Orca #12426 workarounds: strip / extract / reapply paint_color; STL export."""

from __future__ import annotations

import zipfile
from io import BytesIO

from backend.app.services.slicer_3mf_convert import (
    extract_3mf_meshes_as_stl,
    extract_3mf_paint_colors,
    reapply_3mf_paint_colors,
    strip_3mf_paint_color,
    threemf_has_paint_color,
)


def _make_3mf(entries: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_detects_paint_color():
    model = b'<triangle v1="0" v2="1" v3="2" paint_color="1"/>'
    raw = _make_3mf({"3D/Objects/o.model": model, "Metadata/project_settings.config": b"{}"})
    assert threemf_has_paint_color(raw) is True


def test_no_paint_returns_false():
    model = b'<triangle v1="0" v2="1" v3="2"/>'
    raw = _make_3mf({"3D/Objects/o.model": model})
    assert threemf_has_paint_color(raw) is False


def test_strip_removes_paint_attrs():
    model = (
        b"<mesh><triangles>"
        b'<triangle v1="0" v2="1" v3="2" paint_color="1C"/>'
        b'<triangle v1="0" v2="1" v3="2"/>'
        b"</triangles></mesh>"
    )
    raw = _make_3mf({"3D/Objects/o.model": model})
    out = strip_3mf_paint_color(raw)
    assert out is not raw
    with zipfile.ZipFile(BytesIO(out), "r") as zf:
        data = zf.read("3D/Objects/o.model")
    assert b"paint_color=" not in data
    assert b'<triangle v1="0" v2="1" v3="2"/>' in data


def test_strip_noop_without_paint():
    model = b'<triangle v1="0" v2="1" v3="2"/>'
    raw = _make_3mf({"3D/Objects/o.model": model})
    assert strip_3mf_paint_color(raw) is raw


def test_extract_and_reapply_roundtrip():
    model = (
        b"<mesh><triangles>"
        b'<triangle v1="0" v2="1" v3="2" paint_color="1C"/>'
        b'<triangle v1="0" v2="1" v3="2"/>'
        b'<triangle v1="1" v2="2" v3="3" paint_color="2"/>'
        b"</triangles></mesh>"
    )
    raw = _make_3mf({"3D/Objects/o.model": model})
    paint = extract_3mf_paint_colors(raw)
    assert paint == {"3D/Objects/o.model": ["1C", None, "2"]}

    stripped = strip_3mf_paint_color(raw)
    with zipfile.ZipFile(BytesIO(stripped), "r") as zf:
        assert b"paint_color=" not in zf.read("3D/Objects/o.model")

    restored = reapply_3mf_paint_colors(stripped, paint)
    with zipfile.ZipFile(BytesIO(restored), "r") as zf:
        data = zf.read("3D/Objects/o.model")
    assert b'paint_color="1C"' in data
    assert b'paint_color="2"' in data
    # Middle triangle stays unpainted.
    assert data.count(b"paint_color=") == 2


def test_reapply_skips_triangle_count_mismatch():
    painted = _make_3mf(
        {
            "3D/Objects/o.model": (
                b'<triangle v1="0" v2="1" v3="2" paint_color="1"/><triangle v1="0" v2="1" v3="2" paint_color="2"/>'
            )
        }
    )
    paint = extract_3mf_paint_colors(painted)
    assert paint is not None
    # Result mesh has a different triangle count — refuse to guess.
    other = _make_3mf({"3D/Objects/o.model": b'<triangle v1="0" v2="1" v3="2"/>'})
    assert reapply_3mf_paint_colors(other, paint) is other


def test_extract_stl_from_simple_mesh():
    model = """<?xml version="1.0"?>
<model><resources><object id="1" type="model"><mesh>
<vertices>
<vertex x="0" y="0" z="0"/>
<vertex x="1" y="0" z="0"/>
<vertex x="0" y="1" z="0"/>
</vertices>
<triangles>
<triangle v1="0" v2="1" v3="2"/>
</triangles>
</mesh></object></resources></model>
"""
    raw = _make_3mf({"3D/Objects/o.model": model.encode()})
    stl = extract_3mf_meshes_as_stl(raw)
    assert stl is not None
    text = stl.decode()
    assert text.startswith("solid ")
    assert "vertex 0.0 0.0 0.0" in text or "vertex 0 0 0" in text
    assert "endsolid" in text


def test_extract_stl_returns_none_without_mesh():
    raw = _make_3mf({"Metadata/project_settings.config": b"{}"})
    assert extract_3mf_meshes_as_stl(raw) is None
