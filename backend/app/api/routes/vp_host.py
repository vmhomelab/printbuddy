"""OctoPrint/Moonraker-compatible upload endpoint for virtual printers (#52).

Bambu-compatible virtual printers emulate a Bambu Lab printer (SSDP, FTPS,
MQTT). That only helps for Bambu printer profiles: a slicer will not send a
Klipper/Prusa/OctoPrint printer's G-code over the Bambu network protocol.

A Moonraker-compatible virtual printer instead answers the small subset of the
OctoPrint and Moonraker HTTP APIs that slicers use to upload a job:

* OrcaSlicer / Snapmaker Orca / SuperSlicer, host type "Octo/Klipper", and
  PrusaSlicer, host type "OctoPrint" (also for binary ``.bgcode``):
  ``GET api/version``, ``POST api/files/local``
* Moonraker clients: ``GET server/info``, ``GET printer/info``,
  ``POST server/files/upload``

The slicer host URL is ``<printbuddy origin>/api/v1/vp-host/<vp id>`` and the
API key is the VP's generated ``api_key``. The uploaded file then goes through
the same VP pipeline as a Bambu upload (archive / review / print queue), and
the print queue dispatches it to the target printer through its provider.

The routes authenticate with the VP's API key only, never with a Printbuddy
login, so ``/api/v1/vp-host/`` is listed as a public prefix in the auth
middleware.
"""

from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vp-host/{vp_id}", tags=["virtual-printer-host"])

# Large multi-material G-code can reach a few hundred MB; anything beyond this
# is almost certainly not a print job.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
_CHUNK = 1024 * 1024

_SAFE_NAME = re.compile(r"[^\w.\- ()+\[\]]")

VERSION_TEXT = "OctoPrint 1.10.0 (Printbuddy virtual printer)"

# Printer providers whose firmware prints Prusa binary G-code (.bgcode).
BGCODE_PROVIDERS = {"prusalink", "prusaconnect"}


def _sanitize_filename(raw: str | None) -> str | None:
    """Reduce an uploaded name to a safe basename with an accepted extension."""
    if not raw:
        return None
    name = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = _SAFE_NAME.sub("_", name).lstrip(".")
    if not name:
        return None
    lower = name.lower()
    if not lower.endswith((".gcode", ".bgcode", ".3mf")):
        return None
    return name[:200]


def _unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    lower = name.lower()
    suffix = ".gcode.3mf" if lower.endswith(".gcode.3mf") else Path(name).suffix
    stem = name[: -len(suffix)]
    for index in range(1, 1000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}_{secrets.token_hex(4)}{suffix}"


def _presented_key(request: Request) -> str:
    key = request.headers.get("X-Api-Key") or request.query_params.get("apikey") or ""
    if not key:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:]
    return key.strip()


async def _authorize(vp_id: int, request: Request, db: AsyncSession):
    """Return ``(vp, None)`` for a valid key, else ``(None, error response)``.

    Unknown VP ids and wrong keys both return 401 so the endpoint can't be
    used to enumerate virtual printers.
    """
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer.manager import VP_PROTOCOL_MOONRAKER, vp_protocol

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    presented = _presented_key(request)
    if (
        vp is None
        or vp_protocol(vp) != VP_PROTOCOL_MOONRAKER
        or not vp.api_key
        or not presented
        or not secrets.compare_digest(presented.encode(), vp.api_key.encode())
    ):
        return None, JSONResponse(status_code=401, content={"error": "Invalid API key"})
    if not vp.enabled:
        return None, JSONResponse(status_code=409, content={"error": f"Virtual printer '{vp.name}' is disabled"})
    return vp, None


async def _bgcode_target_error(vp, db: AsyncSession) -> JSONResponse | None:
    """Reject .bgcode when the VP's target printer can't print binary G-code.

    Without this the upload is accepted and only fails later, when the print
    queue sends it to a Klipper/OctoPrint/Elegoo printer. VPs without a target
    (archive or review mode) still accept it: the user picks a printer later.
    """
    if not vp.target_printer_id:
        return None
    from backend.app.models.printer import Printer

    result = await db.execute(select(Printer).where(Printer.id == vp.target_printer_id))
    printer = result.scalar_one_or_none()
    if printer is None:
        return None
    provider = (printer.provider or "bambu").strip().lower()
    if provider in BGCODE_PROVIDERS:
        return None
    return JSONResponse(
        status_code=415,
        content={
            "error": (
                f"Binary G-code (.bgcode) can only be printed on Prusa printers (PrusaLink/PrusaConnect), "
                f"but the target printer '{printer.name}' needs plain G-code. In PrusaSlicer, turn off "
                f"'Supports binary G-code' in Printer Settings > General and send the job again."
            )
        },
    )


