"""FastAPI application: jobs, library browsing, and file/art/lyrics serving."""
from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import require_auth
from .config import Settings, get_settings
from .db import get_session, init_db
from .jobs import JobManager, get_job_manager
from .models import Job, Playlist, PlaylistTrack, Track
from .schemas import JobCreate, JobOut, PlaylistOut, TrackOut

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    init_db()
    yield


app = FastAPI(title="Music App Backend", version="0.1.0", lifespan=lifespan)


# --------------------------------------------------------------------------
# Global error handler — always return JSON so clients can parse the error.
# --------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.error("Unhandled exception on %s %s: %s", request.method, request.url.path,
              "".join(traceback.format_exception(exc)))
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
    )


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
    # Use an explicit SELECT rather than session.get() to guarantee we hit the
    # DB (not just the identity map) after the job was committed in a separate
    # session inside submit().
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


@app.websocket("/jobs/{job_id}/events")
async def job_events(
    websocket: WebSocket,
    job_id: str,
    settings: Settings = Depends(get_settings),
    manager: JobManager = Depends(get_job_manager),
) -> None:
    # WebSocket auth: token passed as ?token= since browsers can't set headers.
    token = websocket.query_params.get("token")
    if token != settings.api_key:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    queue = manager.subscribe(job_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("type") == "status" and event.get("status") in {
                "completed",
                "failed",
            }:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(job_id, queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass  # already closed


# --------------------------------------------------------------------------
# Library
# --------------------------------------------------------------------------
@app.get("/playlists", response_model=list[PlaylistOut], dependencies=[Depends(require_auth)])
def list_playlists(session: Session = Depends(get_session)) -> list[PlaylistOut]:
    rows = session.execute(
        select(Playlist, func.count(PlaylistTrack.id))
        .outerjoin(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)
        .group_by(Playlist.id)
        .order_by(Playlist.updated_at.desc())
    ).all()
    return [
        PlaylistOut(
            id=p.id,
            name=p.name,
            spotify_url=p.spotify_url,
            track_count=count,
            updated_at=p.updated_at,
        )
        for p, count in rows
    ]


@app.get(
    "/playlists/{playlist_id}/tracks",
    response_model=list[TrackOut],
    dependencies=[Depends(require_auth)],
)
def playlist_tracks(playlist_id: str, session: Session = Depends(get_session)) -> list[TrackOut]:
    playlist = session.get(Playlist, playlist_id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    return [_track_out(link.track) for link in playlist.track_links if link.track is not None]


@app.get("/tracks", response_model=list[TrackOut], dependencies=[Depends(require_auth)])
def list_tracks(
    updated_since: float | None = Query(default=None, description="Unix epoch seconds"),
    session: Session = Depends(get_session),
) -> list[TrackOut]:
    stmt = select(Track).order_by(Track.updated_at.desc())
    if updated_since is not None:
        from datetime import datetime, timezone

        cutoff = datetime.fromtimestamp(updated_since, tz=timezone.utc)
        stmt = stmt.where(Track.updated_at > cutoff)
    return [_track_out(t) for t in session.scalars(stmt)]


@app.get("/tracks/{track_id}", response_model=TrackOut, dependencies=[Depends(require_auth)])
def get_track(track_id: str, session: Session = Depends(get_session)) -> TrackOut:
    track = _require_track(session, track_id)
    return _track_out(track)


@app.get("/tracks/{track_id}/file", dependencies=[Depends(require_auth)])
def get_track_file(track_id: str, session: Session = Depends(get_session)) -> FileResponse:
    track = _require_track(session, track_id)
    path = Path(track.file_path)
    if not path.exists():
        raise HTTPException(410, "File missing on server")
    # Starlette's FileResponse honours the Range header → 206 Partial Content,
    # which is what the client's resumable downloader relies on.
    safe_filename = "".join(c for c in track.title if c.isalnum() or c in " -_.")[:100] or track.id
    return FileResponse(path, media_type=track.mime, filename=f"{safe_filename}.flac")


@app.get("/tracks/{track_id}/art", dependencies=[Depends(require_auth)])
def get_track_art(track_id: str, session: Session = Depends(get_session)) -> FileResponse:
    track = _require_track(session, track_id)
    if not track.art_path or not Path(track.art_path).exists():
        raise HTTPException(404, "No art")
    return FileResponse(track.art_path)


@app.get("/tracks/{track_id}/lyrics", dependencies=[Depends(require_auth)])
def get_track_lyrics(track_id: str, session: Session = Depends(get_session)) -> PlainTextResponse:
    track = _require_track(session, track_id)
    if not track.lyrics:
        raise HTTPException(404, "No lyrics")
    return PlainTextResponse(track.lyrics)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _require_track(session: Session, track_id: str) -> Track:
    track = session.get(Track, track_id)
    if not track:
        raise HTTPException(404, "Track not found")
    return track


def _track_out(track: Track) -> TrackOut:
    out = TrackOut.model_validate(track)
    out.has_art = bool(track.art_path)
    out.has_lyrics = bool(track.lyrics)
    return out
