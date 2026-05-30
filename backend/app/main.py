"""FastAPI application: download jobs + job-scoped file serving.

The backend stores nothing permanently. A job downloads FLACs into a temp dir,
the device pulls the manifest + files + art, then DELETEs the job (a reaper
cleans up anything abandoned). There is no server-side music library.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_auth
from .config import Settings, get_settings
from .db import SessionLocal, get_session, init_db
from .ingest import load_manifest
from .jobs import JobManager, get_job_manager
from .models import Job
from .schemas import JobCreate, JobOut, Manifest

log = logging.getLogger(__name__)


def _fail_orphaned_jobs() -> None:
    """Mark any jobs still in a non-terminal state as failed.

    A job left in ``running`` or ``queued`` when the server stopped can never
    resume — its asyncio task is gone. Without this, clients that are still
    alive keep polling ``GET /jobs/{id}``, see status=``running``, and flood
    ``GET /jobs/{id}/manifest`` every second forever.
    """
    with SessionLocal() as session:
        orphans = session.scalars(
            select(Job).where(Job.status.in_(["running", "queued"]))
        ).all()
        if orphans:
            log.warning(
                "Marking %d orphaned job(s) as failed on startup", len(orphans)
            )
        for job in orphans:
            job.status = "failed"
            job.error = "Server restarted while this job was running."
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    init_db()
    _fail_orphaned_jobs()
    reaper = asyncio.create_task(get_job_manager().reaper())
    try:
        yield
    finally:
        reaper.cancel()


app = FastAPI(title="Music App Backend", version="0.2.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.error("Unhandled exception on %s %s: %s", request.method, request.url.path,
              "".join(traceback.format_exception(exc)))
    return JSONResponse(status_code=500, content={"detail": f"Internal server error: {exc}"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
@app.post("/jobs", response_model=JobOut, dependencies=[Depends(require_auth)])
async def create_job(
    payload: JobCreate,
    manager: JobManager = Depends(get_job_manager),
    session: Session = Depends(get_session),
) -> Job:
    job_id = await manager.submit(payload.spotifyUrl, payload.preferredSource)
    job = session.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(500, detail="Job was created but could not be retrieved")
    return job


@app.get("/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_auth)])
def get_job(job_id: str, session: Session = Depends(get_session)) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.delete("/jobs/{job_id}", dependencies=[Depends(require_auth)])
def delete_job(job_id: str, manager: JobManager = Depends(get_job_manager)) -> dict[str, str]:
    # Device has pulled everything it needs — drop the temp files.
    manager.delete_job(job_id)
    return {"status": "deleted"}


@app.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_auth)])
def cancel_job(job_id: str, manager: JobManager = Depends(get_job_manager)) -> dict[str, str]:
    """Signal the backend to stop a running job. The cancellation is async:
    the job will transition to ``cancelled`` and the WebSocket will deliver the
    terminal event shortly after this call returns."""
    manager.cancel_job(_safe_job(job_id))
    return {"status": "cancelling"}


@app.websocket("/jobs/{job_id}/events")
async def job_events(
    websocket: WebSocket,
    job_id: str,
    settings: Settings = Depends(get_settings),
    manager: JobManager = Depends(get_job_manager),
) -> None:
    token = websocket.query_params.get("token")
    if token != settings.api_key:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    # subscribe() also cancels any pending disconnect-triggered cancel timer.
    queue = manager.subscribe(job_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") == "status" and event.get("status") in {
                "completed", "failed", "cancelled"
            }:
                break
    except WebSocketDisconnect:
        # Client dropped the connection. Start a grace-period timer: if no
        # client reconnects within 20 s, the job is auto-cancelled so we don't
        # burn bandwidth (or backend storage) for an unattended download.
        manager.on_client_disconnected(job_id)
    finally:
        manager.unsubscribe(job_id, queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass


# --------------------------------------------------------------------------
# Job-scoped file serving (temporary, until the device DELETEs the job)
# --------------------------------------------------------------------------
@app.get("/jobs/{job_id}/manifest", response_model=Manifest, dependencies=[Depends(require_auth)])
def job_manifest(job_id: str, settings: Settings = Depends(get_settings)) -> Manifest:
    manifest = load_manifest(settings.jobs_dir / _safe_job(job_id))
    if manifest is None:
        raise HTTPException(404, "Manifest not ready or job expired")
    return Manifest.model_validate(manifest)


@app.get("/jobs/{job_id}/files/{n}", dependencies=[Depends(require_auth)])
def job_file(job_id: str, n: int, settings: Settings = Depends(get_settings)) -> FileResponse:
    job_dir, track = _resolve_track(settings, job_id, n)
    path = _safe_path(job_dir, track["file"])
    if not path.exists():
        raise HTTPException(410, "File missing on server")
    # FileResponse honours Range → 206, which the resumable downloader needs.
    return FileResponse(path, media_type=track.get("mime", "audio/flac"))


@app.get("/jobs/{job_id}/art/{n}", dependencies=[Depends(require_auth)])
def job_art(job_id: str, n: int, settings: Settings = Depends(get_settings)) -> FileResponse:
    job_dir, track = _resolve_track(settings, job_id, n)
    art_file = track.get("artFile")
    if not art_file:
        raise HTTPException(404, "No art")
    path = _safe_path(job_dir, art_file)
    if not path.exists():
        raise HTTPException(404, "No art")
    return FileResponse(path)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _safe_job(job_id: str) -> str:
    # Job ids are uuid hex; reject anything else to prevent path traversal.
    if not job_id.isalnum():
        raise HTTPException(400, "Invalid job id")
    return job_id


def _resolve_track(settings: Settings, job_id: str, n: int) -> tuple[Path, dict]:
    job_dir = settings.jobs_dir / _safe_job(job_id)
    manifest = load_manifest(job_dir)
    if manifest is None:
        raise HTTPException(404, "Manifest not ready or job expired")
    tracks = manifest.get("tracks", [])
    if n < 0 or n >= len(tracks):
        raise HTTPException(404, "Track not found")
    return job_dir, tracks[n]


def _safe_path(job_dir: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``job_dir``, rejecting path traversal."""
    base = job_dir.resolve()
    candidate = (base / relative).resolve()
    if base != candidate and base not in candidate.parents:
        raise HTTPException(400, "Invalid path")
    return candidate
