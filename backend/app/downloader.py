"""Availability checks for the SpotiFLAC download engine.

SpotiFLAC depends on community-run resolver/proxy services that break
regularly, and its failures only surface at runtime. Two levels of checking:

- ``status()``  — cheap: is the package importable, what happened to the most
  recent job, and the cached result of the last deep probe.
- ``probe()``   — honest but expensive: actually downloads one known track
  (``PROBE_SPOTIFY_URL``) into a throwaway dir. This is the only reliable
  "can it download songs right now" signal.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import logging
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .config import Settings
from .db import SessionLocal
from .models import Job
from .spotiflac_adapter import SpotiFlacError, run_spotiflac

log = logging.getLogger(__name__)

# Last deep-probe result, kept in memory (the backend has a single process).
# A restart loses it; the periodic loop repopulates it within a minute.
_last_probe: dict | None = None
_last_probe_epoch: float = 0.0
_probe_lock = asyncio.Lock()


def _freshness_window_seconds(settings: Settings) -> float:
    # With the periodic loop on, a result older than one interval means the
    # loop is behind (job running, backend restart) — treat it as stale.
    minutes = settings.probe_interval_minutes if settings.probe_interval_minutes > 0 else 30.0
    return minutes * 60


def probe_is_fresh(settings: Settings) -> bool:
    return _last_probe is not None and (time.time() - _last_probe_epoch) < _freshness_window_seconds(settings)


def check_importable() -> tuple[bool, str | None]:
    """Is the SpotiFLAC package installed?

    Deliberately uses ``find_spec`` and never executes package code:
    importing SpotiFLAC contacts its cloud resolvers with long retries at
    import time, which would hang this "cheap" check for minutes when they
    are down. The probe is the check that actually runs the package (in a
    worker thread, via ``run_spotiflac``'s own lazy import).
    """
    try:
        spec = importlib.util.find_spec("SpotiFLAC")
    except Exception as exc:  # pragma: no cover - malformed install
        return False, str(exc)
    if spec is None:
        return False, "SpotiFLAC package is not installed"
    return True, None


def installed_version() -> str | None:
    """Installed SpotiFLAC version from dist metadata (no code executed)."""
    try:
        return importlib.metadata.version("SpotiFLAC")
    except Exception:
        return None


def _last_job_summary() -> dict | None:
    with SessionLocal() as session:
        job = session.scalars(select(Job).order_by(Job.updated_at.desc())).first()
        if job is None:
            return None
        return {
            "status": job.status,
            "error": job.error,
            "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
        }


async def status(settings: Settings, active_jobs: bool) -> dict:
    loop = asyncio.get_running_loop()
    importable, import_error = check_importable()  # find_spec only — fast
    return {
        "importable": importable,
        "importError": import_error,
        "version": installed_version(),
        "services": list(settings.default_services),
        "quality": settings.quality,
        "activeJobs": active_jobs,
        "lastJob": await loop.run_in_executor(None, _last_job_summary),
        "lastProbe": _last_probe,
        "probing": _probe_lock.locked(),
    }


async def probe(settings: Settings) -> dict:
    """Download one sample track into a temp dir and report the outcome.

    The caller must ensure no real job is running (probes compete for the same
    rate-limited upstream services). Serialized by an internal lock.
    """
    global _last_probe
    async with _probe_lock:
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        tmp_dir = Path(tempfile.mkdtemp(prefix="probe-", dir=settings.data_dir))
        ok = False
        detail: str | None = None
        future = None
        try:
            future = loop.run_in_executor(
                None,
                run_spotiflac,
                settings.probe_spotify_url,
                tmp_dir,
                list(settings.default_services),
                settings.quality,
                settings.qobuz_token,
                0,  # no retries: a probe should reflect first-attempt health
                None,
            )
            await asyncio.wait_for(asyncio.shield(future), timeout=settings.probe_timeout_seconds)
            ok = any(tmp_dir.rglob("*.flac"))
            if not ok:
                detail = "SpotiFLAC ran but produced no files — all sources failed."
        except asyncio.TimeoutError:
            detail = f"Probe timed out after {int(settings.probe_timeout_seconds)}s."
            # The executor thread cannot be killed; clean up when it finishes.
            # Bind the path as a default arg — tmp_dir is reassigned to None on
            # the next line, and a plain closure would capture that instead.
            future.add_done_callback(
                lambda f, path=tmp_dir: (f.exception(), shutil.rmtree(path, ignore_errors=True))
            )
            tmp_dir = None
        except SpotiFlacError as exc:
            detail = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            detail = f"Unexpected probe error: {exc}"
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        global _last_probe_epoch
        _last_probe = {
            "ok": ok,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsedSeconds": round(time.monotonic() - started, 1),
        }
        _last_probe_epoch = time.time()
        log.info("Downloader probe finished: ok=%s detail=%s", ok, detail)
        return _last_probe


async def probe_or_cached(settings: Settings, force: bool) -> dict:
    """Instant answer from the stored result when it's fresh; otherwise (or
    with ``force``) run a real probe."""
    if not force and probe_is_fresh(settings):
        return {**_last_probe, "cached": True}
    result = await probe(settings)
    return {**result, "cached": False}


def probing() -> bool:
    return _probe_lock.locked()


async def periodic_probe_loop(settings: Settings, has_active_jobs) -> None:
    """Background task: keep the stored probe result fresh.

    Ticks every minute and probes whenever the result is stale, skipping
    ticks while a real job runs (probes must not compete for the same
    rate-limited upstream services) — the next tick catches up.
    """
    if settings.probe_interval_minutes <= 0:
        log.info("Periodic downloader probe disabled (PROBE_INTERVAL_MINUTES=0)")
        return
    importable, why = check_importable()
    if not importable:
        log.warning("Periodic downloader probe disabled: %s", why)
        return
    log.info("Periodic downloader probe every %.0f min", settings.probe_interval_minutes)
    while True:
        try:
            if not probe_is_fresh(settings) and not has_active_jobs() and not _probe_lock.locked():
                await probe(settings)
        except asyncio.CancelledError:
            return
        except Exception:  # pragma: no cover - defensive
            log.exception("Periodic probe pass failed")
        await asyncio.sleep(60)
