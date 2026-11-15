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


def _sidecar_services(services: dict, settings: Settings) -> list[tuple[str, str]]:
    """``(service, image)`` of compose services running an allowlisted slicer-sidecar image."""
    allowed = {_image_name(image) for image in settings.allowed_sidecar_images.split(",") if image.strip()}
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


@dataclass
class ComposeContext:
    """How to run ``docker compose`` against the host's project.

    The compose CLI runs inside this container, where the compose file is
    mounted at e.g. ``/host/docker-compose.yml``. Without the host's project
    directory, relative bind mounts such as ``./slicer-data/orca`` would
    resolve to ``/host/slicer-data/orca`` on the host, and ``${VAR}`` values
    from the host's ``.env`` would be blank. ``project_dir`` and
    ``config_files`` are the host paths, read from the compose labels of the
    running Printbuddy container.
    """

    base: list[str]
    project_dir: str | None = None
    config_files: list[str] = field(default_factory=list)


async def _compose_labels(settings: Settings) -> dict[str, str] | None:
    """Compose labels of the running Printbuddy container, if any."""
    code, stdout, _ = await run_command(
        [
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={settings.compose_project}",
            "--filter",
            f"label=com.docker.compose.service={settings.service_name}",
        ],
        timeout_seconds=settings.command_timeout_seconds,
    )
    container = stdout.split()[0] if code == 0 and stdout.split() else None
    if not container:
        return None
    code, stdout, _ = await run_command(
        ["docker", "inspect", "--format", "{{json .Config.Labels}}", container],
        timeout_seconds=settings.command_timeout_seconds,
    )
    if code != 0:
        return None
    try:
        labels = json.loads(stdout)
    except ValueError:
        return None
    return labels if isinstance(labels, dict) else None


def _host_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and "\n" not in value and "\0" not in value else None


async def compose_context(settings: Settings) -> ComposeContext:
    base = ["docker", "compose", "-p", settings.compose_project, "-f", str(settings.compose_file)]
    project_dir = _host_path(settings.compose_project_dir)
    config_files: list[str] = []
    labels = await _compose_labels(settings)
    if labels:
        project_dir = project_dir or _host_path(labels.get("com.docker.compose.project.working_dir"))
        raw_files = labels.get("com.docker.compose.project.config_files")
        if isinstance(raw_files, str):
            config_files = [path for path in (_host_path(part) for part in raw_files.split(",")) if path]
    if project_dir:
        base += ["--project-directory", project_dir]
    if settings.compose_env_file and Path(settings.compose_env_file).is_file():
        base += ["--env-file", str(settings.compose_env_file)]
    return ComposeContext(base=base, project_dir=project_dir, config_files=config_files)


async def _compose_services(job: UpdateJob, settings: Settings, ctx: ComposeContext) -> dict | None:
    """``services`` of the resolved compose config, or None if it failed."""
    job.status = "checking"
    code, stdout = await _run_step(
        job, settings, Step("docker compose config (sidecars)"), [*ctx.base, "config", "--format", "json"]
    )
    if code != 0:
        return None
    try:
        services = json.loads(stdout).get("services", {})
    except (ValueError, AttributeError):
        job.steps[-1].status = "failed"
        return None
    return services if isinstance(services, dict) else None


async def _update_slicer_sidecars(job: UpdateJob, settings: Settings, ctx: ComposeContext, services: dict) -> bool:
    """Pull and recreate the slicer sidecars of the compose project.

    Runs after Printbuddy itself is updated. Failures are reported on the
    step but do not fail the job: Printbuddy is already running the new
    version, and it warns about an outdated sidecar on its own. Returns
    False when a sidecar step failed.
    """
    tag = release_tag(job.target_image)
    for service, image in _sidecar_services(services, settings):
        if tag:
            result = await _install_release_image(job, settings, ctx, service, image, tag)
            if result == "failed":
                return False
            if result == "installed":
                continue
        job.status = "pulling"
        code, _ = await _run_step(job, settings, Step(f"docker compose pull {service}"), [*ctx.base, "pull", service])
        if code != 0:
            return False
        job.status = "recreating"
        code, _ = await _run_step(
            job, settings, Step(f"docker compose up -d {service}"), [*ctx.base, "up", "-d", service]
        )
        if code != 0:
            return False
    return True


