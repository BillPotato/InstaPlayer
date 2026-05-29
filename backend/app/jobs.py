"""In-process async job manager.

SpotiFLAC is a blocking, opaque call, so each job:
  1. runs SpotiFLAC in a thread executor into a per-job scratch dir,
  2. concurrently watches that dir and publishes a coarse progress count,
  3. ingests the produced FLACs into the library on completion.

Progress is broadcast to WebSocket subscribers via per-job asyncio queues.
For a single user this is plenty; swap in RQ/Redis + a real worker to scale out.
"""
from __future__ import annotations

import asyncio
import contextlib
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .db import SessionLocal
from .ingest import ingest_directory, scan_flacs
from .models import Job, Playlist
from .spotiflac_adapter import SpotiFlacError, run_spotiflac


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._last_event: dict[str, dict[str, Any]] = {}

    # ---- pub/sub ---------------------------------------------------------
    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[job_id].add(queue)
        if job_id in self._last_event:
            queue.put_nowait(self._last_event[job_id])
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[job_id].discard(queue)

    def _publish(self, job_id: str, event: dict[str, Any]) -> None:
        self._last_event[job_id] = event
        for queue in list(self._subscribers.get(job_id, ())):
            queue.put_nowait(event)

    # ---- job lifecycle ---------------------------------------------------
    async def submit(self, spotify_url: str, preferred_source: str | None) -> str:
        with SessionLocal() as session:
            job = Job(spotify_url=spotify_url, preferred_source=preferred_source)
            session.add(job)
            session.commit()
            job_id = job.id
        asyncio.create_task(self._run(job_id))
        return job_id

    def _services(self, preferred_source: str | None) -> list[str]:
        services = list(self.settings.default_services)
        if preferred_source and preferred_source in services:
            services.remove(preferred_source)
            services.insert(0, preferred_source)
        elif preferred_source:
            services.insert(0, preferred_source)
        return services

    def _set_status(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if job is None:
                # Job row went missing (e.g. manual DB clear) — emit the event
                # anyway so any open WebSocket subscribers get a terminal state.
                return {"type": "status", "jobId": job_id, "status": "failed",
                        "completed": 0, "total": 0, "current": None,
                        "error": "Job record not found", "playlistId": None}
            for key, value in fields.items():
                setattr(job, key, value)
            session.commit()
            event = {
                "type": "status",
                "jobId": job.id,
                "status": job.status,
                "completed": job.completed,
                "total": job.total,
                "current": job.current,
                "error": job.error,
                "playlistId": job.playlist_id,
            }
        self._publish(job_id, event)
        return event

    async def _watch(self, job_id: str, job_dir: Path, progress: dict[str, Any]) -> None:
        """Poll the scratch dir + shared progress and publish status updates.

        ``progress`` is mutated from the SpotiFLAC worker thread (total/current);
        the file count is the authoritative ``completed`` value.
        """
        last: tuple | None = None
        try:
            while True:
                completed = len(scan_flacs(job_dir))
                snapshot = (completed, progress.get("total"), progress.get("current"))
                if snapshot != last:
                    last = snapshot
                    fields: dict[str, Any] = {"completed": completed}
                    if progress.get("total") is not None:
                        fields["total"] = progress["total"]
                    if progress.get("current") is not None:
                        fields["current"] = progress["current"]
                    self._set_status(job_id, **fields)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    async def _run(self, job_id: str) -> None:
        loop = asyncio.get_running_loop()
        job_dir = self.settings.jobs_dir / job_id
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            spotify_url = job.spotify_url
            services = self._services(job.preferred_source)

        self._set_status(job_id, status="running")

        # Shared, thread-safe-enough holder: the worker thread only assigns to
        # these keys, the event loop only reads them.
        progress: dict[str, Any] = {"total": None, "current": None}

        def on_progress(update: dict[str, Any]) -> None:
            progress.update(update)

        watcher = asyncio.create_task(self._watch(job_id, job_dir, progress))
        try:
            await loop.run_in_executor(
                None,
                run_spotiflac,
                spotify_url,
                job_dir,
                services,
                self.settings.quality,
                self.settings.qobuz_token,
                self.settings.track_max_retries,
                on_progress,
            )
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

            # Ingest into the library (also blocking-ish; run in executor).
            count = await loop.run_in_executor(None, self._ingest, job_id, job_dir)
            total = progress.get("total") or count
            if count == 0:
                self._set_status(
                    job_id,
                    status="completed",
                    total=total,
                    completed=0,
                    current=None,
                    error="No tracks could be downloaded — all sources failed. "
                    "Try again later.",
                )
            else:
                self._set_status(
                    job_id,
                    status="completed",
                    total=total,
                    completed=count,
                    current=None,
                    error=None,
                )
        except SpotiFlacError as exc:
            watcher.cancel()
            self._set_status(job_id, status="failed", current=None, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            watcher.cancel()
            self._set_status(
                job_id, status="failed", current=None, error=f"Unexpected error: {exc}"
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    def _ingest(self, job_id: str, job_dir: Path) -> int:
        # Don't create an empty playlist when nothing downloaded.
        if not scan_flacs(job_dir):
            return 0
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            playlist = Playlist(spotify_url=job.spotify_url, name=_playlist_name(job_dir))
            session.add(playlist)
            session.flush()
            job.playlist_id = playlist.id
            session.commit()
            count = ingest_directory(session, job_dir, playlist, self.settings)
        return count


def _playlist_name(job_dir: Path) -> str:
    files = scan_flacs(job_dir)
    if files:
        # SpotiFLAC writes album/playlist sub-folders; use the top-level one.
        rel = files[0].relative_to(job_dir)
        if len(rel.parts) > 1:
            return rel.parts[0]
    return "Imported playlist"


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager(get_settings())
    return _manager
