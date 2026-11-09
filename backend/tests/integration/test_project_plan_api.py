"""Integration tests for the project plan ("Job") endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select


@pytest.fixture
def lib_file_factory(db_session):
    _counter = [0]

    async def _create(**kwargs):
        from backend.app.models.library import LibraryFile

        _counter[0] += 1
        n = _counter[0]
        defaults = {
            "filename": f"plate_{n}.gcode.3mf",
            "file_path": f"/test/library/plate_{n}.gcode.3mf",
            "file_size": 2048,
            "file_type": "3mf",
            "file_metadata": {
                "print_time_seconds": 3600,
                "filament_used_grams": 30.0,
                "filament_slots": [
                    {"slot_id": 1, "used_g": 20.0, "type": "PLA", "color": "#FFFFFFFF"},
                    {"slot_id": 2, "used_g": 10.0, "type": "PLA", "color": "#000000FF"},
                ],
            },
        }
        defaults.update(kwargs)
        lib_file = LibraryFile(**defaults)
        db_session.add(lib_file)
        await db_session.commit()
        await db_session.refresh(lib_file)
        return lib_file

    return _create


@pytest.fixture
def make_project(db_session):
    async def _create(**kwargs) -> dict:
        from backend.app.models.project import Project

        project = Project(name=kwargs.pop("name", "Job"), **kwargs)
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)
        return {"id": project.id}

    return _create


@pytest.mark.asyncio
@pytest.mark.integration
async def test_order_number_roundtrip(async_client: AsyncClient, make_project):
    created = await async_client.post("/api/v1/projects/", json={"name": "Job", "order_number": " ETSY-1234 "})
    assert created.status_code == 200, created.text
    assert created.json()["order_number"] == "ETSY-1234"

    project = await make_project(order_number="ETSY-1")
    resp = await async_client.patch(f"/api/v1/projects/{project['id']}", json={"order_number": " ETSY-9 "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["order_number"] == "ETSY-9"

    listing = (await async_client.get("/api/v1/projects/")).json()
    assert next(p for p in listing if p["id"] == project["id"])["order_number"] == "ETSY-1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_plan_item_reads_slice_metadata(async_client: AsyncClient, make_project, lib_file_factory):
    project = await make_project()
    lib_file = await lib_file_factory()

    resp = await async_client.post(
        f"/api/v1/projects/{project['id']}/plan",
        json={"library_file_id": lib_file.id, "quantity": 3, "group_label": "Base set"},
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()
    assert item["name"] == lib_file.filename.replace(".gcode.3mf", "")
    assert item["quantity"] == 3
    assert item["group_label"] == "Base set"
    assert item["est_print_time_seconds"] == 3600
    assert item["est_filament_grams"] == 30.0
    assert item["is_sliced"] is True
    assert [f["color"] for f in item["filaments"]] == ["#FFFFFF", "#000000"]
    assert item["filaments"][0]["original_type"] == "PLA"
    assert item["progress"]["remaining"] == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_summary_groups_by_material_and_color(async_client: AsyncClient, make_project, lib_file_factory):
    project = await make_project()
    lib_a = await lib_file_factory()
    lib_b = await lib_file_factory()

    item_a = (
        await async_client.post(
            f"/api/v1/projects/{project['id']}/plan", json={"library_file_id": lib_a.id, "quantity": 2}
        )
    ).json()
    await async_client.post(f"/api/v1/projects/{project['id']}/plan", json={"library_file_id": lib_b.id})

    # Print plate A's first slot in red PETG instead of white PLA
    filaments = item_a["filaments"]
    filaments[0].update({"type": "PETG", "color": "#ff0000", "color_name": "Red"})
    resp = await async_client.patch(
        f"/api/v1/projects/{project['id']}/plan/{item_a['id']}", json={"filaments": filaments}
    )
    assert resp.status_code == 200

    summary = (await async_client.get(f"/api/v1/projects/{project['id']}/plan/summary")).json()
    assert summary["total_plates"] == 3
    assert summary["planned_print_time_seconds"] == 3 * 3600
    assert summary["planned_filament_grams"] == 90.0
    by_key = {(m["type"], m["color"]): m for m in summary["materials"]}
    assert by_key[("PETG", "#FF0000")]["planned_grams"] == 40.0
    assert by_key[("PETG", "#FF0000")]["color_name"] == "Red"
    assert by_key[("PLA", "#FFFFFF")]["planned_grams"] == 20.0
    assert by_key[("PLA", "#000000")]["planned_grams"] == 30.0

    stats = (await async_client.get(f"/api/v1/projects/{project['id']}")).json()["stats"]
    assert stats["planned_source"] == "plan"
    assert stats["planned_print_time_hours"] == 3.0
    assert stats["plan_total_plates"] == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stats_fall_back_to_linked_files(async_client: AsyncClient, make_project, lib_file_factory, db_session):
    from backend.app.models.library import LibraryFolder

    project = await make_project()
    folder = LibraryFolder(name="Job files", project_id=project["id"])
    db_session.add(folder)
    await db_session.commit()
    await lib_file_factory(folder_id=folder.id)
    await lib_file_factory(folder_id=folder.id)

    stats = (await async_client.get(f"/api/v1/projects/{project['id']}")).json()["stats"]
    assert stats["planned_source"] == "files"
    assert stats["planned_print_time_hours"] == 2.0
    assert stats["planned_filament_grams"] == 60.0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_enqueue_creates_queue_items_and_tops_up(
    async_client: AsyncClient, make_project, lib_file_factory, printer_factory, db_session
):
    from backend.app.models.print_queue import PrintQueueItem

    printer = await printer_factory()
    project = await make_project()
    lib_file = await lib_file_factory()
    item = (
        await async_client.post(
            f"/api/v1/projects/{project['id']}/plan",
            json={"library_file_id": lib_file.id, "quantity": 2, "printer_id": printer.id},
        )
    ).json()
    filaments = item["filaments"]
    filaments[1].update({"type": "PETG", "color": "#00FF00"})
    await async_client.patch(f"/api/v1/projects/{project['id']}/plan/{item['id']}", json={"filaments": filaments})

    resp = await async_client.post(f"/api/v1/projects/{project['id']}/plan/enqueue", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["queued_total"] == 2

    rows = (
        (await db_session.execute(select(PrintQueueItem).where(PrintQueueItem.plan_item_id == item["id"])))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.printer_id == printer.id and r.project_id == project["id"] for r in rows)
    assert '"slot_id": 2' in rows[0].filament_overrides
    assert '"slot_id": 1' not in rows[0].filament_overrides  # unchanged slot is not overridden

    plan = (await async_client.get(f"/api/v1/projects/{project['id']}/plan")).json()
    assert plan[0]["progress"] == {
        "completed": 0,
        "printing": 0,
        "queued": 2,
        "failed": 0,
        "remaining": 0,
        "percent": 0.0,
    }

    # Nothing left to queue → no new items
    again = (await async_client.post(f"/api/v1/projects/{project['id']}/plan/enqueue", json={})).json()
    assert again["queued_total"] == 0

    # Raise the quantity → only the extra copy is queued
    await async_client.patch(f"/api/v1/projects/{project['id']}/plan/{item['id']}", json={"quantity": 3})
    topped = (await async_client.post(f"/api/v1/projects/{project['id']}/plan/enqueue", json={})).json()
    assert topped["queued_total"] == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_enqueue_rejects_unsliced_files(async_client: AsyncClient, make_project, lib_file_factory):
    project = await make_project()
    lib_file = await lib_file_factory(filename="model.stl", file_type="stl", file_metadata=None)
    item = (
        await async_client.post(f"/api/v1/projects/{project['id']}/plan", json={"library_file_id": lib_file.id})
    ).json()
    assert item["is_sliced"] is False
    assert item["est_print_time_seconds"] is None

    resp = (await async_client.post(f"/api/v1/projects/{project['id']}/plan/enqueue", json={})).json()
    assert resp["queued_total"] == 0
    assert resp["results"] == [{"plan_item_id": item["id"], "queued": 0, "error": "not_sliced"}]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_progress_counts_archives_once(
    async_client: AsyncClient, make_project, lib_file_factory, printer_factory, archive_factory, db_session
):
    from backend.app.models.print_queue import PrintQueueItem

    printer = await printer_factory()
    project = await make_project()
    lib_file = await lib_file_factory()
    item = (
        await async_client.post(
            f"/api/v1/projects/{project['id']}/plan", json={"library_file_id": lib_file.id, "quantity": 4}
        )
    ).json()

    done = await archive_factory(printer.id, status="completed", project_id=project["id"], plan_item_id=item["id"])
    failed = await archive_factory(printer.id, status="failed", project_id=project["id"], plan_item_id=item["id"])
    # Queue rows of the same prints must not be counted twice
    for archive, status in ((done, "completed"), (failed, "failed")):
        db_session.add(
            PrintQueueItem(
                printer_id=printer.id,
                library_file_id=lib_file.id,
                archive_id=archive.id,
                project_id=project["id"],
                plan_item_id=item["id"],
                status=status,
            )
        )
    db_session.add(
        PrintQueueItem(
            printer_id=printer.id,
            library_file_id=lib_file.id,
            project_id=project["id"],
            plan_item_id=item["id"],
            status="printing",
        )
    )
    await db_session.commit()

    plan = (await async_client.get(f"/api/v1/projects/{project['id']}/plan")).json()
    assert plan[0]["progress"] == {
        "completed": 1,
        "printing": 1,
        "queued": 0,
        "failed": 1,
        "remaining": 2,  # 4 - 1 completed - 1 printing (failed copies must be re-queued)
        "percent": 25.0,
    }
    summary = (await async_client.get(f"/api/v1/projects/{project['id']}/plan/summary")).json()
    assert summary["completed_plates"] == 1
    assert summary["remaining_print_time_seconds"] == 3 * 3600


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_plan_item_detaches_queue_items(
    async_client: AsyncClient, make_project, lib_file_factory, printer_factory, db_session
):
    from backend.app.models.print_queue import PrintQueueItem

    printer = await printer_factory()
    project = await make_project()
    lib_file = await lib_file_factory()
    item = (
        await async_client.post(
            f"/api/v1/projects/{project['id']}/plan",
            json={"library_file_id": lib_file.id, "printer_id": printer.id},
        )
    ).json()
    await async_client.post(f"/api/v1/projects/{project['id']}/plan/enqueue", json={})

    resp = await async_client.delete(f"/api/v1/projects/{project['id']}/plan/{item['id']}")
    assert resp.status_code == 200
    rows = (
        (await db_session.execute(select(PrintQueueItem).where(PrintQueueItem.project_id == project["id"])))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    await db_session.refresh(rows[0])
    assert rows[0].plan_item_id is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_plan_validation(async_client: AsyncClient, make_project, lib_file_factory, printer_factory):
    project = await make_project()
    printer = await printer_factory()
    lib_file = await lib_file_factory()
    base = f"/api/v1/projects/{project['id']}/plan"

    assert (await async_client.post(base, json={})).status_code == 400
    assert (await async_client.post(base, json={"library_file_id": 99999})).status_code == 400
    assert (
        await async_client.post(base, json={"library_file_id": lib_file.id, "printer_id": 99999})
    ).status_code == 400
    assert (
        await async_client.post(
            base, json={"library_file_id": lib_file.id, "printer_id": printer.id, "target_model": "X1C"}
        )
    ).status_code == 400
    assert (await async_client.post(base, json={"library_file_id": lib_file.id, "quantity": 0})).status_code == 422
    assert (await async_client.get("/api/v1/projects/99999/plan")).status_code == 404

    item = (await async_client.post(base, json={"library_file_id": lib_file.id, "printer_id": printer.id})).json()
    # Switching to a printer model clears the specific printer
    updated = (await async_client.patch(f"{base}/{item['id']}", json={"target_model": "P1S"})).json()
    assert updated["printer_id"] is None
    assert updated["target_model"] == "P1S"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_template_copies_plan(async_client: AsyncClient, make_project, lib_file_factory, test_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.app.core.database import get_db
    from backend.app.main import app

    # The template routes rely on get_db's commit-on-success (production
    # behaviour); the default test override never commits.
    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def committing_get_db():
        async with maker() as session:
            yield session
            await session.commit()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = committing_get_db
    try:
        await _check_template_copies_plan(async_client, make_project, lib_file_factory)
    finally:
        app.dependency_overrides[get_db] = previous


async def _check_template_copies_plan(async_client, make_project, lib_file_factory):
    project = await make_project()
    lib_file = await lib_file_factory()
    await async_client.post(
        f"/api/v1/projects/{project['id']}/plan",
        json={"library_file_id": lib_file.id, "quantity": 6, "group_label": "Base set"},
    )

    template = (await async_client.post(f"/api/v1/projects/{project['id']}/create-template")).json()
    template_plan = (await async_client.get(f"/api/v1/projects/{template['id']}/plan")).json()
    assert [(i["quantity"], i["group_label"]) for i in template_plan] == [(6, "Base set")]

    job = (await async_client.post(f"/api/v1/projects/from-template/{template['id']}?name=Order 42")).json()
    job_plan = (await async_client.get(f"/api/v1/projects/{job['id']}/plan")).json()
    assert len(job_plan) == 1
    assert job_plan[0]["progress"]["remaining"] == 6


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_project_links_folders(async_client: AsyncClient, lib_file_factory, db_session, test_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models.library import LibraryFolder

    folder = LibraryFolder(name="Desk organizer")
    db_session.add(folder)
    await db_session.commit()
    await lib_file_factory(folder_id=folder.id)

    # Unknown folder → 400 and nothing is created
    resp = await async_client.post("/api/v1/projects/", json={"name": "Bad", "folder_ids": [folder.id, 99999]})
    assert resp.status_code == 400

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def committing_get_db():
        async with maker() as session:
            yield session
            await session.commit()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = committing_get_db
    try:
        resp = await async_client.post("/api/v1/projects/", json={"name": "Job", "folder_ids": [folder.id]})
        assert resp.status_code == 200, resp.text
        project = resp.json()
        # Linked folder's slice estimate shows up right away
        assert project["stats"]["planned_source"] == "files"
        assert project["stats"]["planned_print_time_hours"] == 1.0

        linked = (await async_client.get(f"/api/v1/library/folders/by-project/{project['id']}")).json()
        assert [f["id"] for f in linked] == [folder.id]
    finally:
        app.dependency_overrides[get_db] = previous
