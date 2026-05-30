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
from .ingest import scan_flacs, update_manifest
from .models import Job
from .spotiflac_adapter import SpotiFlacError, run_spotiflac

log = logging.getLogger(__name__)


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._last_event: dict[str, dict[str, Any]] = {}
        # Running download tasks, keyed by job_id — used for cancellation.
        self._tasks: dict[str, asyncio.Task] = {}
        # Per-job timers that fire cancel after a client disconnect grace period.
        self._cancel_timers: dict[str, asyncio.Task] = {}

    # ---- pub/sub ---------------------------------------------------------
    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[job_id].add(queue)
        if job_id in self._last_event:
            queue.put_nowait(self._last_event[job_id])
        # If a disconnect timer is pending (e.g. client reconnected), cancel it.
        timer = self._cancel_timers.pop(job_id, None)
        if timer and not timer.done():
            timer.cancel()
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[job_id].discard(queue)

    def _publish(self, job_id: str, event: dict[str, Any]) -> None:
        self._last_event[job_id] = event
        for queue in list(self._subscribers.get(job_id, ())):
            queue.put_nowait(event)

    # ---- cancellation ----------------------------------------------------
    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a running job. Returns True if found."""
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def on_client_disconnected(self, job_id: str) -> None:
        """Start a 20-second grace period; auto-cancel if no client reconnects."""
        if job_id in self._cancel_timers:
            return  # timer already running
        task = self._tasks.get(job_id)
        if not task or task.done():
            return  # job is not running; nothing to cancel

        async def _delayed() -> None:
            await asyncio.sleep(20)
            log.info("No client for 20 s — auto-cancelling job %s", job_id)
            self.cancel_job(job_id)

        self._cancel_timers[job_id] = asyncio.create_task(_delayed())

    # ---- job lifecycle ---------------------------------------------------
    async def submit(self, spotify_url: str, preferred_source: str | None) -> str:
        with SessionLocal() as session:
            job = Job(spotify_url=spotify_url, preferred_source=preferred_source)
            session.add(job)
            session.commit()
            job_id = job.id
        task = asyncio.create_task(self._run(job_id))
        self._tasks[job_id] = task
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

    async def _watch(
        self,
        job_id: str,
        job_dir: Path,
        spotify_url: str | None,
        progress: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        """Poll the job dir, append newly-finished tracks to the manifest, and
        publish progress. Emits ``file_ready`` for each track the moment it
        becomes fetchable — so the device starts downloading without waiting for
        the whole playlist. Also emits the coarser ``status`` update for the
        progress bar."""
        loop = asyncio.get_running_loop()
        last: tuple | None = None
        try:
            while True:
                # Manifest grows as files land; update off-thread (mutagen +
                # art/json writes would otherwise block the event loop).
                if len(scan_flacs(job_dir)) > state["emitted"]:
                    manifest = await loop.run_in_executor(
                        None, update_manifest, job_dir, spotify_url
                    )
                    new_count = manifest["trackCount"]
                    # Emit file_ready for every track that just became fetchable.
                    for n in range(state["emitted"], new_count):
                        self._publish(job_id, {"type": "file_ready", "jobId": job_id, "n": n})
                    state["emitted"] = new_count
                manifest_count = state["emitted"]
                snapshot = (manifest_count, progress.get("total"), progress.get("current"))
                if snapshot != last:
                    last = snapshot
                    fields: dict[str, Any] = {"completed": manifest_count}
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
        # Shared between _run and _watch so _run knows which file_ready events
        # have already been emitted and can cover the stragglers itself.
        state: dict[str, Any] = {"emitted": 0}

        def on_progress(update: dict[str, Any]) -> None:
            progress.update(update)

        watcher = asyncio.create_task(
            self._watch(job_id, job_dir, spotify_url, progress, state)
        )
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

            # Final pass to catch any stragglers the watcher didn't append yet.
            manifest = await loop.run_in_executor(
                None, update_manifest, job_dir, spotify_url
            )
            count = manifest["trackCount"]
            # Emit file_ready for any tracks the watcher was cancelled before seeing.
            for n in range(state["emitted"], count):
                self._publish(job_id, {"type": "file_ready", "jobId": job_id, "n": n})
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
        except asyncio.CancelledError:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
            shutil.rmtree(job_dir, ignore_errors=True)
            # Publish cancelled status before removing the DB row so any still-
            # connected client receives the terminal event cleanly.
            self._set_status(job_id, status="cancelled", current=None, error=None)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                if job is not None:
                    session.delete(job)
                    session.commit()
            self._last_event.pop(job_id, None)
            # Do NOT re-raise: the task exits cleanly after cleanup.
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
        finally:
            self._tasks.pop(job_id, None)

    def delete_job(self, job_id: str) -> None:
        """Device finished pulling — or user cancelled: delete files and job row."""
        # Stop any running download (harmless if already done).
        task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
        timer = self._cancel_timers.pop(job_id, None)
        if timer and not timer.done():
            timer.cancel()
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
