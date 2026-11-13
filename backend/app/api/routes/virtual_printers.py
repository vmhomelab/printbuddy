import logging
import secrets

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.user import User
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
    mode: str = "immediate"
    model: str | None = None
    access_code: str | None = None
    target_printer_id: int | None = None
    auto_dispatch: bool = True
    queue_force_color_match: bool = False
    bind_ip: str | None = None
    remote_interface_ip: str | None = None


class VirtualPrinterUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    mode: str | None = None
    model: str | None = None
    access_code: str | None = None
    target_printer_id: int | None = None
    auto_dispatch: bool | None = None
    queue_force_color_match: bool | None = None
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
    from backend.app.services.virtual_printer import MOONRAKER_VP_MODES

    if vp.mode not in MOONRAKER_VP_MODES:
        return "Proxy mode is not available for Moonraker/OctoPrint-compatible virtual printers"
    if not vp.api_key:
        return "API key is required when enabling"
    if vp.mode == "print_queue" and not vp.target_printer_id:
        return "Target printer is required for print queue mode"
    return None


def _vp_to_dict(vp, status: dict | None = None) -> dict:
    """Convert VirtualPrinter model to response dict."""
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS
    from backend.app.services.virtual_printer.manager import DEFAULT_VIRTUAL_PRINTER_MODEL, _get_serial_for_model

    model_code = vp.model or DEFAULT_VIRTUAL_PRINTER_MODEL
    serial = _get_serial_for_model(model_code, vp.serial_suffix)

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
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    """List all virtual printers with status."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS, virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).order_by(VirtualPrinter.position, VirtualPrinter.id))
    vps = result.scalars().all()

    printers = []
    for vp in vps:
        instance = virtual_printer_manager.get_instance(vp.id)
        status = instance.get_status() if instance else {"running": False, "pending_files": 0}
        printers.append(_vp_to_dict(vp, status))

    return {
        "printers": printers,
        "models": VIRTUAL_PRINTER_MODELS,
    }


@router.post("")
async def create_virtual_printer(
    body: VirtualPrinterCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Create a new virtual printer."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS, virtual_printer_manager
    from backend.app.services.virtual_printer.manager import DEFAULT_VIRTUAL_PRINTER_MODEL

    # Validate mode
    if body.mode not in ("immediate", "review", "print_queue", "proxy"):
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

    # Validation when enabling
    if body.enabled:
        if not body.bind_ip:
            return JSONResponse(status_code=400, content={"detail": "Bind IP is required when enabling"})
        if body.mode == "proxy":
            if not body.target_printer_id:
                return JSONResponse(status_code=400, content={"detail": "Target printer is required for proxy mode"})
        else:
            if not body.access_code:
                return JSONResponse(status_code=400, content={"detail": "Access code is required when enabling"})

    # Validate proxy target printer exists
    target_printer = None
    if body.target_printer_id:
        from backend.app.models.printer import Printer

        result = await db.execute(select(Printer).where(Printer.id == body.target_printer_id))
        target_printer = result.scalar_one_or_none()
        if not target_printer:
            return JSONResponse(
                status_code=400, content={"detail": f"Printer with ID {body.target_printer_id} not found"}
            )

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
        access_code=body.access_code,
        target_printer_id=body.target_printer_id,
        auto_dispatch=body.auto_dispatch,
        queue_force_color_match=body.queue_force_color_match,
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

    return _vp_to_dict(vp)


async def _create_moonraker_virtual_printer(body: VirtualPrinterCreate, db: AsyncSession):
    """Create an OctoPrint/Moonraker-compatible virtual printer (#52).

    Needs no bind IP, Bambu model or access code: uploads arrive over HTTP on
    the Printbuddy port and are authenticated by a generated API key.
    """
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import MOONRAKER_VP_MODES, virtual_printer_manager

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

    return _vp_to_dict(vp)


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
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
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
    if not vp:
        return JSONResponse(status_code=404, content={"detail": "Virtual printer not found"})

    instance = virtual_printer_manager.get_instance(vp.id)
    return await run_vp_diagnostic(vp, instance, db)


@router.get("/{vp_id}")
async def get_virtual_printer(
    vp_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    """Get a single virtual printer with status."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp:
        return JSONResponse(status_code=404, content={"detail": "Virtual printer not found"})

    instance = virtual_printer_manager.get_instance(vp.id)
    status = instance.get_status() if instance else {"running": False, "pending_files": 0}

    return _vp_to_dict(vp, status)


@router.put("/{vp_id}")
async def update_virtual_printer(
    vp_id: int,
    body: VirtualPrinterUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Update a virtual printer."""
    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import VIRTUAL_PRINTER_MODELS, virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp:
        return JSONResponse(status_code=404, content={"detail": "Virtual printer not found"})

    logger.debug(
        "Update VP %d: body=%s, current state: mode=%s, enabled=%s, access_code_set=%s, bind_ip=%s, target=%s",
        vp_id,
        body.model_dump(exclude_unset=True),
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
        if body.mode not in ("immediate", "review", "print_queue", "proxy"):
            return JSONResponse(status_code=400, content={"detail": "Invalid mode"})
        vp.mode = body.mode
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
        if not target_printer:
            return JSONResponse(
                status_code=400, content={"detail": f"Printer with ID {body.target_printer_id} not found"}
            )
        vp.target_printer_id = body.target_printer_id
        # Auto-inherit model from target printer in proxy mode (unless user explicitly set model)
        if body.model is None and vp.mode == "proxy" and target_printer.model:
            vp.model = _resolve_printer_model(target_printer.model) or target_printer.model
    if body.auto_dispatch is not None:
        vp.auto_dispatch = body.auto_dispatch
    if body.queue_force_color_match is not None:
        vp.queue_force_color_match = body.queue_force_color_match
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
                content={"detail": f"Bind IP {vp.bind_ip} is already in use by '{conflict.name}'"},
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

    return _vp_to_dict(vp, status)


async def _update_moonraker_virtual_printer(vp, body: VirtualPrinterUpdate, db: AsyncSession):
    """Apply an update to a Moonraker/OctoPrint-compatible VP (#52).

    Bambu-only fields (model, access code, bind/remote IP, Tailscale) are
    ignored; they mean nothing to an HTTP upload endpoint.
    """
    from backend.app.services.virtual_printer import MOONRAKER_VP_MODES, virtual_printer_manager

    if body.name is not None:
        vp.name = body.name
    if body.mode is not None:
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
    return _vp_to_dict(vp, status)


@router.post("/{vp_id}/api-key")
async def regenerate_virtual_printer_api_key(
    vp_id: int,
    db: AsyncSession = Depends(get_db),
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
    return _vp_to_dict(vp, status)


@router.delete("/{vp_id}")
async def delete_virtual_printer(
    vp_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Delete a virtual printer."""
    from sqlalchemy import delete as sql_delete

    from backend.app.models.virtual_printer import VirtualPrinter
    from backend.app.services.virtual_printer import virtual_printer_manager

    result = await db.execute(select(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    vp = result.scalar_one_or_none()
    if not vp:
        return JSONResponse(status_code=404, content={"detail": "Virtual printer not found"})

    vp_name = vp.name

    # Stop instance if running
    await virtual_printer_manager.remove_instance(vp_id)

    # Delete from DB
    await db.execute(sql_delete(VirtualPrinter).where(VirtualPrinter.id == vp_id))
    await db.commit()

    logger.info("Deleted virtual printer: %s (id=%d)", vp_name, vp_id)

    # Resync remaining services
    try:
        await virtual_printer_manager.sync_from_db()
    except Exception as e:
        logger.error("Failed to sync virtual printers after delete: %s", e)

    return {"detail": "Deleted", "id": vp_id}