async def _store_and_dispatch(
    vp, file: UploadFile, request: Request, path_hint: str | None, db: AsyncSession
) -> JSONResponse | str:
    """Save the upload into the VP's upload dir and run the VP pipeline.

    Returns the stored filename, or an error response.
    """
    from backend.app.services.virtual_printer import virtual_printer_manager

    instance = virtual_printer_manager.get_instance(vp.id)
    if instance is None:
        # Enabled in the DB but not registered yet (e.g. startup still running).
        await virtual_printer_manager.sync_from_db()
        instance = virtual_printer_manager.get_instance(vp.id)
    if instance is None or not instance.is_http_host:
        return JSONResponse(status_code=503, content={"error": "Virtual printer is not running"})

    name = _sanitize_filename(file.filename) or _sanitize_filename(path_hint)
    if not name:
        return JSONResponse(status_code=415, content={"error": "Only .gcode, .bgcode and .3mf files are accepted"})
    if name.lower().endswith(".bgcode"):
        error = await _bgcode_target_error(vp, db)
        if error:
            logger.info("[VP %s] Rejected %s: target printer can't print binary G-code", vp.name, name)
            return error

    instance.upload_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(instance.upload_dir, name)
    written = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(_CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise ValueError("too large")
                out.write(chunk)
    except ValueError:
        dest.unlink(missing_ok=True)
        return JSONResponse(status_code=413, content={"error": "File too large"})
    except OSError as exc:
        dest.unlink(missing_ok=True)
        logger.error("[VP %s] Failed to store upload %s: %s", vp.name, name, exc)
        return JSONResponse(status_code=500, content={"error": "Could not store the uploaded file"})

    if written == 0:
        dest.unlink(missing_ok=True)
        return JSONResponse(status_code=400, content={"error": "Empty file"})

    source_ip = request.client.host if request.client else ""
    logger.info("[VP %s] HTTP upload %s (%d bytes) from %s", vp.name, dest.name, written, source_ip)
    await instance.on_file_received(dest, source_ip)
    return dest.name


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------
# OctoPrint API subset
# --------------------------------------------------------------------------


@router.get("/api/version")
async def octoprint_version(vp_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Connection test used by OrcaSlicer/PrusaSlicer before every upload."""
    _vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    return {"api": "0.1", "server": "1.10.0", "text": VERSION_TEXT}


@router.get("/api/server")
async def octoprint_server(vp_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    _vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    return {"version": "1.10.0", "safemode": None}


@router.post("/api/files/{location}")
async def octoprint_upload(
    vp_id: int,
    location: str,
    request: Request,
    file: UploadFile = File(...),
    path: str | None = Form(None),
    print_: str | None = Form(None, alias="print"),
    select_: str | None = Form(None, alias="select"),
    db: AsyncSession = Depends(get_db),
):
    """OctoPrint ``POST /api/files/local`` upload.

    The slicer's "print after upload" flag is accepted but the VP's mode
    decides what happens (archive, review or print queue); auto-dispatch in
    print-queue mode is what actually starts the job on the target printer.
    """
    vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    if location not in ("local", "sdcard"):
        return JSONResponse(status_code=404, content={"error": f"Unknown location {location}"})

    stored = await _store_and_dispatch(vp, file, request, path, db)
    if isinstance(stored, JSONResponse):
        return stored
    if _truthy(print_) or _truthy(select_):
        logger.debug("[VP %s] Slicer requested print/select for %s; handled by mode %s", vp.name, stored, vp.mode)

    return JSONResponse(
        status_code=201,
        content={
            "done": True,
            "files": {
                "local": {
                    "name": stored,
                    "display": stored,
                    "path": stored,
                    "origin": "local",
                    "refs": {"resource": str(request.url)},
                }
            },
        },
    )


# --------------------------------------------------------------------------
# Moonraker API subset
# --------------------------------------------------------------------------


@router.get("/server/info")
async def moonraker_server_info(vp_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    return {
        "result": {
            "klippy_connected": True,
            "klippy_state": "ready",
            "components": ["file_manager"],
            "failed_components": [],
            "registered_directories": ["gcodes"],
            "warnings": [],
            "websocket_count": 0,
            "moonraker_version": "printbuddy",
            "api_version": [1, 5, 0],
            "api_version_string": "1.5.0",
        }
    }


@router.get("/printer/info")
async def moonraker_printer_info(vp_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    return {
        "result": {
            "state": "ready",
            "state_message": "Printbuddy virtual printer",
            "hostname": vp.name,
            "software_version": "printbuddy",
        }
    }


@router.post("/server/files/upload")
async def moonraker_upload(
    vp_id: int,
    request: Request,
    file: UploadFile = File(...),
    root: str | None = Form(None),
    path: str | None = Form(None),
    print_: str | None = Form(None, alias="print"),
    db: AsyncSession = Depends(get_db),
):
    """Moonraker ``POST /server/files/upload``."""
    vp, error = await _authorize(vp_id, request, db)
    if error:
        return error
    if root and root != "gcodes":
        return JSONResponse(status_code=400, content={"error": f"Unsupported root {root}"})

    stored = await _store_and_dispatch(vp, file, request, path, db)
    if isinstance(stored, JSONResponse):
        return stored
    if _truthy(print_):
        logger.debug("[VP %s] Slicer requested print for %s; handled by mode %s", vp.name, stored, vp.mode)

    return JSONResponse(
        status_code=201,
        content={
            "result": {
                "item": {"path": stored, "root": "gcodes"},
                "print_started": False,
                "print_queued": vp.mode == "print_queue",
                "action": "create_file",
            }
        },
    )
