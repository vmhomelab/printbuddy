import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_list_update_and_delete_printer_fleet_group(async_client: AsyncClient, printer_factory):
    printer_a = await printer_factory(name="PRA-01", serial_number="PRA01")
    printer_b = await printer_factory(name="PRB-04", serial_number="PRB04")

    create_response = await async_client.post(
        "/api/v1/printer-fleet-groups/",
        json={"name": "Prototype Lab", "printer_ids": [printer_a.id]},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["name"] == "Prototype Lab"
    assert created["printer_ids"] == [printer_a.id]

    list_response = await async_client.get("/api/v1/printer-fleet-groups/")
    assert list_response.status_code == 200
    groups = list_response.json()
    assert groups == [created]

    update_response = await async_client.put(
        f"/api/v1/printer-fleet-groups/{created['id']}",
        json={"name": "Production Row A", "printer_ids": [printer_a.id, printer_b.id]},
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["name"] == "Production Row A"
    assert updated["printer_ids"] == [printer_a.id, printer_b.id]

    delete_response = await async_client.delete(f"/api/v1/printer-fleet-groups/{created['id']}")
    assert delete_response.status_code == 204

    final_response = await async_client.get("/api/v1/printer-fleet-groups/")
    assert final_response.status_code == 200
    assert final_response.json() == []
