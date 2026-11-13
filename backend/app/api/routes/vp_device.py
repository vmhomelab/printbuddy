"""Printer dashboard for the slicer's "Device" tab (#52).

OrcaSlicer (and Snapmaker Orca) open the physical printer's host URL in their
"Device" tab and switch to it after a job is sent. For a Moonraker-compatible
virtual printer that URL is ``<printbuddy>/api/v1/vp-host/<vp id>``, which so
far answered ``{"detail": "Not found"}``.

This module serves a small standalone dashboard there instead:

* ``GET  /vp-host/<id>`` (and ``/``): the HTML shell. It holds no printer data,
  so it is served without a key.
* ``GET  /vp-host/<id>/device/app.js|app.css``: its static assets.
* ``GET  /vp-host/<id>/device/api/state``: status, temperatures, material and
  camera of the VP's target printer.
* ``POST /vp-host/<id>/device/api/camera-token``: a camera stream token for the
  ``<img>`` stream.
* ``POST /vp-host/<id>/device/api/control/<action>``: pause, resume, stop,
  temperature, cooldown, fan and light on the target printer.

The data and control routes use the VP's API key like the upload API. Orca
loads the page with its own web view and adds the configured API key as an
``X-API-Key`` header to every ``fetch`` the page makes; the page also accepts
``?apikey=`` in its URL (for the "Device UI" field or another browser).

Each printer set up in the slicer points at its own virtual printer, so the
dashboard shows and controls only that VP's target printer and nothing else
in Printbuddy. A VP without a target printer shows a hint to pick one.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.vp_host import _authorize
from backend.app.core.config import settings as app_settings
from backend.app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vp-host/{vp_id}", tags=["virtual-printer-device"])

ASSET_DIR = Path(__file__).resolve().parents[2] / "web" / "vp_device"
ASSETS = {"app.js": "text/javascript", "app.css": "text/css"}
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

ACTIVE_STATES = ("RUNNING", "PAUSE", "PREPARE", "SLICING")
NO_TARGET = {"error": "This virtual printer has no target printer", "code": "no_target_printer"}
MAX_SLOTS = 16
_EXTRUDER_KEY = re.compile(r"^extruder(\d*)$")


# --------------------------------------------------------------------------
# Page and assets
# --------------------------------------------------------------------------


def _render_index(vp_id: int) -> str:
    template = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    base = f"{app_settings.api_prefix}/vp-host/{int(vp_id)}"
    return template.replace("{{BASE}}", html.escape(base, quote=True))


@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def device_page(vp_id: int):
    """HTML shell of the dashboard. Contains no printer data."""
    return HTMLResponse(_render_index(vp_id), headers=NO_CACHE)


@router.get("/device/{asset}", include_in_schema=False)
async def device_asset(vp_id: int, asset: str):
    media_type = ASSETS.get(asset)
    if media_type is None:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return FileResponse(ASSET_DIR / asset, media_type=media_type, headers=NO_CACHE)


# --------------------------------------------------------------------------
# Status normalisation
# --------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 1)


def _temperature_rows(temps: Any) -> list[dict[str, Any]]:
    """Flatten the provider temperature dicts into display rows.

    Bambu reports ``nozzle``/``nozzle_2``/``bed``/``chamber`` (+ ``_target``);
    Moonraker reports ``nozzle``/``bed`` plus the raw heater objects, so a
    multi-tool Klipper printer (Snapmaker U1) adds ``extruder1``..``extruderN``.
    """
    if not isinstance(temps, dict):
        return []
    rows: list[dict[str, Any]] = []

    def add(kind: str, index: int | None, current: Any, target: Any) -> None:
        cur = _num(current)
        if cur is None:
            return
        rows.append({"kind": kind, "index": index, "current": cur, "target": _num(target) or 0.0})

    extruders = sorted(
        (int(match.group(1) or 0), value)
        for key, value in temps.items()
        if (match := _EXTRUDER_KEY.match(str(key))) and isinstance(value, dict)
    )
    if len(extruders) > 1:
        for index, values in extruders:
            add("nozzle", index, values.get("temperature"), values.get("target"))
    else:
        if "nozzle" in temps:
            add("nozzle", None if "nozzle_2" not in temps else 0, temps.get("nozzle"), temps.get("nozzle_target"))
        if "nozzle_2" in temps:
            add("nozzle", 1, temps.get("nozzle_2"), temps.get("nozzle_2_target"))
    if "bed" in temps:
        add("bed", None, temps.get("bed"), temps.get("bed_target"))
    if "chamber" in temps:
        add("chamber", None, temps.get("chamber"), temps.get("chamber_target"))
    else:
        for key, values in temps.items():
            if isinstance(values, dict) and "chamber" in str(key).lower():
                add("chamber", None, values.get("temperature"), values.get("target"))
                break
    return rows


def _hex_color(raw: Any) -> str | None:
    value = str(raw or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value):
        return "#" + value[:6].lower()
    return None


def _material_slots(status: Any) -> list[dict[str, Any]]:
    """Spools/feeders of the printer, with the active one marked."""
    slots: list[dict[str, Any]] = []
    tray_now = getattr(status, "tray_now", 255)
    for unit in getattr(status, "ams", None) or []:
        is_tool_unit = (unit.module_type or "") == "snapmaker_u1"
        for tray in unit.tray or []:
            if not (tray.tray_type or tray.tray_color):
                continue
            global_id = unit.id * 4 + tray.id
            label = f"T{tray.id}" if is_tool_unit else f"{chr(65 + unit.id % 26)}{tray.id + 1}"
            active = getattr(status, "active_extruder", None) == tray.id if is_tool_unit else tray_now == global_id
            slots.append(
                {
                    "label": label,
                    "type": tray.tray_sub_brands or tray.tray_type or "",
                    "color": _hex_color(tray.tray_color),
                    "active": bool(active),
                }
            )
    for tray in getattr(status, "vt_tray", None) or []:
        if tray.tray_type or tray.tray_color:
            slots.append(
                {
                    "label": "Ext",
                    "type": tray.tray_sub_brands or tray.tray_type or "",
                    "color": _hex_color(tray.tray_color),
                    "active": tray_now == 254,
                }
            )
    if not slots:
        for index, slot in enumerate(getattr(status, "tool_slots", None) or []):
            if not isinstance(slot, dict):
                continue
            slots.append(
                {
                    "label": str(slot.get("label") or slot.get("name") or f"T{index}"),
                    "type": str(slot.get("material") or slot.get("filament_type") or slot.get("type") or ""),
                    "color": _hex_color(slot.get("color") or slot.get("tray_color")),
                    "active": bool(slot.get("active")),
                }
            )
    return slots[:MAX_SLOTS]


def _has_camera(printer: Any, connected: bool) -> bool:
    from backend.app.services.elegoo_camera import get_effective_camera_source

    try:
        if get_effective_camera_source(printer).enabled:
            return True
    except Exception:  # noqa: BLE001 - a bad camera config must not break the dashboard
        logger.debug("Camera source lookup failed for printer %s", getattr(printer, "id", "?"), exc_info=True)
    return (printer.provider or "bambu") == "bambu" and connected


async def _target_printer(vp, db: AsyncSession):
    """The VP's target printer, or None when unset, deleted or deactivated."""
    from backend.app.models.printer import Printer

    if not vp.target_printer_id:
        return None
    result = await db.execute(select(Printer).where(Printer.id == vp.target_printer_id))
    printer = result.scalar_one_or_none()
    if printer is None or not printer.is_active:
        return None
    return printer


