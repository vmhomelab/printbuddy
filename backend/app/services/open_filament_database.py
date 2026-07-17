"""Open Filament Database API client and normalization helpers.

The upstream API is a static JSON hierarchy:
brands -> brand detail/materials -> material filaments -> filament variants -> variant sizes.
This service keeps the rest of PrintBuddy insulated from that hierarchy and from
network/JSON error details.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from backend.app.core.config import APP_VERSION

logger = logging.getLogger(__name__)

OFDB_BASE_URL = "https://api.openfilamentdatabase.org/api/v1"
OFDB_SOURCE = "openfilamentdatabase"


class OpenFilamentDatabaseError(RuntimeError):
    """Base class for upstream OFDB failures."""

    status_code = 502
    code = "ofdb_error"

    def __init__(self, message: str, *, upstream_status: int | None = None):
        super().__init__(message)
        self.message = message
        self.upstream_status = upstream_status


class OpenFilamentDatabaseNotFound(OpenFilamentDatabaseError):
    status_code = 404
    code = "ofdb_not_found"


class OpenFilamentDatabaseUnavailable(OpenFilamentDatabaseError):
    status_code = 503
    code = "ofdb_unavailable"


class OpenFilamentDatabaseBadResponse(OpenFilamentDatabaseError):
    status_code = 502
    code = "ofdb_bad_response"


def _clean_segment(value: str) -> str:
    cleaned = value.strip().strip("/")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("path segment must not be empty")
    return quote(cleaned, safe="._-")


def _rgba_from_hex(color_hex: str | None) -> str | None:
    if not color_hex:
        return None
    raw = color_hex.strip().lstrip("#")
    if len(raw) != 6:
        return None
    try:
        int(raw, 16)
    except ValueError:
        return None
    return raw.upper() + "FF"


def _pick_slicer_settings(slicer_settings: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(slicer_settings, dict):
        return {}
    for key in ("orcaslicer", "bambustudio", "bambu_studio", "prusaslicer", "elegooslicer"):
        value = slicer_settings.get(key)
        if isinstance(value, dict):
            return value
    for value in slicer_settings.values():
        if isinstance(value, dict):
            return value
    return {}


def _derive_subtype(material: str | None, filament_name: str | None) -> str | None:
    name = (filament_name or "").strip()
    mat = (material or "").strip()
    if not name:
        return None
    if mat and name.upper() == mat.upper():
        return name
    if mat and name.upper().startswith(mat.upper()):
        tail = name[len(mat) :].strip(" -_/()")
        return tail or name
    if mat and name.upper().endswith(mat.upper()):
        head = name[: -len(mat)].strip(" -_/()")
        return head or name
    return name


def _first_preferred_size(sizes: list[dict[str, Any]]) -> dict[str, Any] | None:
    active = [s for s in sizes if isinstance(s, dict) and not s.get("discontinued")]
    candidates = active or [s for s in sizes if isinstance(s, dict)]
    if not candidates:
        return None
    for weight in (1000, 750, 500):
        for size in candidates:
            if size.get("filament_weight") == weight:
                return size
    return candidates[0]


class OpenFilamentDatabaseClient:
    def __init__(self, *, base_url: str = OFDB_BASE_URL, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "User-Agent": f"PrintBuddy/{APP_VERSION} (+https://github.com/vmhomelab/PrintBuddy)",
        }

    async def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers, follow_redirects=True) as client:
                response = await client.get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            logger.warning("OFDB request failed for %s: %s", path, exc)
            raise OpenFilamentDatabaseUnavailable("Open Filament Database is currently unavailable") from exc

        if response.status_code == 404:
            raise OpenFilamentDatabaseNotFound("Open Filament Database entry was not found", upstream_status=404)
        if response.status_code >= 400:
            raise OpenFilamentDatabaseUnavailable(
                f"Open Filament Database returned HTTP {response.status_code}",
                upstream_status=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenFilamentDatabaseBadResponse("Open Filament Database returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise OpenFilamentDatabaseBadResponse("Open Filament Database returned an unexpected response shape")
        return payload

    async def get_brands(self) -> dict[str, Any]:
        payload = await self._get_json("brands/index.json")
        brands = payload.get("brands") if isinstance(payload.get("brands"), list) else []
        return {
            "source": OFDB_SOURCE,
            "version": payload.get("version"),
            "generated_at": payload.get("generated_at"),
            "count": payload.get("count", len(brands)),
            "brands": brands,
        }

    async def get_brand(self, brand_slug: str) -> dict[str, Any]:
        brand = _clean_segment(brand_slug)
        payload = await self._get_json(f"brands/{brand}/index.json")
        materials = payload.get("materials") if isinstance(payload.get("materials"), list) else []
        return {
            "source": OFDB_SOURCE,
            "id": payload.get("id"),
            "name": payload.get("name"),
            "slug": payload.get("slug", brand_slug),
            "origin": payload.get("origin"),
            "website": payload.get("website"),
            "materials": materials,
        }

    async def get_material(self, brand_slug: str, material: str) -> dict[str, Any]:
        brand = _clean_segment(brand_slug)
        material_segment = _clean_segment(material.upper())
        payload = await self._get_json(f"brands/{brand}/materials/{material_segment}/index.json")
        filaments = payload.get("filaments") if isinstance(payload.get("filaments"), list) else []
        return {
            "source": OFDB_SOURCE,
            "brand_slug": brand_slug,
            "material": payload.get("material", material.upper()),
            "id": payload.get("id"),
            "brand_id": payload.get("brand_id"),
            "slug": payload.get("slug", material.upper()),
            "material_class": payload.get("material_class"),
            "filaments": filaments,
        }

    async def search_filaments(self, brand_slug: str, material: str, query: str | None = None) -> dict[str, Any]:
        material_payload = await self.get_material(brand_slug, material)
        filaments = material_payload["filaments"]
        q = (query or "").strip().lower()
        if q:
            filaments = [
                filament
                for filament in filaments
                if q in str(filament.get("name", "")).lower()
                or q in str(filament.get("slug", "")).lower()
                or q in str(filament.get("id", "")).lower()
            ]
        return {
            "source": OFDB_SOURCE,
            "brand_slug": brand_slug,
            "material": material_payload["material"],
            "query": query or "",
            "count": len(filaments),
            "filaments": filaments,
        }

    async def get_filament(self, brand_slug: str, material: str, filament_slug: str) -> dict[str, Any]:
        brand = _clean_segment(brand_slug)
        material_segment = _clean_segment(material.upper())
        filament = _clean_segment(filament_slug)
        payload = await self._get_json(f"brands/{brand}/materials/{material_segment}/filaments/{filament}/index.json")
        variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
        slicer = _pick_slicer_settings(payload.get("slicer_settings"))
        material_name = payload.get("material", material.upper())
        filament_name = payload.get("name")
        return {
            "source": OFDB_SOURCE,
            "brand_slug": brand_slug,
            "material": material_name,
            "id": payload.get("id"),
            "name": filament_name,
            "slug": payload.get("slug", filament_slug),
            "density": payload.get("density"),
            "diameter_tolerance": payload.get("diameter_tolerance"),
            "min_print_temperature": payload.get("min_print_temperature"),
            "max_print_temperature": payload.get("max_print_temperature"),
            "min_bed_temperature": payload.get("min_bed_temperature"),
            "max_bed_temperature": payload.get("max_bed_temperature"),
            "discontinued": payload.get("discontinued", False),
            "slicer_settings": payload.get("slicer_settings")
            if isinstance(payload.get("slicer_settings"), dict)
            else {},
            "preferred_slicer_setting": slicer,
            "variants": variants,
            "spool_prefill": {
                "material": material_name,
                "subtype": _derive_subtype(material_name, filament_name),
                "nozzle_temp_min": payload.get("min_print_temperature"),
                "nozzle_temp_max": payload.get("max_print_temperature"),
                "slicer_filament": slicer.get("id") or slicer.get("generic_id"),
                "slicer_filament_name": slicer.get("profile_name"),
                "data_origin": OFDB_SOURCE,
            },
        }

    async def get_variant(
        self,
        brand_slug: str,
        material: str,
        filament_slug: str,
        variant_slug: str,
    ) -> dict[str, Any]:
        filament_payload = await self.get_filament(brand_slug, material, filament_slug)
        brand_payload = await self.get_brand(brand_slug)
        brand_name = brand_payload.get("name") or brand_slug
        brand = _clean_segment(brand_slug)
        material_segment = _clean_segment(material.upper())
        filament = _clean_segment(filament_slug)
        variant = _clean_segment(variant_slug)
        payload = await self._get_json(
            f"brands/{brand}/materials/{material_segment}/filaments/{filament}/variants/{variant}.json"
        )
        sizes = payload.get("sizes") if isinstance(payload.get("sizes"), list) else []
        selected_size = _first_preferred_size(sizes)
        color_hex = payload.get("color_hex")
        spool_prefill = dict(filament_payload.get("spool_prefill", {}))
        spool_prefill.update(
            {
                "brand": brand_name,
                "color_name": payload.get("name"),
                "rgba": _rgba_from_hex(color_hex),
                "label_weight": selected_size.get("filament_weight") if selected_size else 1000,
                "data_origin": OFDB_SOURCE,
            }
        )
        return {
            "source": OFDB_SOURCE,
            "brand": {
                "id": brand_payload.get("id"),
                "slug": brand_payload.get("slug", brand_slug),
                "name": brand_name,
            },
            "material": filament_payload.get("material", material.upper()),
            "filament": {
                key: filament_payload.get(key)
                for key in (
                    "id",
                    "name",
                    "slug",
                    "density",
                    "diameter_tolerance",
                    "min_print_temperature",
                    "max_print_temperature",
                    "min_bed_temperature",
                    "max_bed_temperature",
                    "discontinued",
                    "preferred_slicer_setting",
                )
            },
            "variant": {
                "id": payload.get("id"),
                "name": payload.get("name"),
                "slug": payload.get("slug", variant_slug),
                "color_hex": color_hex,
                "traits": payload.get("traits") if isinstance(payload.get("traits"), dict) else {},
                "discontinued": payload.get("discontinued", False),
            },
            "sizes": sizes,
            "selected_size": selected_size,
            "spool_prefill": spool_prefill,
        }
