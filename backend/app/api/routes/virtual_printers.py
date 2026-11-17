import logging
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequestPrinterScope, RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.core.printer_scope import PrinterScope
from backend.app.models.user import User
from backend.app.schemas.not_null import IgnoresNullForRequiredColumns
from backend.app.schemas.virtual_printer import VPDiagnosticResult

# Imported at module scope so tests can patch
# backend.app.api.routes.virtual_printers.tailscale_service.
from backend.app.services.virtual_printer.tailscale import tailscale_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/virtual-printers", tags=["virtual-printers"])


class TailscaleStatusResponse(BaseModel):
    available: bool
    fqdn: str
    hostname: str
    tailnet_name: str
    tailscale_ips: list[str]
    error: str | None


class VirtualPrinterCreate(BaseModel):
    name: str = "Printbuddy"
    enabled: bool = False
    # "bambu" (default, emulates a Bambu printer) or "moonraker" (OctoPrint/
    # Moonraker-compatible HTTP upload endpoint for non-Bambu printers, #52).
    # Fixed at creation time.
    protocol: str = "bambu"
    mode: str = "archive"
    model: str | None = None
    access_code: str | None = None
    target_printer_id: int | None = None
    auto_dispatch: bool = True
    queue_force_color_match: bool = False
    save_ams_mapping: bool = False
    gcode_injection: bool = False
    bind_ip: str | None = None
    remote_interface_ip: str | None = None


class VirtualPrinterUpdate(IgnoresNullForRequiredColumns):
    __orm_table__ = "virtual_printers"
    name: str | None = None
    enabled: bool | None = None
    mode: str | None = None
    model: str | None = None
    access_code: str | None = None
    target_printer_id: int | None = None
    auto_dispatch: bool | None = None
    queue_force_color_match: bool | None = None
    save_ams_mapping: bool | None = None
    gcode_injection: bool | None = None
    bind_ip: str | None = None
    remote_interface_ip: str | None = None
    tailscale_disabled: bool | None = None


def _resolve_printer_model(printer_model: str | None) -> str | None:
    """Map a printer's model (display name or SSDP code) to a valid VP SSDP model code.

    Printers store display names like 'X1C' while VPs need SSDP codes like 'BL-P001'.
    """
    if not printer_model:
        return None
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS
    from backend.app.services.virtual_printer.manager import DISPLAY_NAME_TO_MODEL_CODE

    # Already a valid SSDP model code
    if printer_model in VIRTUAL_PRINTER_MODELS:
        return printer_model
    # Map display name to SSDP code
    return DISPLAY_NAME_TO_MODEL_CODE.get(printer_model)


def _target_missing(target_printer_id: int) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": f"Printer with ID {target_printer_id} not found"})


def _vp_missing() -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Virtual printer not found"})


def generate_vp_api_key() -> str:
    """API key a slicer sends as ``X-Api-Key`` to a Moonraker-compatible VP."""
    return secrets.token_hex(16)


def _is_moonraker(vp) -> bool:
    from backend.app.services.virtual_printer.manager import VP_PROTOCOL_MOONRAKER, vp_protocol

    return vp_protocol(vp) == VP_PROTOCOL_MOONRAKER


async def _validate_moonraker_target(db: AsyncSession, printer_id: int) -> JSONResponse | None:
    """Moonraker-compatible VPs hand raw G-code to non-Bambu printers only."""
    from backend.app.models.printer import Printer

    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    printer = result.scalar_one_or_none()
    if not printer:
        return JSONResponse(status_code=400, content={"detail": f"Printer with ID {printer_id} not found"})
    if (printer.provider or "bambu").strip().lower() == "bambu":
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Moonraker/OctoPrint-compatible virtual printers can only target non-Bambu printers. "
                "Use a Bambu-compatible virtual printer for Bambu Lab printers."
            },
        )
    return None


def _moonraker_enable_error(vp) -> str | None:
    """Return why a Moonraker-compatible VP can't be enabled, or None."""
    from backend.app.models.virtual_printer import VP_MODE_QUEUE, normalize_vp_mode
    from backend.app.services.virtual_printer import MOONRAKER_VP_MODES

    if normalize_vp_mode(vp.mode) not in MOONRAKER_VP_MODES:
        return "Proxy mode is not available for Moonraker/OctoPrint-compatible virtual printers"
    if not vp.api_key:
        return "API key is required when enabling"
    if normalize_vp_mode(vp.mode) == VP_MODE_QUEUE and not vp.target_printer_id:
        return "Target printer is required for print queue mode"
    return None


