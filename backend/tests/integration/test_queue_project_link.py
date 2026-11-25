"""Linking print-queue items (e.g. virtual-printer uploads) to projects."""

import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import select


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Point base_dir/archive_dir at a temp dir so files can be copied for real."""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "archive_dir", tmp_path / "archive")
    (tmp_path / "archive").mkdir()
    return tmp_path


@pytest.fixture
def make_project(db_session):
    async def _create(name: str = "Job"):
        from backend.app.models.project import Project

        project = Project(name=name)
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)
        return project

    return _create


@pytest.fixture
def make_vp_queue_item(db_session, storage):
    """Archive-only queue item, the shape a VP in print_queue mode creates."""
    _counter = [0]

    async def _create(status: str = "pending", plate_id: int | None = None, archive=None, **kwargs):
        from backend.app.models.archive import PrintArchive
        from backend.app.models.print_queue import PrintQueueItem

        _counter[0] += 1
        n = _counter[0]
        if archive is None:
            rel = f"archive/vp_{n}.gcode.3mf"
            with zipfile.ZipFile(storage / rel, "w") as zf:
                zf.writestr("Metadata/plate_1.gcode", f"; vp upload {n}\n")
            archive = PrintArchive(
                filename=f"vp_{n}.gcode.3mf",
                print_name=f"VP Print {n}",
                file_path=rel,
                file_size=(storage / rel).stat().st_size,
                status="archived",
            )
            db_session.add(archive)
            await db_session.commit()
            await db_session.refresh(archive)
        item = PrintQueueItem(
            archive_id=archive.id,
            target_model="X1C",
            plate_id=plate_id,
            status=status,
            position=n,
            **kwargs,
        )
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)
        return item, archive

    return _create


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_queue_item_links_project_and_archive(
    async_client: AsyncClient, db_session, make_project, make_vp_queue_item
):
    from backend.app.models.archive import PrintArchive

    project = await make_project("Desk organiser")
    item, archive = await make_vp_queue_item()

    resp = await async_client.patch(f"/api/v1/queue/{item.id}", json={"project_id": project.id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] == project.id
    assert resp.json()["project_name"] == "Desk organiser"

    await db_session.refresh(archive)
    assert archive.project_id == project.id

    # Explicit null unlinks both again
    resp = await async_client.patch(f"/api/v1/queue/{item.id}", json={"project_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] is None
    archive = (await db_session.execute(select(PrintArchive).where(PrintArchive.id == archive.id))).scalar_one()
    await db_session.refresh(archive)
    assert archive.project_id is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_queue_item_unknown_project_404(async_client: AsyncClient, make_vp_queue_item):
    item, _ = await make_vp_queue_item()
    resp = await async_client.patch(f"/api/v1/queue/{item.id}", json={"project_id": 99999})
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_update_sets_project(async_client: AsyncClient, make_project, make_vp_queue_item):
    project = await make_project()
    a, _ = await make_vp_queue_item()
    b, _ = await make_vp_queue_item()

    resp = await async_client.patch("/api/v1/queue/bulk", json={"item_ids": [a.id, b.id], "project_id": project.id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_count"] == 2

    listing = (await async_client.get("/api/v1/queue/")).json()
    linked = {i["id"]: i["project_id"] for i in listing}
    assert linked[a.id] == project.id
    assert linked[b.id] == project.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_project_link_works_for_history_items(async_client: AsyncClient, make_project, make_vp_queue_item):
    project = await make_project()
    done, _ = await make_vp_queue_item(status="completed")

    resp = await async_client.post("/api/v1/queue/project-link", json={"item_ids": [done.id], "project_id": project.id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_count"] == 1

    archives = (await async_client.get(f"/api/v1/projects/{project.id}/archives")).json()
    assert len(archives) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_project_link_add_to_plan_copies_archive_into_file_manager(
    async_client: AsyncClient, db_session, make_project, make_vp_queue_item
):
    from backend.app.models.library import LibraryFile
    from backend.app.models.project_plan import ProjectPlanItem

    project = await make_project()
    first, archive = await make_vp_queue_item()
    second, _ = await make_vp_queue_item(archive=archive)  # same upload queued twice

    resp = await async_client.post(
        "/api/v1/queue/project-link",
        json={"item_ids": [first.id, second.id], "project_id": project.id, "add_to_plan": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["library_files_created"] == 1
    assert body["plan_items_created"] == 1
    assert body["plan_items_linked"] == 1

    files = (await db_session.execute(LibraryFile.active())).scalars().all()
    assert len(files) == 1
    assert files[0].source_type == "archive"
    assert files[0].project_id == project.id

    rows = (
        (await db_session.execute(select(ProjectPlanItem).where(ProjectPlanItem.project_id == project.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].library_file_id == files[0].id
    assert rows[0].quantity == 2

    plan = (await async_client.get(f"/api/v1/projects/{project.id}/plan")).json()
    assert plan[0]["progress"]["queued"] == 2
    assert plan[0]["progress"]["remaining"] == 0

    # Linking again is idempotent: no second file, no second row
    resp = await async_client.post(
        "/api/v1/queue/project-link",
        json={"item_ids": [first.id], "project_id": project.id, "add_to_plan": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["library_files_created"] == 0
    assert resp.json()["plan_items_created"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_project_link_add_to_plan_requires_project(async_client: AsyncClient, make_vp_queue_item):
    item, _ = await make_vp_queue_item()
    resp = await async_client.post(
        "/api/v1/queue/project-link", json={"item_ids": [item.id], "project_id": None, "add_to_plan": True}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
@pytest.mark.integration
async def test_moving_to_other_project_drops_plan_link(
    async_client: AsyncClient, db_session, make_project, make_vp_queue_item
):
    from backend.app.models.print_queue import PrintQueueItem

    job_a = await make_project("A")
    job_b = await make_project("B")
    item, _ = await make_vp_queue_item()

    await async_client.post(
        "/api/v1/queue/project-link", json={"item_ids": [item.id], "project_id": job_a.id, "add_to_plan": True}
    )
    resp = await async_client.post("/api/v1/queue/project-link", json={"item_ids": [item.id], "project_id": job_b.id})
    assert resp.status_code == 200, resp.text

    refreshed = (await db_session.execute(select(PrintQueueItem).where(PrintQueueItem.id == item.id))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.project_id == job_b.id
    assert refreshed.plan_item_id is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_virtual_printer_default_project_roundtrip(async_client: AsyncClient, make_project):
    project = await make_project()
    created = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Queue VP", "mode": "print_queue", "default_project_id": project.id},
    )
    assert created.status_code in (200, 201), created.text
    vp = created.json()
    assert vp["default_project_id"] == project.id

    # Field omitted: unchanged
    resp = await async_client.put(f"/api/v1/virtual-printers/{vp['id']}", json={"name": "Renamed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_project_id"] == project.id

    # Explicit null clears
    resp = await async_client.put(f"/api/v1/virtual-printers/{vp['id']}", json={"default_project_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_project_id"] is None

    bad = await async_client.put(f"/api/v1/virtual-printers/{vp['id']}", json={"default_project_id": 99999})
    assert bad.status_code == 400
