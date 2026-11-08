import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from updater.app.jobs import get_job_store
from updater.app.main import app
from updater.app.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    settings = Settings(
        updater_token="secret-token",
        compose_file=tmp_path / "docker-compose.yml",
        compose_project="printbuddy",
        service_name="printbuddy",
        allowed_image="docker.io/vmhomelabde/printbuddy",
    )
    settings.compose_file.write_text("services:\n  printbuddy:\n    image: docker.io/vmhomelabde/printbuddy:dev\n")
    app.dependency_overrides[get_settings] = lambda: settings
    get_job_store().reset()
    yield settings
    app.dependency_overrides.clear()
    get_job_store().reset()


@pytest.mark.asyncio
async def test_health_requires_bearer_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_reports_compose_and_docker_socket(monkeypatch):
    monkeypatch.setattr("updater.app.main.docker_socket_available", lambda: True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "printbuddy-updater",
        "docker_available": True,
        "compose_file_available": True,
    }


@pytest.mark.asyncio
async def test_update_starts_allowlisted_compose_job(monkeypatch):
    recorded = []

    async def fake_run_command(argv, *, timeout_seconds):
        recorded.append(argv)
        return 0, "ok", ""

    monkeypatch.setattr("updater.app.jobs.run_command", fake_run_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/update", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    job = get_job_store().get(body["job_id"])
    assert job is not None
    await job.task
    assert get_job_store().get(body["job_id"]).status == "completed"
    assert recorded == [
        ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file), "pull", "printbuddy"],
        ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file), "up", "-d", "printbuddy"],
        ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file), "config", "--format", "json"],
    ]


@pytest.mark.asyncio
async def test_update_with_target_image_pulls_beta_and_retags_compose_service(monkeypatch):
    recorded = []

    async def fake_run_command(argv, *, timeout_seconds):
        recorded.append(argv)
        if argv[-2:] == ["--format", "json"]:
            return 0, '{"services":{"printbuddy":{"image":"docker.io/vmhomelabde/printbuddy:latest"}}}', ""
        return 0, "ok", ""

    monkeypatch.setattr("updater.app.jobs.run_command", fake_run_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/update",
            headers={"Authorization": "Bearer secret-token"},
            json={"target_image": "docker.io/vmhomelabde/printbuddy:v0.2.5.1b13"},
        )

    assert response.status_code == 200
    body = response.json()
    job = get_job_store().get(body["job_id"])
    assert job is not None
    await job.task
    assert get_job_store().get(body["job_id"]).status == "completed"
    assert recorded == [
        ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file), "config", "--format", "json"],
        ["docker", "pull", "docker.io/vmhomelabde/printbuddy:v0.2.5.1b13"],
        [
            "docker",
            "tag",
            "docker.io/vmhomelabde/printbuddy:v0.2.5.1b13",
            "docker.io/vmhomelabde/printbuddy:latest",
        ],
        [
            "docker",
            "compose",
            "-p",
            "printbuddy",
            "-f",
            str(job.compose_file),
            "up",
            "-d",
            "--force-recreate",
            "printbuddy",
        ],
        ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file), "config", "--format", "json"],
    ]


