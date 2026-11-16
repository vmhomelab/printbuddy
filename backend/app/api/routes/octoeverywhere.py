"""API routes for the OctoEverywhere Gadget AI failure-detection provider (PB-35).

Settings live in their own endpoints (not the generic /settings payload) so the
API key can be stored encrypted and is never returned to any caller.
"""

import json
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.settings import get_setting, set_setting
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.encryption import mfa_decrypt, mfa_encrypt
from backend.app.core.permissions import Permission
from backend.app.models.user import User
from backend.app.schemas.octoeverywhere import (
    OctoEverywhereSettings,
    OctoEverywhereSettingsUpdate,
    OctoEverywhereTestRequest,
    OctoEverywhereTestResult,
)
from backend.app.services import octoeverywhere_detection as svc_module
from backend.app.services.octoeverywhere_detection import (
    KEY_ACTION,
    KEY_API_KEY,
    KEY_ENABLED,
    KEY_ENABLED_PRINTERS,
    KEY_NOTIFY_ON_WARNING,
    KEY_POLL_INTERVAL,
    KEY_SENSITIVITY,
    octoeverywhere_detection_service,
    parse_enabled_printers,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/octoeverywhere", tags=["octoeverywhere"])


async def _read_settings(db: AsyncSession) -> OctoEverywhereSettings:
    sensitivity = await get_setting(db, KEY_SENSITIVITY) or "medium"
    action = await get_setting(db, KEY_ACTION) or "notify"
    try:
        poll_interval = int(await get_setting(db, KEY_POLL_INTERVAL) or 0)
    except ValueError:
        poll_interval = 0
    return OctoEverywhereSettings(
        enabled=(await get_setting(db, KEY_ENABLED) or "false").lower() == "true",
        has_api_key=bool(await get_setting(db, KEY_API_KEY)),
        sensitivity=sensitivity if sensitivity in svc_module.SENSITIVITIES else "medium",
        action=action if action in svc_module.ACTIONS else "notify",
        poll_interval=poll_interval,
        enabled_printers=parse_enabled_printers(await get_setting(db, KEY_ENABLED_PRINTERS)),
        notify_on_warning=(await get_setting(db, KEY_NOTIFY_ON_WARNING) or "true").lower() == "true",
    )


@router.get("/settings", response_model=OctoEverywhereSettings)
async def get_octoeverywhere_settings(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    return await _read_settings(db)


@router.put("/settings", response_model=OctoEverywhereSettings)
async def update_octoeverywhere_settings(
    body: OctoEverywhereSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    if body.api_key is not None:
        key = body.api_key.strip()
        await set_setting(db, KEY_API_KEY, mfa_encrypt(key) if key else "")
    if body.enabled is not None:
        await set_setting(db, KEY_ENABLED, "true" if body.enabled else "false")
    if body.sensitivity is not None:
        await set_setting(db, KEY_SENSITIVITY, body.sensitivity)
    if body.action is not None:
        await set_setting(db, KEY_ACTION, body.action)
    if body.poll_interval is not None:
        await set_setting(db, KEY_POLL_INTERVAL, str(body.poll_interval))
    if body.all_printers:
        await set_setting(db, KEY_ENABLED_PRINTERS, "")
    elif body.enabled_printers is not None:
        await set_setting(db, KEY_ENABLED_PRINTERS, json.dumps(sorted(set(body.enabled_printers))))
    if body.notify_on_warning is not None:
        await set_setting(db, KEY_NOTIFY_ON_WARNING, "true" if body.notify_on_warning else "false")
    await db.commit()
    return await _read_settings(db)


@router.get("/status")
async def get_octoeverywhere_status(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    """Service state, per-printer results and recent detections. Never includes context IDs or URLs."""
    settings = await _read_settings(db)
    return {
        **octoeverywhere_detection_service.get_status(),
        "enabled": settings.enabled,
        "has_api_key": settings.has_api_key,
    }


@router.post("/test-connection", response_model=OctoEverywhereTestResult)
async def test_octoeverywhere_connection(
    body: OctoEverywhereTestRequest,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Validate the API key (given, or stored) by creating and cancelling a free context."""
    api_key = (body.api_key or "").strip()
    if not api_key:
        stored = await get_setting(db, KEY_API_KEY) or ""
        if stored:
            try:
                api_key = mfa_decrypt(stored)
            except RuntimeError:
                return OctoEverywhereTestResult(
                    ok=False, error="Stored API key cannot be decrypted; re-enter it in Settings"
                )
    return OctoEverywhereTestResult(**await octoeverywhere_detection_service.test_connection(api_key))
