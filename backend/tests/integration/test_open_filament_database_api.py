import pytest
from httpx import AsyncClient

from backend.app.services.open_filament_database import OpenFilamentDatabaseNotFound


@pytest.mark.asyncio
async def test_search_filaments_filters_brand_material(monkeypatch, async_client: AsyncClient):
    from backend.app.services.open_filament_database import OpenFilamentDatabaseClient

    async def fake_search(self, brand_slug: str, material: str, query: str | None = None):
        assert brand_slug == "elegoo"
        assert material == "PLA"
        assert query == "matte"
        return {
            "source": "openfilamentdatabase",
            "brand_slug": brand_slug,
            "material": material,
            "query": query,
            "count": 1,
            "filaments": [
                {
                    "id": "86ab73c0-6edc-52a2-ae22-787deb9eceb0",
                    "name": "PLA MATTE",
                    "slug": "pla_matte",
                    "variant_count": 17,
                    "path": "filaments/pla_matte/index.json",
                }
            ],
        }

    monkeypatch.setattr(OpenFilamentDatabaseClient, "search_filaments", fake_search)

    response = await async_client.get("/api/v1/open-filament-database/search?brand=elegoo&material=PLA&q=matte")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "openfilamentdatabase"
    assert payload["count"] == 1
    assert payload["filaments"][0]["slug"] == "pla_matte"


@pytest.mark.asyncio
async def test_variant_endpoint_returns_spool_prefill(monkeypatch, async_client: AsyncClient):
    from backend.app.services.open_filament_database import OpenFilamentDatabaseClient

    async def fake_variant(self, brand_slug: str, material: str, filament_slug: str, variant_slug: str):
        assert (brand_slug, material, filament_slug, variant_slug) == ("elegoo", "PLA", "pla", "black")
        return {
            "source": "openfilamentdatabase",
            "brand": {"id": "brand-id", "slug": "elegoo", "name": "ELEGOO"},
            "material": "PLA",
            "filament": {
                "id": "filament-id",
                "name": "PLA",
                "slug": "pla",
                "min_print_temperature": 190,
                "max_print_temperature": 230,
                "preferred_slicer_setting": {"id": "OGFE04", "generic_id": "GFL99", "profile_name": "Elegoo PLA"},
            },
            "variant": {"id": "variant-id", "name": "Black", "slug": "black", "color_hex": "#000000"},
            "sizes": [{"id": "size-id", "filament_weight": 1000, "diameter": 1.75}],
            "selected_size": {"id": "size-id", "filament_weight": 1000, "diameter": 1.75},
            "spool_prefill": {
                "brand": "ELEGOO",
                "material": "PLA",
                "subtype": "PLA",
                "color_name": "Black",
                "rgba": "000000FF",
                "label_weight": 1000,
                "nozzle_temp_min": 190,
                "nozzle_temp_max": 230,
                "slicer_filament": "OGFE04",
                "slicer_filament_name": "Elegoo PLA",
                "data_origin": "openfilamentdatabase",
            },
        }

    monkeypatch.setattr(OpenFilamentDatabaseClient, "get_variant", fake_variant)

    response = await async_client.get(
        "/api/v1/open-filament-database/brands/elegoo/materials/PLA/filaments/pla/variants/black"
    )

    assert response.status_code == 200
    prefill = response.json()["spool_prefill"]
    assert prefill == {
        "brand": "ELEGOO",
        "material": "PLA",
        "subtype": "PLA",
        "color_name": "Black",
        "rgba": "000000FF",
        "label_weight": 1000,
        "nozzle_temp_min": 190,
        "nozzle_temp_max": 230,
        "slicer_filament": "OGFE04",
        "slicer_filament_name": "Elegoo PLA",
        "data_origin": "openfilamentdatabase",
    }


@pytest.mark.asyncio
async def test_not_found_maps_to_structured_404(monkeypatch, async_client: AsyncClient):
    from backend.app.services.open_filament_database import OpenFilamentDatabaseClient

    async def fake_material(self, brand_slug: str, material: str):
        raise OpenFilamentDatabaseNotFound("Open Filament Database entry was not found", upstream_status=404)

    monkeypatch.setattr(OpenFilamentDatabaseClient, "get_material", fake_material)

    response = await async_client.get("/api/v1/open-filament-database/brands/nope/materials/PLA/filaments")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "ofdb_not_found",
        "message": "Open Filament Database entry was not found",
        "upstream_status": 404,
    }
