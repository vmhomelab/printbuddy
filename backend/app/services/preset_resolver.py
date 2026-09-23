"""Resolve a `PresetRef` (source + id) to the JSON-string content the
slicer-api sidecar's `/slice` endpoint expects.

Three sources, three paths:

- **local**   — read ``LocalPreset.setting`` from the DB. Existing pre-PR
                behaviour for the slicer integration; preserved verbatim
                so clients still sending bare integer ids see no change.
- **cloud**   — fetch ``BambuCloudService.get_setting_detail(id)`` for the
                caller's stored cloud token. Result is the full slicer-shape
                preset JSON the sidecar can ingest directly.
- **standard** — emit a stub ``{inherits: <name>, from: "system"}``. The
                 sidecar's `printbuddy/profile-resolver` branch already walks
                 ``inherits:`` against ``BUNDLED_PROFILES_PATH/<category>/<name>.json``
                 during ``materializeProfile`` and merges parent-then-child,
                 so the stub flattens out to the bundled content with no
                 round-trip needed for the JSON itself.

All three return the JSON as a *string* because that's what
``SlicerApiService.slice_with_profiles`` accepts as
``printer_profile_json`` etc. — the sidecar parses it once.
"""

from __future__ import annotations

import json
import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.cloud import get_stored_token
from backend.app.api.routes.orca_cloud import _build_authenticated_service as _build_orca_service
from backend.app.core.permissions import Permission
from backend.app.models.local_preset import LocalPreset
from backend.app.models.user import User
from backend.app.schemas.slicer import PresetRef
from backend.app.services.bambu_cloud import (
    BambuCloudAuthError,
    BambuCloudError,
    BambuCloudService,
)
from backend.app.services.orca_cloud import OrcaCloudAuthError, OrcaCloudError

logger = logging.getLogger(__name__)


_SLOT_TO_BUNDLED_CATEGORY = {
    "printer": "machine",
    "process": "process",
    "filament": "filament",
}

# The CLI's --load-settings parser uses the JSON's `type` field to decide
# how to interpret each file (machine/process/filament). Without it the
# CLI logs `operator(): unknown config type ... in load-settings`,
# writes `error_string: "The input preset file is invalid and can not be
# parsed.", return_code: -5` to result.json, and exits 0 — which the
# Node sidecar's child_process treats as silent success producing no
# output, then bubbles up as a generic "Failed to slice the model" 5xx.
# Printbuddy then falls back to the embedded-settings path for every 3MF
# slice, silently using whatever printer the source file was originally
# bound to. Setting `type` correctly per slot fixes the silent fallback.
_SLOT_TO_PROFILE_TYPE = {
    "printer": "machine",
    "process": "process",
    "filament": "filament",
}

# GUI-originated Bambu/Orca profiles use these exact string values as
# "inherit from parent" sentinels. The desktop UI resolves them before
# validation; the headless CLI does not. Keep this list deliberately narrow:
# removing every negative value would corrupt valid offsets and geometry.
_PROFILE_INHERIT_SENTINEL_KEYS = frozenset(
    {
        "raft_first_layer_expansion",
        "tree_support_wall_count",
        "prime_tower_brim_width",
    }
)


async def resolve_preset_ref(
    db: AsyncSession,
    user: User | None,
    ref: PresetRef,
    slot: str,
) -> str:
    """Return the JSON-string content for `ref` so the sidecar can ingest it.

    `slot` is one of ``"printer"`` / ``"process"`` / ``"filament"``; it's
    only used to generate friendly error messages and to pick the bundled
    category for the standard tier.

    Raises ``HTTPException`` for any caller-facing error (invalid id, wrong
    preset type, cloud auth failure, network error fetching cloud detail).
    """
    if ref.source == "local":
        content = await _resolve_local(db, ref, slot)
    elif ref.source == "cloud":
        content = await _resolve_cloud(db, user, ref, slot)
    elif ref.source == "orca_cloud":
        content = await _resolve_orca_cloud(db, user, ref, slot)
    elif ref.source == "standard":
        content = _resolve_standard(ref, slot)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset source for {slot}: {ref.source!r}",
        )
    return _normalise_profile_for_slicer(content, slot)


def _normalise_profile_for_slicer(content: str, slot: str) -> str:
    """Make a profile payload safe for Orca's strict CLI parser.

    Imported local and Bambu Cloud profiles are historical/user-controlled
    JSON and can omit, or use Bambu's alternate value for, ``type``. Orca's
    ``--load-settings`` requires its exact vocabulary (machine/process/
    filament), so establish it from PrintBuddy's already-validated slot.
    """
    expected_type = _SLOT_TO_PROFILE_TYPE.get(slot)
    if expected_type is None:
        raise HTTPException(status_code=400, detail=f"Unknown slot for slicer profile: {slot!r}")
    try:
        profile = json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {slot} preset JSON") from exc
    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail=f"Invalid {slot} preset JSON")
    # Profile JSON from the desktop/cloud APIs can carry the same literal
    # `"-1"` GUI-inheritance sentinels as an embedded project config. If such
    # a child profile is merged in the sidecar it overwrites the valid parent
    # with a CLI-invalid value. Dropping only known sentinel keys lets the
    # inherited parent/default provide the value without changing valid negative
    # values (e.g. z_offset).
    profile = {
        key: value for key, value in profile.items() if not (key in _PROFILE_INHERIT_SENTINEL_KEYS and value == "-1")
    }
    return json.dumps({**profile, "type": expected_type})


async def _resolve_local(db: AsyncSession, ref: PresetRef, slot: str) -> str:
    try:
        local_id = int(ref.id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid local preset id for {slot}: {ref.id!r}") from None
    preset = await db.get(LocalPreset, local_id)
    if preset is None or preset.preset_type != slot:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {slot} preset id (expected preset_type='{slot}')",
        )
    return preset.setting