async def _install_release_image(
    job: UpdateJob,
    settings: Settings,
    ctx: ComposeContext,
    service: str,
    image: str,
    tag: str,
    *,
    recreate: bool = True,
) -> str:
    """Install the image published for release ``tag`` as ``service``'s image.

    Mirrors the targeted Printbuddy update: pull ``<image>:<tag>`` and retag
    it as the image the compose service declares, so a compose file on
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
    if not recreate:
        return "installed"
    job.status = "recreating"
    code, _ = await _run_step(
        job,
        settings,
        Step(f"docker compose up -d --force-recreate {service}"),
        [*ctx.base, "up", "-d", "--force-recreate", service],
    )
    return "installed" if code == 0 else "failed"


async def _inspect(settings: Settings, argv: list[str]) -> str | None:
    code, stdout, _ = await run_command(argv, timeout_seconds=settings.command_timeout_seconds)
    value = stdout.strip()
    return value if code == 0 and value else None


async def _update_self(job: UpdateJob, settings: Settings, ctx: ComposeContext, services: dict) -> str:
    """Pull this updater's own image and, if it changed, restart onto it.

    The updater cannot recreate its own container from inside the job: it
    would be killed mid-command. Instead it starts a short-lived helper
    container from the new image that waits a few seconds (so this job can
    report "completed") and then runs ``docker compose up -d`` for the updater
    service from the host's project directory. Returns "current", "restarting",
    "skipped" or "failed".
    """
    service = settings.updater_service_name
    config = services.get(service)
    image = config.get("image") if isinstance(config, dict) else None
    if not isinstance(image, str) or _image_name(image) != _image_name(settings.allowed_updater_image):
        return "skipped"
    if not ctx.project_dir or not ctx.config_files:
        # Without the host paths the helper could not recreate the updater
        # with its real mounts; leave it to a manual update.
        return "skipped"

    tag = release_tag(job.target_image)
    result = await _install_release_image(job, settings, ctx, service, image, tag, recreate=False) if tag else None
    if result == "failed":
        return "failed"
    if result != "installed":
        job.status = "pulling"
        code, _ = await _run_step(job, settings, Step(f"docker compose pull {service}"), [*ctx.base, "pull", service])
        if code != 0:
            return "failed"

    container = await _inspect(settings, [*ctx.base, "ps", "-q", service])
    running = (
        await _inspect(settings, ["docker", "inspect", "--format", "{{.Image}}", container]) if container else None
    )
    latest = await _inspect(settings, ["docker", "image", "inspect", "--format", "{{.Id}}", image])
    if running and latest and running == latest:
        return "current"

    compose_cmd = ["docker", "compose", "-p", settings.compose_project]
    for config_file in ctx.config_files:
        compose_cmd += ["-f", config_file]
    compose_cmd += ["up", "-d", "--force-recreate", "--no-deps", service]
    mounts = ["-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{ctx.project_dir}:{ctx.project_dir}:ro"]
    for config_file in ctx.config_files:
        if not config_file.startswith(ctx.project_dir.rstrip("/") + "/"):
            mounts += ["-v", f"{config_file}:{config_file}:ro"]
    job.status = "recreating"
    code, _ = await _run_step(
        job,
        settings,
        Step(f"restart {service} with the new image"),
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            f"{settings.compose_project}-updater-self-update",
            *mounts,
            "-w",
            ctx.project_dir,
            image,
            "sh",
            "-c",
            'sleep 5 && exec "$@"',
            "self-update",
            *compose_cmd,
        ],
    )
    return "restarting" if code == 0 else "failed"


async def run_update_job(job: UpdateJob, settings: Settings) -> None:
    try:
        ctx = await compose_context(settings)
    except Exception as exc:  # defensive: discovery must never block the update
        ctx = ComposeContext(
            base=["docker", "compose", "-p", settings.compose_project, "-f", str(settings.compose_file)]
        )
        job.safe_log_tail = sanitize_log(f"Compose project discovery failed: {exc}", settings)
    compose_base = ctx.base
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

        notes: list[str] = []
        if settings.update_slicer_sidecars or settings.update_self:
            services = await _compose_services(job, settings, ctx)
            if services is None:
                notes.append("sidecar update failed")
            else:
                if settings.update_slicer_sidecars and not await _update_slicer_sidecars(job, settings, ctx, services):
                    notes.append("slicer sidecar update failed")
                if settings.update_self:
                    self_result = await _update_self(job, settings, ctx, services)
                    if self_result == "restarting":
                        notes.append("updater restarts with the new version")
                    elif self_result == "failed":
                        notes.append("updater self-update failed")
        job.status = "completed"
        job.exit_code = 0
        job.message = "; ".join(["Container recreated", *notes])
    except Exception as exc:  # defensive: keep API status useful if subprocess setup blows up
        job.status = "failed"
        job.exit_code = 1
        job.message = "Update job failed"
        job.safe_log_tail = sanitize_log(str(exc), settings)
    finally:
        job.finished_at = datetime.now(UTC).isoformat()
