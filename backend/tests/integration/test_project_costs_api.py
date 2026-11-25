"""Integration tests for the project production cost estimate."""

import pytest
from httpx import AsyncClient

from backend.tests.integration.test_project_plan_api import lib_file_factory, make_project  # noqa: F401


@pytest.fixture
async def cost_setup(db_session, printer_factory, archive_factory):
    from backend.app.models.filament import Filament
    from backend.app.models.settings import Settings
    from backend.app.models.spool import Spool

    db_session.add_all(
        [
            Settings(key="energy_cost_per_kwh", value="0.40"),
            Settings(key="currency", value="EUR"),
            # Two white PLA spools: 800 g left @ 20 €/kg, 200 g left @ 30 €/kg → 22 €/kg
            Spool(material="PLA", rgba="FFFFFFFF", label_weight=1000, weight_used=200, cost_per_kg=20.0),
            Spool(material="PLA", rgba="FFFFFFFF", label_weight=1000, weight_used=800, cost_per_kg=30.0),
            # Spool without price is ignored, archived spool too
            Spool(material="PLA", rgba="000000FF", label_weight=1000, weight_used=0, cost_per_kg=None),
            Filament(name="Generic PLA", type="PLA", cost_per_kg=21.0),
        ]
    )
    await db_session.commit()

    powered = await printer_factory(name="P1S-01", model="P1S", power_watts=200)
    x1c = await printer_factory(name="X1C-01", model="X1C")
    # X1C history: 0.5 kWh over 2 h → 0.25 kWh/h
    await archive_factory(x1c.id, status="completed", energy_kwh=0.5, print_time_seconds=7200)
    return {"powered": powered, "x1c": x1c}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cost_breakdown(async_client: AsyncClient, make_project, lib_file_factory, cost_setup, db_session):  # noqa: F811
    from backend.app.models.project_bom import ProjectBOMItem

    project = await make_project(waste_percent=20, budget=10.0)
    base = await lib_file_factory()  # PLA white 20 g + PLA black 10 g, 1 h
    accessory = await lib_file_factory(
        file_metadata={
            "print_time_seconds": 3600,
            "filament_used_grams": 50.0,
            "filament_slots": [{"slot_id": 1, "used_g": 50.0, "type": "PETG", "color": "#FF0000"}],
        }
    )
    url = f"/api/v1/projects/{project['id']}"
    await async_client.post(
        f"{url}/plan",
        json={"library_file_id": base.id, "quantity": 2, "printer_id": cost_setup["powered"].id},
    )
    await async_client.post(f"{url}/plan", json={"library_file_id": accessory.id, "target_model": "X1C"})
    db_session.add_all(
        [
            ProjectBOMItem(
                project_id=project["id"], name="Magnets", quantity_needed=10, quantity_acquired=4, unit_price=0.1
            ),
            ProjectBOMItem(project_id=project["id"], name="Glue", quantity_needed=1),
        ]
    )
    await db_session.commit()

    resp = await async_client.get(f"{url}/costs")
    assert resp.status_code == 200, resp.text
    costs = resp.json()

    rows = {(r["type"], r["color"]): r for r in costs["material"]["rows"]}
    white = rows[("PLA", "#FFFFFF")]
    assert white["source"] == "spools" and white["price_per_kg"] == 22.0
    assert len(white["spools"]) == 2
    assert white["planned_cost"] == 0.88  # 40 g
    black = rows[("PLA", "#000000")]
    assert black["source"] == "catalog" and black["price_per_kg"] == 21.0
    assert black["planned_cost"] == 0.42  # 20 g
    red = rows[("PETG", "#FF0000")]
    assert red["source"] == "default" and red["price_per_kg"] == 25.0
    assert red["planned_cost"] == 1.25  # 50 g
    assert costs["material"]["planned_cost"] == 2.55
    assert costs["material"]["waste_cost"] == 0.51
    assert costs["material"]["total_cost"] == 3.06

    energy = {r["key"]: r for r in costs["energy"]["rows"]}
    p1s = energy[f"p:{cost_setup['powered'].id}"]
    assert p1s["source"] == "power_setting" and p1s["kwh_per_hour"] == 0.2
    assert p1s["planned_hours"] == 2.0 and p1s["planned_kwh"] == 0.4
    x1c = energy["m:X1C"]
    assert x1c["source"] == "history" and x1c["kwh_per_hour"] == 0.25
    assert costs["energy"]["planned_kwh"] == 0.65
    assert costs["energy"]["planned_cost"] == 0.26

    assert costs["bom"]["total"] == 1.0
    assert costs["bom"]["acquired"] == 0.4
    assert [r["name"] for r in costs["bom"]["rows"]] == ["Magnets"]

    assert costs["planned"] == {"material": 3.06, "energy": 0.26, "bom": 1.0, "total": 4.32}
    assert costs["incurred"] == {"material": 0.0, "energy": 0.0, "bom": 0.4, "total": 0.4}
    assert costs["remaining"] == {"material": 3.06, "energy": 0.26, "bom": 0.6, "total": 3.92}
    assert costs["currency"] == "EUR"
    assert costs["budget"] == 10.0

    codes = {w["code"] for w in costs["warnings"]}
    assert codes == {"default_price", "bom_without_price"}

    listing = (await async_client.get("/api/v1/projects/")).json()
    entry = next(p for p in listing if p["id"] == project["id"])
    assert entry["estimated_costs"]["total"] == 4.32


@pytest.mark.asyncio
@pytest.mark.integration
async def test_costs_without_plan_use_actual_spend(
    async_client: AsyncClient,
    make_project,  # noqa: F811
    printer_factory,
    archive_factory,
):
    printer = await printer_factory()
    project = await make_project()
    await archive_factory(printer.id, project_id=project["id"], cost=1.5, energy_cost=0.2, energy_kwh=0.5)

    costs = (await async_client.get(f"/api/v1/projects/{project['id']}/costs")).json()
    assert costs["has_plan"] is False
    assert costs["incurred"]["total"] == 1.7
    assert costs["planned"]["total"] == 1.7
    assert costs["remaining"]["total"] == 0.0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_waste_percent_and_printer_power_roundtrip(async_client: AsyncClient, make_project, printer_factory):  # noqa: F811
    project = await make_project()
    resp = await async_client.patch(f"/api/v1/projects/{project['id']}", json={"waste_percent": 7.5})
    assert resp.status_code == 200
    assert resp.json()["waste_percent"] == 7.5
    assert (
        await async_client.patch(f"/api/v1/projects/{project['id']}", json={"waste_percent": -1})
    ).status_code == 422

    printer = await printer_factory(power_watts=150)
    data = (await async_client.get(f"/api/v1/printers/{printer.id}")).json()
    assert data["power_watts"] == 150
