from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status

from updater.app.auth import require_token
from updater.app.jobs import get_job_store, run_update_job
from updater.app.settings import Settings, get_settings

app = FastAPI(title="Printbuddy Updater", version="0.1.0")


def docker_socket_available() -> bool:
    return os.path.exists("/var/run/docker.sock")


@app.get("/health", dependencies=[Depends(require_token)])
async def health(settings: Settings = Depends(get_settings)):
    compose_file = Path(settings.compose_file)
    docker_ok = docker_socket_available()
    compose_ok = compose_file.is_file()
    return {
        "ok": docker_ok and compose_ok,
        "service": "printbuddy-updater",
        "docker_available": docker_ok,
        "compose_file_available": compose_ok,
    }


@app.post("/update", dependencies=[Depends(require_token)])
async def update(settings: Settings = Depends(get_settings)):
    if not Path(settings.compose_file).is_file():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Compose file is not mounted")

    store = get_job_store()
    try:
        job = store.create(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    import asyncio

    job.task = asyncio.create_task(run_update_job(job, settings))
    return {"accepted": True, "job_id": job.job_id, "message": "Update started"}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_token)])
async def job_status(job_id: str):
    job = get_job_store().get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update job not found")
    return job.to_dict()