async def _vp_to_dict(vp, db: AsyncSession, status: dict | None = None) -> dict:
    """Convert VirtualPrinter model to response dict.

    In proxy mode the surfaced serial is the target printer's actual serial
    (what the bridge advertises over SSDP / what slicers see), not the
    self-generated suffix. Archive / queue / review keep the self-generated
    serial since those modes never speak the target's identity.
    """
    from backend.app.models.printer import Printer
    from backend.app.models.virtual_printer import VP_MODE_PROXY
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS
    from backend.app.services.virtual_printer.manager import DEFAULT_VIRTUAL_PRINTER_MODEL, _get_serial_for_model

    model_code = vp.model or DEFAULT_VIRTUAL_PRINTER_MODEL
    serial = _get_serial_for_model(model_code, vp.serial_suffix)
    if vp.mode == VP_MODE_PROXY and vp.target_printer_id:
        result = await db.execute(select(Printer.serial_number).where(Printer.id == vp.target_printer_id))
        target_serial = result.scalar_one_or_none()
        if target_serial:
            serial = target_serial

    return {
        "id": vp.id,
        "name": vp.name,
        "enabled": vp.enabled,
        "protocol": "moonraker" if _is_moonraker(vp) else "bambu",
        "mode": vp.mode,
        "model": model_code,
        "model_name": VIRTUAL_PRINTER_MODELS.get(model_code, model_code),
        "access_code_set": bool(vp.access_code),
        "serial": serial,
        "target_printer_id": vp.target_printer_id,
        "auto_dispatch": vp.auto_dispatch,
        "queue_force_color_match": vp.queue_force_color_match,
        "save_ams_mapping": vp.save_ams_mapping,
        "gcode_injection": vp.gcode_injection,
        "bind_ip": vp.bind_ip,
        "remote_interface_ip": vp.remote_interface_ip,
        "tailscale_disabled": vp.tailscale_disabled,
        "position": vp.position,
        "status": status or {"running": False, "pending_files": 0},
        # Moonraker/OctoPrint-compatible VPs (#52): the slicer's "Physical
        # printer" host is <printbuddy origin><host_path>, authenticated with
        # api_key as X-Api-Key. Only returned for those VPs.
        **(
            {"api_key": vp.api_key, "host_path": f"/api/v1/vp-host/{vp.id}"}
            if _is_moonraker(vp)
            else {"api_key": None, "host_path": None}
        ),
    }