async def _build_state(vp, db: AsyncSession) -> dict[str, Any]:
    from backend.app.api.routes.printers import get_printer_status

    payload: dict[str, Any] = {
        "vp": {"id": vp.id, "name": vp.name, "mode": vp.mode, "target_printer_id": vp.target_printer_id},
        "printer": None,
    }
    printer = await _target_printer(vp, db)
    if printer is None:
        return payload

    prefix = app_settings.api_prefix
    status = await get_printer_status(printer_id=printer.id, _=None, db=db)
    connected = bool(status.connected)
    state = (status.state or "").upper() or None
    payload["printer"] = {
        "id": printer.id,
        "name": printer.name,
        "model": printer.model,
        "provider": printer.provider or "bambu",
        "ip_address": printer.ip_address,
        "connected": connected,
        "state": state,
        "is_active_job": state in ACTIVE_STATES,
        "file": status.subtask_name or status.current_print or status.gcode_file,
        "progress": _num(status.progress),
        "remaining_minutes": status.remaining_time,
        "layer": status.layer_num,
        "total_layers": status.total_layers,
        "cover_path": f"{prefix}/printers/{printer.id}/cover" if status.cover_url else None,
        "temperatures": _temperature_rows(status.temperatures),
        "materials": _material_slots(status),
        "fans": {
            "part": status.cooling_fan_speed,
            "aux": status.big_fan1_speed,
            "chamber": status.big_fan2_speed,
        },
        "light": {
            "on": bool(status.chamber_light),
            "supported": status.chamber_light_supported is not False,
        },
        "chamber_heater": bool(status.chamber_heater_supported),
        "errors": [{"code": str(err.code or ""), "severity": err.severity} for err in (status.hms_errors or [])[:5]],
        "camera": {
            "available": _has_camera(printer, connected),
            "stream_path": f"{prefix}/printers/{printer.id}/camera/stream",
            "snapshot_path": f"{prefix}/printers/{printer.id}/camera/snapshot",
        },
    }
    return payload


