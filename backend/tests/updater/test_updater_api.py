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
        ["docker", "compose", "-p", "printbuddy", "-f", str(job.compose_file), "up", "-d", "--force-recreate", "printbuddy"],
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
