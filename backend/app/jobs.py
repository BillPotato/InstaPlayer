"""In-process async job manager.

SpotiFLAC is a blocking, opaque call, so each job:
  1. runs SpotiFLAC in a thread executor into a per-job dir,
  2. concurrently watches that dir and publishes a coarse progress count,
  3. builds a manifest (metadata + art sidecars) the device pulls from.

The job dir is then retained until the device has fetched everything and calls
DELETE /jobs/{id} (or the reaper deletes it after job_retention_hours). The
backend keeps no permanent copy of any song.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .db import SessionLocal
from .ingest import build_manifest, scan_flacs
from .models import Job
from .spotiflac_adapter import SpotiFlacError, run_spotiflac

log = logging.getLogger(__name__)


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
                return {"type": "status", "jobId": job_id, "status": "failed",
                        "completed": 0, "total": 0, "current": None,
                        "error": "Job record not found"}
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
            }
        self._publish(job_id, event)
        return event

    async def _watch(self, job_id: str, job_dir: Path, progress: dict[str, Any]) -> None:
        """Poll the job dir + shared progress and publish status updates."""
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

            # Build the manifest (blocking-ish) the device will fetch from.
            manifest = await loop.run_in_executor(
                None, build_manifest, job_dir, spotify_url
            )
            count = manifest["trackCount"]
            total = progress.get("total") or count
            if count == 0:
                # Nothing downloaded — drop the empty dir, report clearly.
                shutil.rmtree(job_dir, ignore_errors=True)
                self._set_status(
                    job_id, status="completed", total=total, completed=0,
                    current=None,
                    error="No tracks could be downloaded — all sources failed. "
                    "Try again later.",
                )
            else:
                # Keep the dir; the device pulls from it, then DELETEs the job.
                self._set_status(
                    job_id, status="completed", total=total, completed=count,
                    current=None, error=None,
                )
        except SpotiFlacError as exc:
            watcher.cancel()
            shutil.rmtree(job_dir, ignore_errors=True)
            self._set_status(job_id, status="failed", current=None, error=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            watcher.cancel()
            shutil.rmtree(job_dir, ignore_errors=True)
            self._set_status(
                job_id, status="failed", current=None, error=f"Unexpected error: {exc}"
            )

    def delete_job(self, job_id: str) -> None:
        """Device finished pulling: delete the files and the job row."""
        shutil.rmtree(self.settings.jobs_dir / job_id, ignore_errors=True)
        self._last_event.pop(job_id, None)
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if job is not None:
                session.delete(job)
                session.commit()

    async def reaper(self) -> None:
        """Periodically delete abandoned job dirs older than the retention TTL."""
        while True:
            try:
                await asyncio.sleep(1800)  # every 30 min
                self._reap_once()
            except asyncio.CancelledError:
                return
            except Exception:  # pragma: no cover - defensive
                log.exception("Reaper pass failed")

    def _reap_once(self) -> None:
        # Use filesystem mtime (robust across SQLite tz handling): any job dir
        # untouched for longer than the retention window is abandoned.
        jobs_dir = self.settings.jobs_dir
        if not jobs_dir.exists():
            return
        cutoff = time.time() - self.settings.job_retention_hours * 3600
        with SessionLocal() as session:
            for child in jobs_dir.iterdir():
                if not child.is_dir() or child.stat().st_mtime >= cutoff:
                    continue
                log.info("Reaping abandoned job dir %s", child.name)
                shutil.rmtree(child, ignore_errors=True)
                job = session.get(Job, child.name)
                if job is not None:
                    session.delete(job)
                    session.commit()


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager(get_settings())
    return _manager