# --------------------------------------------------------------------------
# Data and control API (VP API key)
# --------------------------------------------------------------------------


@router.get("/device/api/state")
async def device_state(
    vp_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    return JSONResponse(await _build_state(vp, db), headers=NO_CACHE)


@router.post("/device/api/camera-token")
async def device_camera_token(vp_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Token for the camera ``<img>`` (it cannot send the API key header)."""
    from backend.app.core.auth import CAMERA_STREAM_TOKEN_EXPIRE_MINUTES, create_camera_stream_token

    _vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    return {"token": await create_camera_stream_token(), "expires_in": CAMERA_STREAM_TOKEN_EXPIRE_MINUTES * 60}


class DeviceAction(BaseModel):
    heater: str | None = None  # nozzle | bed | chamber
    target: int | None = None
    fan: str | None = None  # part | aux | chamber
    speed: int | None = None
    on: bool | None = None


ACTIONS = ("pause", "resume", "stop", "temperature", "cooldown", "fan", "light")


@router.post("/device/api/control/{action}")
async def device_action(
    vp_id: int,
    action: str,
    request: Request,
    body: DeviceAction | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Run a printer control on the VP's target printer.

    Only the target printer can be controlled; there is no printer id in the
    request. Delegates to the regular printer routes so every provider keeps its own
    checks; their ``HTTPException`` errors pass through unchanged.
    """
    from backend.app.api.routes import printers as printer_routes

    vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    if action not in ACTIONS:
        return JSONResponse(status_code=404, content={"error": f"Unknown action {action}"})
    printer = await _target_printer(vp, db)
    if printer is None:
        return JSONResponse(status_code=409, content=NO_TARGET)
    printer_id = printer.id
    body = body or DeviceAction()
    logger.info("[VP %s] Device dashboard: %s on printer %s", vp.name, action, printer_id)

    if action == "pause":
        return await printer_routes.pause_print(printer_id=printer_id, _=None, db=db)
    if action == "resume":
        return await printer_routes.resume_print(printer_id=printer_id, _=None, db=db)
    if action == "stop":
        return await printer_routes.stop_print(printer_id=printer_id, _=None, db=db)
    if action == "light":
        return await printer_routes.set_chamber_light(printer_id=printer_id, on=bool(body.on), _=None, db=db)
    if action == "fan":
        if body.fan not in ("part", "aux", "chamber") or body.speed is None:
            return JSONResponse(status_code=400, content={"error": "fan must be part, aux or chamber with a speed"})
        speed = max(0, min(100, int(body.speed)))
        return await printer_routes.set_fan_speed(printer_id=printer_id, fan=body.fan, speed=speed, _=None, db=db)

    setters = {
        "nozzle": printer_routes.set_nozzle_temperature,
        "bed": printer_routes.set_bed_temperature,
        "chamber": printer_routes.set_chamber_temperature,
    }
    if action == "cooldown":
        await setters["nozzle"](printer_id=printer_id, target=0, _=None, db=db)
        await setters["bed"](printer_id=printer_id, target=0, _=None, db=db)
        return {"success": True, "message": "Nozzle and bed heaters off"}

    # action == "temperature"
    setter = setters.get(body.heater or "")
    if setter is None or body.target is None:
        return JSONResponse(status_code=400, content={"error": "heater must be nozzle, bed or chamber with a target"})
    return await setter(printer_id=printer_id, target=int(body.target), _=None, db=db)
