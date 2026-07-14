"""Availability checks for the SpotiFLAC download engine.

The engine is the vendored ``spotiflac-dl`` Go binary. It depends on
community-run resolver/proxy services that break regularly, and those failures
only surface at runtime. Two levels of checking:

- ``status()``  — cheap: is the engine binary present/runnable, what happened
  to the most recent job, and the cached result of the last deep probe.
- ``probe()``   — honest but expensive: actually downloads one known track
  (``PROBE_SPOTIFY_URL``) into a throwaway dir. This is the only reliable
  "can it download songs right now" signal.
"""
from __future__ import annotations

import asyncio
import json
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
from .spotiflac_adapter import (
    BINARY_NAME,
    SpotiFlacError,
    binary_version,
    resolve_binary,
    run_spotiflac,
)

log = logging.getLogger(__name__)

# Last deep-probe result. Kept in memory (single process) AND mirrored to disk,
# so a backend restart within the freshness window reuses it instead of probing
# again (each probe downloads a real track — slow and rate-limit-hungry). The
# epoch is wall-clock (time.time), so the freshness check survives restarts.
_last_probe: dict | None = None
_last_probe_epoch: float = 0.0
_probe_lock = asyncio.Lock()

# The probe cache is mirrored here, inside DATA_DIR (next to the job store).
_PROBE_CACHE_NAME = "last_probe.json"


def _probe_cache_path(settings: Settings) -> Path:
    return settings.data_dir / _PROBE_CACHE_NAME


def _persist_probe(settings: Settings) -> None:
    """Best-effort mirror of the current probe result to disk."""
    if _last_probe is None:
        return
    try:
        path = _probe_cache_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"probe": _last_probe, "epoch": _last_probe_epoch}),
            encoding="utf-8",
        )
    except Exception:  # pragma: no cover - the cache is advisory
        log.debug("Could not persist probe cache", exc_info=True)


def load_persisted_probe(settings: Settings) -> None:
    """Load the probe cache from disk into memory at startup, so a fresh cached
    result suppresses an immediate re-probe after a restart. No-op if the file
    is missing/unreadable or a result is already in memory."""
    global _last_probe, _last_probe_epoch
    if _last_probe is not None:
        return
    try:
        data = json.loads(_probe_cache_path(settings).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception:  # pragma: no cover - corrupt/partial cache
        log.debug("Could not read probe cache", exc_info=True)
        return
    probe = data.get("probe")
    epoch = data.get("epoch")
    if isinstance(probe, dict) and isinstance(epoch, (int, float)):
        _last_probe = probe
        _last_probe_epoch = float(epoch)
        age_min = max(0, int((time.time() - _last_probe_epoch) / 60))
        log.info("Loaded cached probe from disk (ok=%s, %d min old)", probe.get("ok"), age_min)


def _freshness_window_seconds(settings: Settings) -> float:
    # With the periodic loop on, a result older than one interval means the
    # loop is behind (job running, backend restart) — treat it as stale.
    minutes = settings.probe_interval_minutes if settings.probe_interval_minutes > 0 else 30.0
    return minutes * 60


def probe_is_fresh(settings: Settings) -> bool:
    return _last_probe is not None and (time.time() - _last_probe_epoch) < _freshness_window_seconds(settings)


def check_importable() -> tuple[bool, str | None]:
    """Is the ``spotiflac-dl`` engine binary available and runnable?

    Kept under the historical name so callers (``main.py``, ``status``) are
    unchanged. Cheap and network-free: resolves the binary on PATH and runs
    ``--version``. (The real download run happens in a worker thread via
    ``run_spotiflac``.)
    """
    binary = resolve_binary()
    if binary is None:
        return False, f"{BINARY_NAME} binary not found (set SPOTIFLAC_DL_BIN or add it to PATH)"
    if binary_version() is None:
        return False, f"{BINARY_NAME} found at {binary} but did not run"
    return True, None


def installed_version() -> str | None:
    """Version reported by the engine binary (``spotiflac-dl --version``)."""
    return binary_version()


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
    importable, import_error = check_importable()  # binary presence + --version
    installed = installed_version()
    # No package registry to compare against now — the engine is a vendored
    # binary, kept current with scripts/update-spotiflac.sh. Keep the keys for
    # frontend compatibility; there's simply never an "update available" hint.
    return {
        "importable": importable,
        "importError": import_error,
        "version": installed,
        "latestVersion": None,
        "updateAvailable": False,
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
        _persist_probe(settings)  # survive restarts within the freshness window
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
