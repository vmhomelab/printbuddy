"""Regression: BBL parents must not resolve from the Snapmaker folder."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services import orca_profiles
from backend.app.services.orca_profiles import (
    _cache_key,
    _vendors_for_lookup,
    fetch_and_cache_base_profile,
    infer_profile_vendor,
    resolve_preset,
)


def test_infer_vendor_prefers_child_printer_model_over_fdm_parent():
    child = {
        "name": "Bambu PLA Basic @BBL X1C",
        "inherits": "fdm_filament_pla",
        "printer_model": "Bambu Lab X1 Carbon",
        "filament_vendor": ["Bambu Lab"],
    }
    assert infer_profile_vendor(child) == "BBL"


def test_infer_vendor_snapmaker_from_printer_model():
    child = {
        "name": "0.20 Standard @Snapmaker U1 (0.4 nozzle)",
        "inherits": "fdm_process_common",
        "printer_model": "Snapmaker U1",
    }
    assert infer_profile_vendor(child) == "Snapmaker"


def test_vendors_for_bare_fdm_parent_keep_bbl_first():
    """A bare fdm_* parent must not promote Snapmaker ahead of BBL."""
    vendors = _vendors_for_lookup("fdm_filament_pla", preferred_vendor=None)
    assert vendors[0] == "BBL"
    assert "Snapmaker" in vendors


def test_vendors_for_snapmaker_preferred_put_snapmaker_first():
    vendors = _vendors_for_lookup("fdm_filament_pla", preferred_vendor="Snapmaker")
    assert vendors[0] == "Snapmaker"


@pytest.mark.asyncio
async def test_bbl_filament_chain_resolves_bbl_fdm_filament_pla():
    """BBL PLA Basic → … → fdm_filament_pla must load the BBL parent.

    Preferring Snapmaker for every fdm_* name previously injected Snapmaker
    base values into normal Bambu chains and cached them under the bare name.
    """
    child = {
        "name": "Bambu PLA Basic @BBL X1C",
        "inherits": "fdm_filament_pla",
        "filament_vendor": ["Bambu Lab"],
        "filament_type": ["PLA"],
        "bridge_speed": ["50"],
    }
    bbl_parent = {
        "name": "fdm_filament_pla",
        "from": "system",
        "bridge_speed": ["50"],
        "filament_type": ["PLA"],
        "vendor_marker": "BBL",
    }

    async def fake_fetch(name, profile_type, db, *, preferred_vendor=None):
        assert name == "fdm_filament_pla"
        assert preferred_vendor == "BBL"
        return dict(bbl_parent)

    db = MagicMock()
    with patch.object(orca_profiles, "fetch_and_cache_base_profile", new=AsyncMock(side_effect=fake_fetch)):
        merged = await resolve_preset(child, "filament", db)

    assert merged["vendor_marker"] == "BBL"
    assert merged["name"] == "Bambu PLA Basic @BBL X1C"
    assert merged["inherits"] == "fdm_filament_pla"


@pytest.mark.asyncio
async def test_fetch_caches_under_vendor_scoped_key():
    db = MagicMock()
    # Cache probe + insert lookup (and any fallback vendor probes) all miss.
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.add = MagicMock()

    payload = {"name": "fdm_filament_pla", "vendor_marker": "BBL"}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return payload

    with patch("backend.app.services.orca_profiles.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client.get = AsyncMock(return_value=_Resp())
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = client

        data = await fetch_and_cache_base_profile(
            "fdm_filament_pla",
            "filament",
            db,
            preferred_vendor="BBL",
        )

    assert data == payload
    assert db.add.called
    cached = db.add.call_args.args[0]
    assert cached.name == _cache_key("BBL", "fdm_filament_pla")
    assert json.loads(cached.setting)["vendor_marker"] == "BBL"


@pytest.mark.asyncio
async def test_preferred_vendor_queries_github_before_other_vendor_cache():
    """Snapmaker cache must not win when the preferred vendor is BBL.

    Repro from PR #41 review: only Snapmaker/fdm_filament_pla is cached and
    the network is stubbed. A BBL child must still fetch BBL from GitHub
    instead of returning the Snapmaker row from the fallback cache walk.
    """
    snapmaker_parent = {
        "name": "fdm_filament_pla",
        "vendor_marker": "Snapmaker",
        "bridge_speed": ["25"],
    }
    bbl_parent = {
        "name": "fdm_filament_pla",
        "vendor_marker": "BBL",
        "bridge_speed": ["50"],
    }

    async def fake_cached(name, db, *, vendor=None):
        assert name == "fdm_filament_pla"
        if vendor == "Snapmaker":
            return dict(snapmaker_parent)
        return None

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def json(self):
            return self._payload

    async def fake_get(url):
        if "/BBL/" in url:
            return _Resp(bbl_parent)
        return MagicMock(status_code=404)

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.add = MagicMock()

    with (
        patch.object(orca_profiles, "get_cached_base_profile", new=AsyncMock(side_effect=fake_cached)),
        patch("backend.app.services.orca_profiles.httpx.AsyncClient") as client_cls,
    ):
        client = AsyncMock()
        client.get = AsyncMock(side_effect=fake_get)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = client

        child = {
            "name": "My PLA",
            "filament_settings_id": "Bambu PLA Basic @BBL X1C",
            "inherits": "fdm_filament_pla",
        }
        assert infer_profile_vendor(child) == "BBL"
        merged = await resolve_preset(child, "filament", db)

    assert merged["vendor_marker"] == "BBL"
    assert merged["bridge_speed"] == ["50"]
    # GitHub was consulted for BBL rather than short-circuiting on Snapmaker cache.
    assert any("/BBL/" in call.args[0] for call in client.get.await_args_list)
    assert db.add.called
    assert db.add.call_args.args[0].name == _cache_key("BBL", "fdm_filament_pla")


@pytest.mark.asyncio
async def test_resolve_preset_ref_skips_flatten_for_bambu_studio():
    """Bambu Studio must keep inherits so the sidecar walks stock BBL parents."""
    from backend.app.schemas.slicer import PresetRef
    from backend.app.services import preset_resolver

    db = MagicMock()
    preset = MagicMock()
    preset.preset_type = "filament"
    preset.setting = json.dumps(
        {
            "name": "Bambu PLA Basic @BBL X1C",
            "inherits": "fdm_filament_pla",
            "filament_type": ["PLA"],
        }
    )
    db.get = AsyncMock(return_value=preset)

    with patch.object(preset_resolver, "_flatten_and_strip_inherits", new=AsyncMock()) as flatten:
        out = await preset_resolver.resolve_preset_ref(
            db,
            None,
            PresetRef(source="local", id="7"),
            slot="filament",
            slicer="bambu_studio",
        )

    flatten.assert_not_awaited()
    payload = json.loads(out)
    assert payload["inherits"] == "fdm_filament_pla"
    assert payload["type"] == "filament"


@pytest.mark.asyncio
async def test_resolve_preset_ref_flattens_snapmaker_for_orcaslicer():
    from backend.app.schemas.slicer import PresetRef
    from backend.app.services import preset_resolver

    db = MagicMock()
    preset = MagicMock()
    preset.preset_type = "process"
    preset.setting = json.dumps(
        {
            "name": "0.20 Standard @Snapmaker U1",
            "inherits": "fdm_process_common",
            "printer_model": "Snapmaker U1",
            "layer_height": "0.2",
        }
    )
    db.get = AsyncMock(return_value=preset)

    flattened = json.dumps(
        {
            "name": "0.20 Standard @Snapmaker U1",
            "printer_model": "Snapmaker U1",
            "layer_height": "0.2",
            "bridge_speed": ["25"],
            "type": "process",
        }
    )
    with patch.object(
        preset_resolver,
        "_flatten_and_strip_inherits",
        new=AsyncMock(return_value=flattened),
    ) as flatten:
        out = await preset_resolver.resolve_preset_ref(
            db,
            None,
            PresetRef(source="local", id="7"),
            slot="process",
            slicer="orcaslicer",
        )

    flatten.assert_awaited_once()
    assert json.loads(out)["bridge_speed"] == ["25"]


@pytest.mark.asyncio
async def test_resolve_preset_ref_keeps_bbl_inherits_on_orcaslicer():
    """Stock BBL chains should keep inherits for the sidecar's bundled walk."""
    from backend.app.schemas.slicer import PresetRef
    from backend.app.services import preset_resolver

    db = MagicMock()
    preset = MagicMock()
    preset.preset_type = "filament"
    preset.setting = json.dumps(
        {
            "name": "Bambu PLA Basic @BBL X1C",
            "inherits": "fdm_filament_pla",
            "filament_vendor": ["Bambu Lab"],
            "filament_type": ["PLA"],
        }
    )
    db.get = AsyncMock(return_value=preset)

    with patch.object(preset_resolver, "_flatten_and_strip_inherits", new=AsyncMock()) as flatten:
        out = await preset_resolver.resolve_preset_ref(
            db,
            None,
            PresetRef(source="local", id="7"),
            slot="filament",
            slicer="orcaslicer",
        )

    flatten.assert_not_awaited()
    assert json.loads(out)["inherits"] == "fdm_filament_pla"