@router.get("")
async def list_virtual_printers(
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    """List all virtual printers with status."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS, virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).order_by(VirtualPrinter.position, VirtualPrinter.id))
    vps = result.scalars().all()

    printers = []
    for vp in vps:
        # One bridging to a printer the caller can't use is left out: its
        # status names that printer.
        if not printer_scope.allows(vp.target_printer_id):
            continue
        instance = virtual_printer_manager.get_instance(vp.id)
        status = instance.get_status() if instance else {"running": False, "pending_files": 0}
        printers.append(await _vp_to_dict(vp, db, status))

    return {
        "printers": printers,
        "models": VIRTUAL_PRINTER_MODELS,
    }


@router.post("")
async def create_virtual_printer(
    body: VirtualPrinterCreate,
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    """Create a new virtual printer."""
    from backend.app.models.virtual_printer import VP_MODE_VALUES, VirtualPrinter, normalize_vp_mode
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS, virtual_printer_manager
    from backend.app.services.virtual_printer.manager import DEFAULT_VIRTUAL_PRINTER_MODEL

    # Accept both canonical and legacy wire values so older clients (forks /
    # mobile shortcuts / scripted setups) still work; normalize before write.
    body.mode = normalize_vp_mode(body.mode) or body.mode
    if body.mode not in VP_MODE_VALUES:
        return JSONResponse(status_code=400, content={"detail": "Invalid mode"})

    from backend.app.services.virtual_printer import VP_PROTOCOLS

    if body.protocol not in VP_PROTOCOLS:
        return JSONResponse(status_code=400, content={"detail": "Invalid protocol"})
    if body.protocol == "moonraker":
        return await _create_moonraker_virtual_printer(body, db)

    # Validate model
    if body.model and body.model not in VIRTUAL_PRINTER_MODELS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid model. Must be one of: {', '.join(VIRTUAL_PRINTER_MODELS.keys())}"},
        )

    # Validate access code length
    if body.access_code and len(body.access_code) != 8:
        return JSONResponse(status_code=400, content={"detail": "Access code must be exactly 8 characters"})

    # Validation when enabling. Non-proxy VPs with a target printer derive
    # their access code from the target (the bridge forwards the slicer's
    # auth bytes through to the real printer, so the codes MUST match),
    # so a separately-supplied access_code isn't required in that case.
    if body.enabled:
        if not body.bind_ip:
            return JSONResponse(status_code=400, content={"detail": "Bind IP is required when enabling"})
        if body.mode == "proxy":
            if not body.target_printer_id:
                return JSONResponse(status_code=400, content={"detail": "Target printer is required for proxy mode"})
        else:
            if not body.access_code and not body.target_printer_id:
                return JSONResponse(status_code=400, content={"detail": "Access code is required when enabling"})

    # Validate proxy target printer exists
    target_printer = None
    if body.target_printer_id is not None:
        from backend.app.models.printer import Printer

        result = await db.execute(select(Printer).where(Printer.id == body.target_printer_id))
        target_printer = result.scalar_one_or_none()
        if not target_printer or not printer_scope.allows(target_printer.id):
            return _target_missing(body.target_printer_id)

    # Validate bind_ip uniqueness (against all enabled VPs)
    if body.bind_ip:
        result = await db.execute(
            select(VirtualPrinter).where(
                VirtualPrinter.bind_ip == body.bind_ip,
                VirtualPrinter.enabled == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none():
            return JSONResponse(status_code=400, content={"detail": f"Bind IP {body.bind_ip} is already in use"})

    # Force-inherit the access code from the target printer for non-proxy VPs.
    # The non-proxy bridge (Immediate / Review / Queue with a target set) forwards
    # the slicer's MQTT / RTSPS auth bytes through to the real printer, so any
    # value the user supplied here would silently break the bridge if it didn't
    # match the printer's code. The UI now renders the field read-only when a
    # target is set; this is the belt-and-braces backstop for any non-UI client.
    effective_access_code = body.access_code
    if body.mode != "proxy" and target_printer is not None:
        effective_access_code = target_printer.access_code

    # Generate next serial suffix
    result = await db.execute(select(VirtualPrinter.serial_suffix).order_by(VirtualPrinter.id.desc()))
    last_suffix = result.scalar()
    if last_suffix:
        try:
            next_num = int(last_suffix) + 1
            new_suffix = str(next_num).zfill(9)
        except ValueError:
            new_suffix = "391800002"
    else:
        new_suffix = "391800001"

    # Get next position
    result = await db.execute(select(VirtualPrinter.position).order_by(VirtualPrinter.position.desc()))
    last_pos = result.scalar()
    next_pos = (last_pos or 0) + 1

    vp = VirtualPrinter(
        name=body.name,
        enabled=body.enabled,
        mode=body.mode,
        model=body.model
        or _resolve_printer_model(target_printer.model if target_printer and body.mode == "proxy" else None)
        or DEFAULT_VIRTUAL_PRINTER_MODEL,
        access_code=effective_access_code,
        target_printer_id=body.target_printer_id,
        auto_dispatch=body.auto_dispatch,
        queue_force_color_match=body.queue_force_color_match,
        save_ams_mapping=body.save_ams_mapping,
        gcode_injection=body.gcode_injection,
        bind_ip=body.bind_ip,
        remote_interface_ip=body.remote_interface_ip,
        serial_suffix=new_suffix,
        position=next_pos,
    )
    db.add(vp)
    await db.commit()
    await db.refresh(vp)

    logger.info("Created virtual printer: %s (id=%d)", vp.name, vp.id)

    # Sync services if enabled
    if body.enabled:
        try:
            await virtual_printer_manager.sync_from_db()
        except Exception as e:
            logger.error("Failed to start virtual printer after create: %s", e)

    return await _vp_to_dict(vp, db)


async def _create_moonraker_virtual_printer(body: VirtualPrinterCreate, db: AsyncSession):
    """Create an OctoPrint/Moonraker-compatible virtual printer (#52).

    Needs no bind IP, Bambu model or access code: uploads arrive over HTTP on
    the Printbuddy port and are authenticated by a generated API key.
    """
    from backend.app.models.virtual_printer import VirtualPrinter, normalize_vp_mode
    from backend.app.services.virtual_printer import MOONRAKER_VP_MODES, virtual_printer_manager

    body.mode = normalize_vp_mode(body.mode) or body.mode
    if body.mode not in MOONRAKER_VP_MODES:
        return JSONResponse(
            status_code=400,
            content={"detail": "Proxy mode is not available for Moonraker/OctoPrint-compatible virtual printers"},
        )
    if body.target_printer_id:
        error = await _validate_moonraker_target(db, body.target_printer_id)
        if error:
            return error

    result = await db.execute(select(VirtualPrinter.serial_suffix).order_by(VirtualPrinter.id.desc()))
    last_suffix = result.scalar()
    try:
        new_suffix = str(int(last_suffix) + 1).zfill(9) if last_suffix else "391800001"
    except ValueError:
        new_suffix = "391800002"

    result = await db.execute(select(VirtualPrinter.position).order_by(VirtualPrinter.position.desc()))
    next_pos = (result.scalar() or 0) + 1

    vp = VirtualPrinter(
        name=body.name,
        enabled=body.enabled,
        protocol="moonraker",
        mode=body.mode,
        model=None,
        api_key=generate_vp_api_key(),
        target_printer_id=body.target_printer_id,
        auto_dispatch=body.auto_dispatch,
        queue_force_color_match=body.queue_force_color_match,
        serial_suffix=new_suffix,
        position=next_pos,
    )
    if body.enabled:
        error = _moonraker_enable_error(vp)
        if error:
            return JSONResponse(status_code=400, content={"detail": error})

    db.add(vp)
    await db.commit()
    await db.refresh(vp)
    logger.info("Created Moonraker-compatible virtual printer: %s (id=%d)", vp.name, vp.id)

    if body.enabled:
        try:
            await virtual_printer_manager.sync_from_db()
        except Exception as e:
            logger.error("Failed to start virtual printer after create: %s", e)

    return await _vp_to_dict(vp, db)


@router.get("/tailscale-status", response_model=TailscaleStatusResponse)
async def get_tailscale_status(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
) -> TailscaleStatusResponse:
    """Return current Tailscale availability and machine identity.

    Used by the frontend to indicate whether virtual printer TLS is backed
    by a trusted Let's Encrypt certificate or a self-signed CA.
    """
    status = await tailscale_service.get_status()
    return TailscaleStatusResponse(
        available=status.available,
        fqdn=status.fqdn,
        hostname=status.hostname,
        tailnet_name=status.tailnet_name,
        tailscale_ips=status.tailscale_ips,
        error=status.error,
    )


@router.get("/ca-certificate")
async def get_ca_certificate(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    """Return the shared virtual-printer CA certificate (PEM) for slicer trust import.

    One CA is shared by every virtual printer — the user imports it into their
    slicer's trust store once. Only the public certificate is returned; the CA
    private key never leaves the backend.
    """
    from backend.app.services.virtual_printer import virtual_printer_manager

    try:
        return virtual_printer_manager.get_ca_certificate_info()
    except Exception as e:
        logger.error("Failed to obtain virtual printer CA certificate: %s", e)
        return JSONResponse(status_code=500, content={"detail": "Could not generate the CA certificate"})


@router.get("/{vp_id}/diagnostic", response_model=VPDiagnosticResult)
async def diagnose_virtual_printer(
    vp_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    """Run setup diagnostics for a virtual printer.

    Probes the VP's own bind IP and services so the user can self-diagnose the
    common "my virtual printer doesn't show up in the slicer" failures.
    """
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager
    from backend.app.services.virtual_printer.diagnostic import run_vp_diagnostic

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp or not printer_scope.allows(vp.target_printer_id):
        return _vp_missing()

    instance = virtual_printer_manager.get_instance(vp.id)
    return await run_vp_diagnostic(vp, instance, db)


@router.get("/{vp_id}")
async def get_virtual_printer(
    vp_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    """Get a single virtual printer with status."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp or not printer_scope.allows(vp.target_printer_id):
        return _vp_missing()

    instance = virtual_printer_manager.get_instance(vp.id)
    status = instance.get_status() if instance else {"running": False, "pending_files": 0}

    return await _vp_to_dict(vp, db, status)


@router.put("/{vp_id}")
async def update_virtual_printer(
    vp_id: int,
    body: VirtualPrinterUpdate,
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    """Update a virtual printer."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS, virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    # One bridging to a printer the caller can't use is not theirs to change.
    if not vp or not printer_scope.allows(vp.target_printer_id):
        return _vp_missing()

    # Redact the access code before logging — model_dump otherwise includes
    # the plaintext value at DEBUG, violating the project no-secrets-in-logs
    # rule. Replace with a marker that still signals "the user changed it"
    # vs "the user didn't touch this field".
    _safe_body = body.model_dump(exclude_unset=True)
    if "access_code" in _safe_body:
        _safe_body["access_code"] = "***"
    logger.debug(
        "Update VP %d: body=%s, current state: mode=%s, enabled=%s, access_code_set=%s, bind_ip=%s, target=%s",
        vp_id,
        _safe_body,
        vp.mode,
        vp.enabled,
        bool(vp.access_code),
        vp.bind_ip,
        vp.target_printer_id,
    )

    if _is_moonraker(vp):
        return await _update_moonraker_virtual_printer(vp, body, db)

    # Apply updates
    if body.name is not None:
        vp.name = body.name
    if body.mode is not None:
        from backend.app.models.virtual_printer import VP_MODE_VALUES, normalize_vp_mode

        canonical_mode = normalize_vp_mode(body.mode) or body.mode
        if canonical_mode not in VP_MODE_VALUES:
            return JSONResponse(status_code=400, content={"detail": "Invalid mode"})
        vp.mode = canonical_mode
    if body.model is not None:
        if body.model not in VIRTUAL_PRINTER_MODELS:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Invalid model. Must be one of: {', '.join(VIRTUAL_PRINTER_MODELS.keys())}"},
            )
        vp.model = body.model
    if body.access_code is not None:
        if body.access_code and len(body.access_code) != 8:
            return JSONResponse(status_code=400, content={"detail": "Access code must be exactly 8 characters"})
        vp.access_code = body.access_code
    if body.target_printer_id is not None:
        from backend.app.models.printer import Printer

        result = await db.execute(select(Printer).where(Printer.id == body.target_printer_id))
        target_printer = result.scalar_one_or_none()
        if not target_printer or not printer_scope.allows(target_printer.id):
            return _target_missing(body.target_printer_id)
        vp.target_printer_id = body.target_printer_id
        # Auto-inherit model from target printer in proxy mode (unless user explicitly set model)
        if body.model is None and vp.mode == "proxy" and target_printer.model:
            vp.model = _resolve_printer_model(target_printer.model) or target_printer.model
    if body.auto_dispatch is not None:
        vp.auto_dispatch = body.auto_dispatch
    if body.queue_force_color_match is not None:
        vp.queue_force_color_match = body.queue_force_color_match
    if body.save_ams_mapping is not None:
        vp.save_ams_mapping = body.save_ams_mapping
    if body.gcode_injection is not None:
        vp.gcode_injection = body.gcode_injection
    if body.bind_ip is not None:
        vp.bind_ip = body.bind_ip
    if body.remote_interface_ip is not None:
        vp.remote_interface_ip = body.remote_interface_ip
    if body.tailscale_disabled is not None:
        vp.tailscale_disabled = body.tailscale_disabled

    # Auto-inherit model when switching to proxy mode with existing target printer
    if body.mode == "proxy" and body.model is None and body.target_printer_id is None and vp.target_printer_id:
        from backend.app.models.printer import Printer as PrinterModel

        result = await db.execute(select(PrinterModel).where(PrinterModel.id == vp.target_printer_id))
        existing_target = result.scalar_one_or_none()
        if existing_target and existing_target.model:
            vp.model = _resolve_printer_model(existing_target.model) or existing_target.model

    # Force-inherit the access code from the target printer for non-proxy VPs.
    # See create_virtual_printer for the rationale: the bridge forwards slicer
    # auth bytes through, so the VP's code MUST equal the target's. This block
    # runs after every patch (whether or not access_code or target were in the
    # body), so changing the target also resyncs the code, and an explicit
    # access_code submitted alongside a target is silently overridden.
    if vp.mode != "proxy" and vp.target_printer_id is not None:
        from backend.app.models.printer import Printer as PrinterModelAC

        result = await db.execute(select(PrinterModelAC).where(PrinterModelAC.id == vp.target_printer_id))
        target_for_ac = result.scalar_one_or_none()
        if target_for_ac is not None and vp.access_code != target_for_ac.access_code:
            vp.access_code = target_for_ac.access_code

    # Determine final enabled state
    explicitly_enabling = body.enabled is True
    new_enabled = body.enabled if body.enabled is not None else vp.enabled
    effective_mode = vp.mode

    if explicitly_enabling:
        # User is explicitly toggling on — enforce all requirements
        if not vp.bind_ip:
            logger.warning("Update VP %d rejected: no bind_ip", vp_id)
            return JSONResponse(status_code=400, content={"detail": "Bind IP is required when enabling"})
        # Validate bind_ip uniqueness (against all enabled VPs)
        existing = await db.execute(
            select(VirtualPrinter).where(
                VirtualPrinter.bind_ip == vp.bind_ip,
                VirtualPrinter.id != vp_id,
                VirtualPrinter.enabled == True,  # noqa: E712
            )
        )
        conflict = existing.scalar_one_or_none()
        if conflict:
            logger.warning(
                "Update VP %d rejected: bind_ip %s already in use by VP %d (enabled=%s, mode=%s)",
                vp_id,
                vp.bind_ip,
                conflict.id,
                conflict.enabled,
                conflict.mode,
            )
            return JSONResponse(
                status_code=400,
                content={
                    "detail": f"Bind IP {vp.bind_ip} is already in use by '{conflict.name}'"
                    if printer_scope.allows(conflict.target_printer_id)
                    else f"Bind IP {vp.bind_ip} is already in use"
                },
            )
        if effective_mode == "proxy":
            if not vp.target_printer_id:
                logger.warning("Update VP %d rejected: no target_printer_id for proxy mode", vp_id)
                return JSONResponse(status_code=400, content={"detail": "Target printer is required for proxy mode"})
        else:
            if not vp.access_code:
                logger.warning(
                    "Update VP %d rejected: no access_code for non-proxy enable (mode=%s)", vp_id, effective_mode
                )
                return JSONResponse(status_code=400, content={"detail": "Access code is required when enabling"})
    elif new_enabled and body.enabled is None:
        # VP is already enabled and user is changing other fields —
        # auto-disable if new state doesn't meet requirements
        if not vp.bind_ip:
            new_enabled = False
        elif effective_mode == "proxy":
            if not vp.target_printer_id:
                new_enabled = False
        else:
            if not vp.access_code:
                new_enabled = False

    vp.enabled = new_enabled

    await db.commit()
    await db.refresh(vp)

    logger.info("Updated virtual printer: %s (id=%d)", vp.name, vp.id)

    # Sync services
    try:
        await virtual_printer_manager.sync_from_db()
    except Exception as e:
        logger.error("Failed to sync virtual printers after update: %s", e)

    instance = virtual_printer_manager.get_instance(vp.id)
    status = instance.get_status() if instance else {"running": False, "pending_files": 0}

    return await _vp_to_dict(vp, db, status)


async def drop_virtual_printer(db: AsyncSession, vp_id: int) -> Path:
    """Delete a virtual printer's row and discard its pending uploads.

    Its instance must be stopped first, if one runs. The caller commits, then
    calls remove_upload_dir with what this returns. *db* is a session or a
    connection.
    """
    from sqlalchemy import delete as sql_delete

    from backend.app.models.pending_upload import PendingUpload
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager

    upload_dir = virtual_printer_manager._base_dir / "uploads" / str(vp_id)
    # Mark any PendingUpload rows that referenced this VP's upload_dir as
    # discarded — without this the rows live on as phantom entries in
    # /pending-uploads/ pointing at file paths that no longer exist, and
    # the user only learns they're orphaned by trying to archive one and
    # getting a flip-to-discarded on file-missing.
    try:
        await db.execute(
            update(PendingUpload)
            # The folder, not every path that starts with its name (uploads/12 for 1).
            .where(PendingUpload.file_path.startswith(f"{upload_dir}{os.sep}", autoescape=True))
            .values(status="discarded")
        )
    except Exception as e:
        logger.error("Failed to discard orphan PendingUpload rows for VP %d: %s", vp_id, e)
    await db.execute(sql_delete(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    return upload_dir


def remove_upload_dir(upload_dir: Path) -> None:
    """Remove a deleted virtual printer's upload directory.

    After the DB commit succeeds, so a crash between commit and rmtree only
    leaves orphan files (vs orphan rows pointing at a now-missing tree).
    """
    if upload_dir.exists():
        import shutil

        shutil.rmtree(upload_dir, ignore_errors=True)


async def _update_moonraker_virtual_printer(vp, body: VirtualPrinterUpdate, db: AsyncSession):
    """Apply an update to a Moonraker/OctoPrint-compatible VP (#52).

    Bambu-only fields (model, access code, bind/remote IP, Tailscale) are
    ignored; they mean nothing to an HTTP upload endpoint.
    """
    from backend.app.models.virtual_printer import normalize_vp_mode
    from backend.app.services.virtual_printer import MOONRAKER_VP_MODES, virtual_printer_manager

    if body.name is not None:
        vp.name = body.name
    if body.mode is not None:
        body.mode = normalize_vp_mode(body.mode) or body.mode
        if body.mode not in MOONRAKER_VP_MODES:
            return JSONResponse(
                status_code=400,
                content={"detail": "Proxy mode is not available for Moonraker/OctoPrint-compatible virtual printers"},
            )
        vp.mode = body.mode
    if body.target_printer_id is not None:
        error = await _validate_moonraker_target(db, body.target_printer_id)
        if error:
            return error
        vp.target_printer_id = body.target_printer_id
    if body.auto_dispatch is not None:
        vp.auto_dispatch = body.auto_dispatch
    if body.queue_force_color_match is not None:
        vp.queue_force_color_match = body.queue_force_color_match
    if not vp.api_key:
        vp.api_key = generate_vp_api_key()

    new_enabled = body.enabled if body.enabled is not None else vp.enabled
    if new_enabled:
        error = _moonraker_enable_error(vp)
        if error:
            if body.enabled is True:
                return JSONResponse(status_code=400, content={"detail": error})
            # Already enabled and another field change broke a requirement.
            new_enabled = False
    vp.enabled = new_enabled

    await db.commit()
    await db.refresh(vp)
    logger.info("Updated Moonraker-compatible virtual printer: %s (id=%d)", vp.name, vp.id)

    try:
        await virtual_printer_manager.sync_from_db()
    except Exception as e:
        logger.error("Failed to sync virtual printers after update: %s", e)

    instance = virtual_printer_manager.get_instance(vp.id)
    status = instance.get_status() if instance else {"running": False, "pending_files": 0}
    return await _vp_to_dict(vp, db, status)


@router.post("/{vp_id}/api-key")
async def regenerate_virtual_printer_api_key(
    vp_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Issue a new API key for a Moonraker/OctoPrint-compatible VP (#52).

    The old key stops working immediately; the slicer's physical-printer
    entry must be updated with the new one.
    """
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp:
        return JSONResponse(status_code=404, content={"detail": "Virtual printer not found"})
    if not _is_moonraker(vp):
        return JSONResponse(
            status_code=400, content={"detail": "Only Moonraker/OctoPrint-compatible virtual printers use an API key"}
        )

    vp.api_key = generate_vp_api_key()
    await db.commit()
    await db.refresh(vp)
    logger.info("Regenerated API key for virtual printer %s (id=%d)", vp.name, vp.id)

    instance = virtual_printer_manager.get_instance(vp.id)
    status = instance.get_status() if instance else {"running": False, "pending_files": 0}
    return await _vp_to_dict(vp, db, status)


@router.delete("/{vp_id}")
async def delete_virtual_printer(
    vp_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    printer_scope: PrinterScope = RequestPrinterScope,
):
    """Delete a virtual printer."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp or not printer_scope.allows(vp.target_printer_id):
        return _vp_missing()

    vp_name = vp.name

    # Stop instance if running
    await virtual_printer_manager.remove_instance(vp_id)
    upload_dir = await drop_virtual_printer(db, vp_id)
    await db.commit()
    remove_upload_dir(upload_dir)

    logger.info("Deleted virtual printer: %s (id=%d)", vp_name, vp_id)

    # Resync remaining services
    try:
        await virtual_printer_manager.sync_from_db()
    except Exception as e:
        logger.error("Failed to sync virtual printers after delete: %s", e)

    return {"detail": "Deleted", "id": vp_id}
