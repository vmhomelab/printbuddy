from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from updater.app.commands import run_command
from updater.app.settings import Settings

TERMINAL_STATES = {"completed", "failed"}


@dataclass
class Step:
    name: str
    status: str = "pending"


@dataclass
class UpdateJob:
    job_id: str
    compose_file: Path
    status: str = "queued"
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    exit_code: int | None = None
    message: str = "Update queued"
    safe_log_tail: str = ""
    target_image: str | None = None
    steps: list[Step] = field(default_factory=list)
    task: asyncio.Task | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "message": self.message,
            "safe_log_tail": self.safe_log_tail,
            "steps": [step.__dict__.copy() for step in self.steps],
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, UpdateJob] = {}

    def reset(self) -> None:
        self._jobs.clear()

    def active(self) -> UpdateJob | None:
        return next((job for job in self._jobs.values() if job.status not in TERMINAL_STATES), None)

    def get(self, job_id: str) -> UpdateJob | None:
        return self._jobs.get(job_id)

    def create(self, settings: Settings, *, target_image: str | None = None) -> UpdateJob:
        if self.active() is not None:
            raise RuntimeError("An update job is already running")
        target_image = normalize_target_image(target_image, settings)
        steps = [
            Step(f"docker compose pull {settings.service_name}"),
            Step(f"docker compose up -d {settings.service_name}"),
        ]
        if target_image:
            steps = [
                Step("docker compose config"),
                Step(f"docker pull {target_image}"),
                Step("docker tag target image as compose service image"),
                Step(f"docker compose up -d {settings.service_name}"),
            ]
        job = UpdateJob(
            job_id=f"upd_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}",
            compose_file=settings.compose_file,
            target_image=target_image,
            steps=steps,
        )
        self._jobs[job.job_id] = job
        return job


_store = JobStore()


def get_job_store() -> JobStore:
    return _store


def sanitize_log(text: str, settings: Settings) -> str:
    cleaned = text
    if settings.updater_token:
        cleaned = cleaned.replace(settings.updater_token, "[REDACTED]")
    cleaned = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", cleaned)
    return cleaned[-4000:]


def _normalized_image_name(image: str) -> str:
    image = image.strip()
    if image.startswith("docker.io/library/"):
        return image.removeprefix("docker.io/library/")
    if image.startswith("docker.io/"):
        return image.removeprefix("docker.io/")
    return image


def normalize_target_image(target_image: str | None, settings: Settings) -> str | None:
    if not target_image:
        return None
    target_image = target_image.strip()
    allowed = _normalized_image_name(settings.allowed_image).split(":", 1)[0]
    candidate = _normalized_image_name(target_image).split(":", 1)[0]
    if candidate != allowed:
        raise RuntimeError("Target image is not allowlisted")
    return target_image


def _compose_service_image(config_stdout: str, settings: Settings) -> str:
    data = json.loads(config_stdout)
    image = data.get("services", {}).get(settings.service_name, {}).get("image")
    if not image:
        raise RuntimeError("Configured compose service image could not be determined")
    allowed = _normalized_image_name(settings.allowed_image).split(":", 1)[0]
    service_image_name = _normalized_image_name(image).split(":", 1)[0]
    if service_image_name != allowed:
        raise RuntimeError("Configured compose service image is not allowlisted")
    return image


async def run_update_job(job: UpdateJob, settings: Settings) -> None:
    compose_base = ["docker", "compose", "-p", settings.compose_project, "-f", str(settings.compose_file)]
    commands = [
        [*compose_base, "pull", settings.service_name],
        [*compose_base, "up", "-d", settings.service_name],
    ]
    phases = ["pulling", "recreating"]
    if job.target_image:
        commands = [
            [*compose_base, "config", "--format", "json"],
            ["docker", "pull", job.target_image],
            ["docker", "tag", job.target_image, ""],
            [*compose_base, "up", "-d", "--force-recreate", settings.service_name],
        ]
        phases = ["checking", "pulling", "tagging", "recreating"]
    try:
        for idx, argv in enumerate(commands):
            job.status = phases[idx]
            job.message = job.steps[idx].name
            job.steps[idx].status = "running"
            code, stdout, stderr = await run_command(argv, timeout_seconds=settings.command_timeout_seconds)
            if job.target_image and idx == 0 and code == 0:
                commands[2][-1] = _compose_service_image(stdout, settings)
            job.safe_log_tail = sanitize_log("\n".join(part for part in [stdout, stderr] if part), settings)
            job.exit_code = code
            if code != 0:
                job.status = "failed"
                job.steps[idx].status = "failed"
                job.message = f"{job.steps[idx].name} failed"
                return
            job.steps[idx].status = "completed"
        job.status = "completed"
        job.exit_code = 0
        job.message = "Container recreated"
    except Exception as exc:  # defensive: keep API status useful if subprocess setup blows up
        job.status = "failed"
        job.exit_code = 1
        job.message = "Update job failed"
        job.safe_log_tail = sanitize_log(str(exc), settings)
    finally:
        job.finished_at = datetime.now(UTC).isoformat()
