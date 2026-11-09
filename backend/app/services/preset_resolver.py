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

from backend.app.api.routes.orca_cloud import _build_authenticated_service as _build_orca_service
from backend.app.core.auth import is_auth_enabled
from backend.app.core.permissions import Permission
from backend.app.models.local_preset import LocalPreset
from backend.app.models.user import User
from backend.app.schemas.slicer import PresetRef
from backend.app.services.bambu_cloud import (
    BambuCloudAuthError,
    BambuCloudError,
    BambuCloudService,
)
from backend.app.services.bambu_cloud_credentials import get_stored_token
from backend.app.services.orca_cloud import OrcaCloudAuthError, OrcaCloudError
from backend.app.utils.slicer_strings import unescape_strings_cstyle, unquote_slicer_items

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

# String-list options Orca Cloud can return INI-encoded (#3380). The sidecar
# only fixes up `compatible_printers` when it is an array (#3250), so a
# process made for a user printer preset passes the Slice dialog's check and
# is then refused by the CLI.
_ORCA_STRING_LIST_FIELDS = ("compatible_printers", "filament_type", "default_filament_colour")
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


# The sign-in stored without a user belongs to an install with auth off. With
# auth on, a caller without a user (an API key without Allow Cloud Access)
# has no cloud sign-in of its own and must not borrow that one.
_NO_CLOUD_IDENTITY = "{cloud} presets need a signed-in user or an API key with Allow Cloud Access ({slot})"


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
    if user is None and await is_auth_enabled(db):
        raise HTTPException(status_code=403, detail=_NO_CLOUD_IDENTITY.format(cloud="Bambu Cloud", slot=slot))

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

    # `get_setting_detail` returns the wrapper envelope; the actual preset
    # JSON lives under `.setting`. Read it before identifying public stock
    # rows because Bambu's detail endpoint may omit the listing fields.
    payload = detail.get("setting") if isinstance(detail, dict) else None
    payload_name = payload.get("name") if isinstance(payload, dict) else None

    # Bambu's public/stock setting IDs use the GF* namespace; its personal
    # presets use PFU*/PFUS*. The public Cloud body is designed for the GUI and
    # can contain parameter encodings the headless CLI does not accept. The
    # reference ID comes directly from the listing response and is stable even
    # when its later detail response has no top-level setting_id/name.
    preset_name = detail.get("name") if isinstance(detail, dict) else None
    if not isinstance(preset_name, str) or not preset_name.strip():
        preset_name = payload_name
    if (
        isinstance(ref.id, str)
        and ref.id.upper().startswith("GF")
        and isinstance(preset_name, str)
        and preset_name.strip()
    ):
        return _resolve_standard(PresetRef(source="standard", id=preset_name), slot)

    # The sidecar wants the preset content, not the envelope.
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
    if isinstance(payload, dict):
        # Bambu Cloud labels presets with `type: "printer"` / `"print"` /
        # `"filament"`, but the BS / Orca CLI's `--load-settings` parser only
        # accepts `"machine"` / `"process"` / `"filament"`. Without this
        # rewrite the CLI exits -5 with `operator(): unknown config type`
        # and the sidecar surfaces a generic "The input preset file is
        # invalid and can not be parsed" — see preset_resolver header
        # comment for the silent-fail history. `from` gets the same
        # treatment: Bambu Cloud's filament details routinely arrive with
        # `from: ""` (or no `from` at all) and the CLI rejects either with
        # `operator(): ... from  unsupported` (same -5 exit). The standard
        # tier already pins `from: "system"` for exactly this reason; the
        # cloud tier needs the same pin because it lands at the same `--load-
        # settings` parser. The sidecar's `normalizeFromField` only rewrites
        # the `"User"` / `"System"` casings, not empty / missing values.
        payload = {**payload, "type": _SLOT_TO_PROFILE_TYPE[slot], "from": "system"}
    return json.dumps(payload)


async def _resolve_orca_cloud(db: AsyncSession, user: User | None, ref: PresetRef, slot: str) -> str:
    """Fetch a single profile from the user's separately paired, read-only
    Orca Cloud account and return its content JSON.

    The route-layer service builder handles JIT token refresh (atomically
    persisting rotation before this fetch) and stale-credential cleanup, so any
    exception here means a genuine fetch / network / not-found problem — never
    a "stale token" situation the caller could retry through. Permission gate
    matches the rest of the Orca Cloud surface so a user with
    ``LIBRARY_UPLOAD`` but no ``ORCA_CLOUD_AUTH`` cannot slice using cloud
    profiles even if their stored token survived a permission revocation.
    """
    if user is not None and not user.has_permission(Permission.ORCA_CLOUD_AUTH.value):
        raise HTTPException(
            status_code=403,
            detail=f"Orca Cloud presets require the orca_cloud:auth permission ({slot})",
        )
    if user is None and await is_auth_enabled(db):
        raise HTTPException(status_code=403, detail=_NO_CLOUD_IDENTITY.format(cloud="Orca Cloud", slot=slot))

    # Builder already produces the right user-facing error (401 not
    # connected, 401 session refresh failed, 502 unreachable).
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

    # ``profile`` is the ProfileUpsert shape — the inner ``content`` is the
    # actual slicer-format JSON. Fall back to forwarding the wrapper if the
    # shape doesn't match what we expect (defensive, in case Orca evolves
    # the wire format).
    content = profile.get("content") if isinstance(profile, dict) else None
    if not isinstance(content, dict):
        logger.info(
            "Orca Cloud preset %r for %s returned unexpected shape, forwarding raw payload",
            ref.id,
            slot,
        )
        content = profile
    if isinstance(content, dict):
        # Orca natively uses `machine` / `process` / `filament` for `type`,
        # which is what the CLI wants — but Bambu-imported profiles synced
        # through Orca Cloud can carry `printer` / `print` instead, and the
        # CLI's `--load-settings` parser rejects those the same way it does
        # for the Bambu Cloud tier. Force the slot-appropriate value so the
        # source tier doesn't decide whether slicing works. `from` gets the
        # same forced pin to `"system"` for the same reason — see the
        # Bambu Cloud branch above.
        content = {**content, "type": _SLOT_TO_PROFILE_TYPE[slot], "from": "system"}
        for key in _ORCA_STRING_LIST_FIELDS:
            raw = content.get(key)
            # Parsed the way the slicer would, empty items included, so
            # per-extruder positions survive. A string it can't parse is
            # forwarded as is.
            # Orca Cloud also sends the list form with quoted items.
            if isinstance(raw, str):
                items = unescape_strings_cstyle(raw)
            elif isinstance(raw, list):
                items = unquote_slicer_items(raw)
            else:
                items = None
            if items is not None:
                content[key] = items
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
