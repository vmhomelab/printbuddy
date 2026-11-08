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


def _image_name(image: str) -> str:
    """Image reference without tag or digest, registry-normalised."""
    name = _normalized_image_name(image).split("@", 1)[0]
    last_slash = name.rfind("/")
    colon = name.rfind(":")
    return name[:colon] if colon > last_slash else name


def _sidecar_services(config_stdout: str, settings: Settings) -> list[tuple[str, str]]:
    """``(service, image)`` of compose services running an allowlisted slicer-sidecar image."""
    allowed = {_image_name(image) for image in settings.allowed_sidecar_images.split(",") if image.strip()}
    services = json.loads(config_stdout).get("services", {})
    found = []
    for name, service in services.items():
        if name == settings.service_name or not isinstance(service, dict):
            continue
        image = service.get("image")
        if isinstance(image, str) and _image_name(image) in allowed:
            found.append((name, image))
    return sorted(found)


_RELEASE_TAG = re.compile(r"^v\d[\w.-]*$")


def release_tag(target_image: str | None) -> str | None:
    """Release tag of an explicit target image (``…/printbuddy:v0.2.5.4b5``).

    The slicer-sidecar images are published under the same release tag, so a
    targeted (e.g. beta) update installs the sidecars built for that release.
    """
    if not target_image:
        return None
    name = target_image.split("@", 1)[0]
    last_slash = name.rfind("/")
    colon = name.rfind(":")
    if colon <= last_slash:
        return None
    tag = name[colon + 1 :]
    return tag if _RELEASE_TAG.match(tag) else None


def _with_tag(image: str, tag: str) -> str:
    """``image`` with its tag (or digest) replaced by ``tag``."""
    name = image.split("@", 1)[0]
    last_slash = name.rfind("/")
    colon = name.rfind(":")
    if colon > last_slash:
        name = name[:colon]
    return f"{name}:{tag}"


async def _run_step(job: UpdateJob, settings: Settings, step: Step, argv: list[str]) -> tuple[int, str]:
    job.steps.append(step)
    job.message = step.name
    step.status = "running"
    code, stdout, stderr = await run_command(argv, timeout_seconds=settings.command_timeout_seconds)
    job.safe_log_tail = sanitize_log("\n".join(part for part in [stdout, stderr] if part), settings)
    step.status = "completed" if code == 0 else "failed"
    return code, stdout


async def _update_slicer_sidecars(job: UpdateJob, settings: Settings, compose_base: list[str]) -> bool:
    """Pull and recreate the slicer sidecars of the compose project.

    Runs after Printbuddy itself is updated. Failures are reported on the
    step but do not fail the job: Printbuddy is already running the new
    version, and it warns about an outdated sidecar on its own. Returns
    False when a sidecar step failed.
    """
    if not settings.update_slicer_sidecars:
        return True
    job.status = "checking"
    code, stdout = await _run_step(
        job, settings, Step("docker compose config (slicer sidecars)"), [*compose_base, "config", "--format", "json"]
    )
    if code != 0:
        return False
    try:
        services = _sidecar_services(stdout, settings)
    except (ValueError, AttributeError):
        job.steps[-1].status = "failed"
        return False
    tag = release_tag(job.target_image)
    for service, image in services:
        if tag:
            result = await _install_release_sidecar(job, settings, compose_base, service, image, tag)
            if result == "failed":
                return False
            if result == "installed":
                continue
        job.status = "pulling"
        code, _ = await _run_step(
            job, settings, Step(f"docker compose pull {service}"), [*compose_base, "pull", service]
        )
        if code != 0:
            return False
        job.status = "recreating"
        code, _ = await _run_step(
            job, settings, Step(f"docker compose up -d {service}"), [*compose_base, "up", "-d", service]
        )
        if code != 0:
            return False
    return True


async def _install_release_sidecar(
    job: UpdateJob, settings: Settings, compose_base: list[str], service: str, image: str, tag: str
) -> str:
    """Install the sidecar image published for release ``tag``.

    Mirrors the targeted Printbuddy update: pull ``<sidecar image>:<tag>`` and
    retag it as the image the compose service declares, so a compose file on
    ``:latest`` runs the sidecar that belongs to the selected (beta) release.
    Returns "installed", "failed", or "unavailable" when no such image exists
    (releases published before the sidecars got release tags); the caller
    then falls back to a plain pull.
    """
    target = _with_tag(image, tag)
    job.status = "pulling"
    code, _ = await _run_step(job, settings, Step(f"docker pull {target}"), ["docker", "pull", target])
    if code != 0:
        job.steps[-1].status = "skipped"
        return "unavailable"
    if target != image:
        job.status = "tagging"
        code, _ = await _run_step(job, settings, Step(f"docker tag {target} {image}"), ["docker", "tag", target, image])
        if code != 0:
            return "failed"
    job.status = "recreating"
    code, _ = await _run_step(
        job,
        settings,
        Step(f"docker compose up -d --force-recreate {service}"),
        [*compose_base, "up", "-d", "--force-recreate", service],
    )
    return "installed" if code == 0 else "failed"


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
        sidecars_ok = await _update_slicer_sidecars(job, settings, compose_base)
        job.status = "completed"
        job.exit_code = 0
        job.message = "Container recreated" if sidecars_ok else "Container recreated; slicer sidecar update failed"
    except Exception as exc:  # defensive: keep API status useful if subprocess setup blows up
        job.status = "failed"
        job.exit_code = 1
        job.message = "Update job failed"
        job.safe_log_tail = sanitize_log(str(exc), settings)
    finally:
        job.finished_at = datetime.now(UTC).isoformat()
