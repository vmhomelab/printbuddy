"""Orca 2.5 rejects concrete --load-settings JSONs that still name a parent."""

from __future__ import annotations

import json

from backend.app.services.preset_resolver import _strip_inherits_if_concrete


def test_strips_inherits_from_concrete_process():
    raw = json.dumps(
        {
            "name": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
            "type": "process",
            "from": "system",
            "inherits": "fdm_process_U1_0.20",
            "layer_height": "0.2",
            "wall_loops": "3",
            "sparse_infill_density": "15%",
            "top_shell_layers": "5",
            "bottom_shell_layers": "3",
            "compatible_printers": ["Snapmaker U1 (0.4 nozzle)"],
        }
    )
    out = json.loads(_strip_inherits_if_concrete(raw))
    assert "inherits" not in out
    assert out["layer_height"] == "0.2"
    assert out["compatible_printers"] == ["Snapmaker U1 (0.4 nozzle)"]


def test_keeps_inherits_on_standard_stub():
    raw = json.dumps(
        {
            "name": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
            "inherits": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
            "from": "system",
            "type": "process",
        }
    )
    assert _strip_inherits_if_concrete(raw) == raw


def test_noop_without_inherits():
    raw = json.dumps({"name": "X", "type": "machine", "from": "system", "nozzle_diameter": ["0.4"]})
    assert _strip_inherits_if_concrete(raw) == raw
