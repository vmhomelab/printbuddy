"""inherits is stripped only after a confirmed parent flatten."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.services.preset_resolver import _flatten_and_strip_inherits


@pytest.mark.asyncio
async def test_strips_inherits_only_when_parent_keys_merge():
    raw = json.dumps(
        {
            "name": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
            "type": "process",
            "from": "system",
            "inherits": "fdm_process_U1_0.20",
            "layer_height": "0.2",
            "wall_loops": "3",
        }
    )
    # Flattened result has more keys than the child alone → confirmed merge.
    flattened = {
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
    db = AsyncMock()
    with patch("backend.app.services.preset_resolver.resolve_preset", new=AsyncMock(return_value=flattened)):
        out = json.loads(await _flatten_and_strip_inherits(db, raw, "process"))
    assert "inherits" not in out
    assert out["layer_height"] == "0.2"
    assert out["sparse_infill_density"] == "15%"


@pytest.mark.asyncio
async def test_keeps_inherits_when_parent_unresolved():
    raw = json.dumps(
        {
            "name": "Custom child",
            "type": "process",
            "from": "User",
            "inherits": "missing_parent",
            "layer_height": "0.2",
            "wall_loops": "3",
            "sparse_infill_density": "20%",
            "top_shell_layers": "4",
            "bottom_shell_layers": "4",
            "extra_a": "1",
            "extra_b": "2",
        }
    )
    child = json.loads(raw)
    db = AsyncMock()
    # resolve_preset returns the child unchanged when the parent is missing.
    with patch("backend.app.services.preset_resolver.resolve_preset", new=AsyncMock(return_value=child)):
        out = await _flatten_and_strip_inherits(db, raw, "process")
    assert out == raw
    assert json.loads(out)["inherits"] == "missing_parent"


@pytest.mark.asyncio
async def test_noop_without_inherits():
    raw = json.dumps({"name": "X", "type": "machine", "from": "system", "nozzle_diameter": ["0.4"]})
    db = AsyncMock()
    with patch("backend.app.services.preset_resolver.resolve_preset", new=AsyncMock()) as resolve:
        assert await _flatten_and_strip_inherits(db, raw, "printer") == raw
        resolve.assert_not_called()