@pytest.mark.asyncio
async def test_update_rejects_concurrent_job(monkeypatch):
    blocker = asyncio.Event()

    async def slow_command(argv, *, timeout_seconds):
        await blocker.wait()
        return 0, "ok", ""

    monkeypatch.setattr("updater.app.jobs.run_command", slow_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/update", headers={"Authorization": "Bearer secret-token"})
        second = await client.post("/update", headers={"Authorization": "Bearer secret-token"})

    assert first.status_code == 200
    assert second.status_code == 409
    blocker.set()
    await get_job_store().get(first.json()["job_id"]).task


@pytest.mark.asyncio
async def test_failed_command_marks_job_failed(monkeypatch):
    async def failing_command(argv, *, timeout_seconds):
        return 1, "", "pull denied: secret-token should not leak"

    monkeypatch.setattr("updater.app.jobs.run_command", failing_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/update", headers={"Authorization": "Bearer secret-token"})

    job_id = response.json()["job_id"]
    await get_job_store().get(job_id).task

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get(f"/jobs/{job_id}", headers={"Authorization": "Bearer secret-token"})

    body = status.json()
    assert body["status"] == "failed"
    assert body["exit_code"] == 1
    assert "secret-token" not in body["safe_log_tail"]
    assert "[REDACTED]" in body["safe_log_tail"]


COMPOSE_WITH_SIDECARS = (
    '{"services":{'
    '"printbuddy":{"image":"docker.io/vmhomelabde/printbuddy:latest"},'
    '"orca-slicer-api":{"image":"docker.io/vmhomelabde/printbuddy-orca-slicer-api:latest"},'
    '"bambu-studio-api":{"image":"vmhomelabde/printbuddy-bambu-studio-api:dev"},'
    '"postgres":{"image":"postgres:16"},'
    '"lookalike":{"image":"docker.io/evil/printbuddy-orca-slicer-api:latest"}'
    "}}"
)


@pytest.mark.asyncio
async def test_update_also_pulls_and_recreates_slicer_sidecars(monkeypatch):
    recorded = []

    async def fake_run_command(argv, *, timeout_seconds):
        recorded.append(argv)
        if argv[-2:] == ["--format", "json"]:
            return 0, COMPOSE_WITH_SIDECARS, ""
        return 0, "ok", ""

    monkeypatch.setattr("updater.app.jobs.run_command", fake_run_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/update", headers={"Authorization": "Bearer secret-token"})

    job = get_job_store().get(response.json()["job_id"])
    await job.task
    base = ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file)]
    assert job.status == "completed"
    assert job.message == "Container recreated"
    # Printbuddy first, then only the allowlisted sidecar images.
    assert recorded == [
        [*base, "pull", "printbuddy"],
        [*base, "up", "-d", "printbuddy"],
        [*base, "config", "--format", "json"],
        [*base, "pull", "bambu-studio-api"],
        [*base, "up", "-d", "bambu-studio-api"],
        [*base, "pull", "orca-slicer-api"],
        [*base, "up", "-d", "orca-slicer-api"],
    ]
    assert [step.status for step in job.steps] == ["completed"] * 7


@pytest.mark.asyncio
async def test_sidecar_failure_does_not_fail_the_printbuddy_update(monkeypatch):
    async def fake_run_command(argv, *, timeout_seconds):
        if argv[-2:] == ["--format", "json"]:
            return 0, COMPOSE_WITH_SIDECARS, ""
        if argv[-2:] == ["pull", "bambu-studio-api"]:
            return 1, "", "manifest unknown"
        return 0, "ok", ""

    monkeypatch.setattr("updater.app.jobs.run_command", fake_run_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/update", headers={"Authorization": "Bearer secret-token"})

    job = get_job_store().get(response.json()["job_id"])
    await job.task
    assert job.status == "completed"
    assert job.message == "Container recreated; slicer sidecar update failed"
    assert job.steps[-1].name == "docker compose pull bambu-studio-api"
    assert job.steps[-1].status == "failed"


@pytest.mark.asyncio
async def test_sidecar_update_can_be_disabled(monkeypatch, isolated_settings):
    isolated_settings.update_slicer_sidecars = False
    recorded = []

    async def fake_run_command(argv, *, timeout_seconds):
        recorded.append(argv)
        return 0, COMPOSE_WITH_SIDECARS, ""

    monkeypatch.setattr("updater.app.jobs.run_command", fake_run_command)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/update", headers={"Authorization": "Bearer secret-token"})

    job = get_job_store().get(response.json()["job_id"])
    await job.task
    assert [argv[-1] for argv in recorded] == ["printbuddy", "printbuddy"]