async def _resolve_cloud(db: AsyncSession, user: User | None, ref: PresetRef, slot: str) -> str:
    """Fetch a single cloud preset detail. Permission gate matches the
    rest of the cloud surface (`CLOUD_AUTH`) so a user with `LIBRARY_UPLOAD`
    but no `CLOUD_AUTH` can't slice using cloud presets even if their
    ``User.cloud_token`` survived a permission revocation."""
    if user is not None and not user.has_permission(Permission.CLOUD_AUTH.value):
        raise HTTPException(
            status_code=403,
            detail=f"Cloud presets require the cloud:auth permission ({slot})",
        )

    token, _email, region = await get_stored_token(db, user)
    if not token:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cloud preset selected for {slot}, but no Bambu Cloud session is "
                "stored. Sign in to Bambu Cloud and retry."
            ),
        )

    cloud = BambuCloudService(region=region)
    cloud.set_token(token)
    try:
        detail = await cloud.get_setting_detail(ref.id)
    except BambuCloudAuthError:
        raise HTTPException(
            status_code=401,
            detail=(f"Bambu Cloud session expired while fetching {slot} preset. Sign in again and retry."),
        ) from None
    except BambuCloudError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Bambu Cloud unreachable while fetching {slot} preset: {e}",
        ) from e
    finally:
        await cloud.close()

    # Bambu's public/stock setting IDs use the GF* namespace; its personal
    # presets use PFU*/PFUS*. The public Cloud body is designed for the GUI and
    # can contain parameter encodings the headless CLI does not accept. We have
    # an exact immutable copy in the sidecar resources, so resolve the selected
    # public name there instead. Personal Cloud presets remain payload-backed.
    setting_id = detail.get("setting_id") if isinstance(detail, dict) else None
    preset_name = detail.get("name") if isinstance(detail, dict) else None
    if (
        isinstance(setting_id, str)
        and setting_id.upper().startswith("GF")
        and isinstance(preset_name, str)
        and preset_name.strip()
    ):
        return _resolve_standard(PresetRef(source="standard", id=preset_name), slot)

    # `get_setting_detail` returns the wrapper envelope; the actual preset
    # JSON lives under `.setting`. The sidecar wants the preset content, not
    # the envelope.
    payload = detail.get("setting") if isinstance(detail, dict) else None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid {slot} preset JSON from Bambu Cloud") from exc
    if not isinstance(payload, dict):
        # Some endpoints return the preset at the top level instead of
        # nested under `setting`. Fall back to the whole response in that
        # case rather than failing — the sidecar will reject it cleanly if
        # the shape is genuinely wrong, and we log the unusual response.
        logger.info(
            "Cloud preset %r for %s returned unexpected shape, forwarding raw payload",
            ref.id,
            slot,
        )
        payload = detail
    return json.dumps(payload)


async def _resolve_orca_cloud(db: AsyncSession, user: User | None, ref: PresetRef, slot: str) -> str:
    """Resolve a profile through the user's separately paired, read-only Orca
    Cloud account. The route builder handles proactive token refresh and atomically
    persists rotation before this fetch occurs."""
    if user is not None and not user.has_permission(Permission.ORCA_CLOUD_AUTH.value):
        raise HTTPException(
            status_code=403,
            detail=f"Orca Cloud presets require the orca_cloud:auth permission ({slot})",
        )

    svc = await _build_orca_service(db, user)
    try:
        profile = await svc.get_profile(ref.id)
    except OrcaCloudAuthError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Orca Cloud session expired while fetching {slot} preset. Sign in again and retry.",
        ) from e
    except OrcaCloudError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Orca Cloud {slot} preset {ref.id!r} not found.",
            ) from e
        raise HTTPException(
            status_code=502,
            detail=f"Orca Cloud unreachable while fetching {slot} preset: {e}",
        ) from e
    finally:
        await svc.close()

    content = profile.get("content") if isinstance(profile, dict) else None
    if not isinstance(content, dict):
        logger.info(
            "Orca Cloud preset %r for %s returned unexpected shape, forwarding raw payload",
            ref.id,
            slot,
        )
        content = profile
    if isinstance(content, dict):
        # Orca can contain Bambu-style printer/print labels. Normalize every
        # source to the CLI's machine/process/filament vocabulary.
        content = {**content, "type": _SLOT_TO_PROFILE_TYPE[slot], "from": "system"}
    return json.dumps(content)


def _resolve_standard(ref: PresetRef, slot: str) -> str:
    """Build a minimal `{name, inherits, from, type}` stub. The sidecar's
    resolver walks `BUNDLED_PROFILES_PATH/<category>/<name>.json` and merges,
    yielding the full bundled preset without us round-tripping the content
    through Printbuddy."""
    if slot not in _SLOT_TO_BUNDLED_CATEGORY:
        raise HTTPException(status_code=400, detail=f"Unknown slot for standard preset: {slot!r}")
    return json.dumps(
        {
            # `name` must be set so the sidecar's compatibility checks see a
            # populated value. Reusing the bundled name keeps the resolved
            # profile's identity consistent with what the user picked.
            "name": ref.id,
            "inherits": ref.id,
            # `from: "system"` skips the User/system compatibility rejection
            # the resolver was designed to fix for OrcaSlicer GUI exports —
            # we never want a bundled preset to be treated as User-authored.
            "from": "system",
            # `type` is required by the CLI's --load-settings parser — see
            # _SLOT_TO_PROFILE_TYPE above for the silent-failure mode.
            "type": _SLOT_TO_PROFILE_TYPE[slot],
        }
    )
