from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.models.user import User
from backend.app.services.open_filament_database import (
    OpenFilamentDatabaseBadResponse,
    OpenFilamentDatabaseClient,
    OpenFilamentDatabaseError,
    OpenFilamentDatabaseNotFound,
    OpenFilamentDatabaseUnavailable,
)

router = APIRouter(prefix="/open-filament-database", tags=["open-filament-database"])


def _ofdb_error(exc: OpenFilamentDatabaseError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "upstream_status": exc.upstream_status,
        },
    )


async def _call_ofdb(method: str, *args: Any, **kwargs: Any) -> Any:
    client = OpenFilamentDatabaseClient()
    try:
        return await getattr(client, method)(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "ofdb_invalid_path", "message": str(exc)},
        ) from exc
    except (OpenFilamentDatabaseNotFound, OpenFilamentDatabaseUnavailable, OpenFilamentDatabaseBadResponse) as exc:
        raise _ofdb_error(exc) from exc
    except OpenFilamentDatabaseError as exc:
        raise _ofdb_error(exc) from exc


@router.get("/brands")
async def list_brands(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.INVENTORY_READ),
):
    """List brands known to Open Filament Database."""
    return await _call_ofdb("get_brands")


@router.get("/brands/{brand_slug}")
async def get_brand(
    brand_slug: str,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.INVENTORY_READ),
):
    """Get one OFDB brand and its material list."""
    return await _call_ofdb("get_brand", brand_slug)


@router.get("/brands/{brand_slug}/materials/{material}/filaments")
async def list_material_filaments(
    brand_slug: str,
    material: str,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.INVENTORY_READ),
):
    """List filament families for a brand/material pair."""
    return await _call_ofdb("get_material", brand_slug, material)


@router.get("/search")
async def search_filaments(
    brand: str = Query(..., min_length=1, description="OFDB brand slug, e.g. elegoo"),
    material: str = Query(..., min_length=1, description="Material identifier, e.g. PLA"),
    q: str = Query("", description="Optional filament family search text"),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.INVENTORY_READ),
):
    """Search filament families under a specific brand/material pair.

    OFDB is hierarchical rather than a global text-search API, so the first UI
    search step filters within a selected brand + material.
    """
    return await _call_ofdb("search_filaments", brand, material, q)


@router.get("/brands/{brand_slug}/materials/{material}/filaments/{filament_slug}")
async def get_filament(
    brand_slug: str,
    material: str,
    filament_slug: str,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.INVENTORY_READ),
):
    """Get one OFDB filament family with variants and spool-prefill fields."""
    return await _call_ofdb("get_filament", brand_slug, material, filament_slug)


@router.get("/brands/{brand_slug}/materials/{material}/filaments/{filament_slug}/variants/{variant_slug}")
async def get_variant(
    brand_slug: str,
    material: str,
    filament_slug: str,
    variant_slug: str,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.INVENTORY_READ),
):
    """Get one OFDB variant and normalized PrintBuddy spool-prefill fields."""
    return await _call_ofdb("get_variant", brand_slug, material, filament_slug, variant_slug)
