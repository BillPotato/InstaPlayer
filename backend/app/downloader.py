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

from . import adminstate, verification
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
# again (each probe downloads a real track — slow and rate-limit-hungry).
#
# `_next_probe_at` (wall-clock epoch) is when the next probe is due. Normally
# that's one interval out; but when a probe fails because a community endpoint is
# on cooldown (503 "back in ~Ns"), we push it to exactly when the cooldown
# expires — re-probing sooner would just 503 again. Wall-clock, so it survives
# restarts.
_last_probe: dict | None = None
_last_probe_epoch: float = 0.0
_next_probe_at: float = 0.0
_probe_lock = asyncio.Lock()

# Small grace after a cooldown before retrying (server clock skew / rounding),
# and a sanity cap so a bogus cooldown can't wedge the prober for hours.
_COOLDOWN_BUFFER_SECONDS = 30
_COOLDOWN_MAX_SECONDS = 3 * 3600

# The probe cache is mirrored here, inside DATA_DIR (next to the job store).
_PROBE_CACHE_NAME = "last_probe.json"

# Rolling history of recent download-health outcomes (for the dashboard's
# green/red reliability timeline). Fed by both the hourly probe (source="probe")
# and real download jobs' terminal outcomes (source="job"). In memory + mirrored
# to disk; bounded. Each entry: {at, ok, source, detail?}.
_probe_history: list[dict] = []
_PROBE_HISTORY_MAX = 200
_PROBE_HISTORY_NAME = "probe_history.json"


def _probe_cache_path(settings: Settings) -> Path:
    return settings.data_dir / _PROBE_CACHE_NAME


def _history_path(settings: Settings) -> Path:
    return settings.data_dir / _PROBE_HISTORY_NAME


def _persist_history(settings: Settings) -> None:
    try:
        path = _history_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_probe_history), encoding="utf-8")
    except Exception:  # pragma: no cover - advisory
        log.debug("Could not persist probe history", exc_info=True)


def _load_history(settings: Settings) -> None:
    global _probe_history
    if _probe_history:
        return
    try:
        data = json.loads(_history_path(settings).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception:  # pragma: no cover - corrupt cache
        log.debug("Could not read probe history", exc_info=True)
        return
    if isinstance(data, list):
        _probe_history = [x for x in data if isinstance(x, dict) and "ok" in x][-_PROBE_HISTORY_MAX:]


def probe_history() -> dict:
    """Recent download-health outcomes (probe + real jobs) for the dashboard's
    green/red timeline, plus a pass count."""
    ok_count = sum(1 for x in _probe_history if x.get("ok"))
    return {"history": list(_probe_history), "okCount": ok_count, "total": len(_probe_history)}


def clear_history(settings: Settings) -> None:
    """Wipe the health timeline (admin action — e.g. after fixing an outage,
    so the dashboard starts a clean record)."""
    _probe_history.clear()
    _persist_history(settings)
    log.info("Download-health history cleared by admin")


def record_download_outcome(settings: Settings, ok: bool, detail: str | None = None) -> None:
    """Append a real download job's terminal outcome to the health timeline, so
    the dashboard's green/red timeline reflects actual downloads, not just the
    hourly probe. Best-effort; never raises."""
    try:
        _probe_history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "ok": bool(ok),
            "source": "job",
            "detail": detail or None,
        })
        del _probe_history[:-_PROBE_HISTORY_MAX]
        _persist_history(settings)
    except Exception:  # pragma: no cover - advisory
        log.debug("Could not record download outcome", exc_info=True)


def _persist_probe(settings: Settings) -> None:
    """Best-effort mirror of the current probe result to disk."""
    if _last_probe is None:
        return
    try:
        path = _probe_cache_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"probe": _last_probe, "epoch": _last_probe_epoch, "nextAt": _next_probe_at}),
            encoding="utf-8",
        )
    except Exception:  # pragma: no cover - the cache is advisory
        log.debug("Could not persist probe cache", exc_info=True)


def load_persisted_probe(settings: Settings) -> None:
    """Load the probe cache from disk into memory at startup, so a fresh cached
    result (or an active cooldown) suppresses an immediate re-probe after a
    restart. No-op if the file is missing/unreadable or a result is in memory."""
    global _last_probe, _last_probe_epoch, _next_probe_at
    _load_history(settings)  # independent of the last-probe cache below
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
        next_at = data.get("nextAt")
        _next_probe_at = (
            float(next_at)
            if isinstance(next_at, (int, float))
            else _last_probe_epoch + _freshness_window_seconds(settings)  # older cache
        )
        age_min = max(0, int((time.time() - _last_probe_epoch) / 60))
        log.info("Loaded cached probe from disk (ok=%s, %d min old)", probe.get("ok"), age_min)


def _freshness_window_seconds(settings: Settings) -> float:
    # With the periodic loop on, a result older than one interval means the
    # loop is behind (job running, backend restart) — treat it as stale.
    minutes = settings.probe_interval_minutes if settings.probe_interval_minutes > 0 else 30.0
    return minutes * 60


def probe_is_fresh(settings: Settings) -> bool:
    # "Fresh" = a result exists and the next probe isn't due yet. During a
    # cooldown that window stretches to the cooldown's expiry.
    return _last_probe is not None and time.time() < _next_probe_at


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


def _job_summaries() -> tuple[dict | None, dict | None]:
    """(last, active) job summaries in one DB round-trip.

    ``last`` is the most recently updated job of any status; ``active`` is the
    newest queued/running one (usually the same row while a job runs) — the
    dashboard shows its progress / downloads remaining."""
    with SessionLocal() as session:
        job = session.scalars(select(Job).order_by(Job.updated_at.desc())).first()
        last = None
        if job is not None:
            last = {
                "status": job.status,
                "error": job.error,
                "updatedAt": job.updated_at.isoformat() if job.updated_at else None,
            }
        active_row = job if job is not None and job.status in ("queued", "running") else (
            session.scalars(
                select(Job)
                .where(Job.status.in_(["queued", "running"]))
                .order_by(Job.updated_at.desc())
            ).first()
        )
        active = None
        if active_row is not None:
            active = {
                "id": active_row.id,
                "status": active_row.status,
                "total": active_row.total,
                "completed": active_row.completed,
                "current": active_row.current,
                "spotifyUrl": active_row.spotify_url,
            }
        return last, active


async def status(
    settings: Settings, active_jobs: bool, include_verification: bool = True
) -> dict:
    """Cheap availability report.

    ``include_verification`` reads the community session file and checks that
    a browser is installed, so the unauthenticated public status turns it off:
    that work belongs behind auth, and nothing sanitized ever exposed it.
    """
    loop = asyncio.get_running_loop()
    importable, import_error = check_importable()  # binary presence + --version
    installed = installed_version()
    # No package registry to compare against now — the engine is a vendored
    # binary, kept current with scripts/update-spotiflac.sh. Keep the keys for
    # frontend compatibility; there's simply never an "update available" hint.
    last_job, active_job = await loop.run_in_executor(None, _job_summaries)
    return {
        # One verdict every client renders, so they can't disagree.
        "health": health_verdict(importable, _last_probe, last_job),
        "importable": importable,
        "importError": import_error,
        "version": installed,
        "latestVersion": None,
        "updateAvailable": False,
        "services": list(settings.default_services),
        "quality": settings.quality,
        "activeJobs": active_jobs,
        "lastJob": last_job,
        "activeJob": active_job,
        # Community session state. A download can't reach any provider without
        # one, so an invalid session here explains an otherwise baffling
        # "all sources failed" run.
        "verification": verification.status_report(settings) if include_verification else None,
        "lastProbe": _last_probe,
        "nextProbeAt": (
            datetime.fromtimestamp(_next_probe_at, tz=timezone.utc).isoformat()
            if _next_probe_at > 0
            else None
        ),
        "probing": _probe_lock.locked(),
    }


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def health_verdict(importable: bool,
                   last_probe: dict | None, last_job: dict | None) -> dict:
    """The single "can users download right now?" answer.

    Computed here so the admin dashboard, the public page and the phone all
    agree — they used to each apply their own rule and disagree (a stale failed
    job showed red on the phone while the dashboard was green).

    A failed last job only counts while it is the most recent evidence: once a
    probe succeeds *after* it, the failure is history and the verdict clears.
    That's what makes "Force probe" fix a red light, which is what an operator
    expects it to do.

    Reasons are deliberately generic: this verdict is served unauthenticated on
    ``/public/status``. The diagnostic text (``importError``, probe ``detail``)
    stays on the authed endpoints.
    """
    if not importable:
        return {"ok": False, "code": "engine",
                "reason": "The download engine is not available."}

    cooldown_until = _parse_iso((last_probe or {}).get("cooldownUntil"))
    if cooldown_until and cooldown_until > datetime.now(timezone.utc):
        return {"ok": False, "code": "cooldown",
                "reason": "The music sources are rate-limiting us right now."}

    probe_at = _parse_iso((last_probe or {}).get("at"))
    if last_probe is not None and last_probe.get("ok") is False:
        return {"ok": False, "code": "probe",
                "reason": "The last health check could not download a song."}

    if last_job and last_job.get("status") == "failed":
        job_at = _parse_iso(last_job.get("updatedAt"))
        # Superseded by a newer successful probe? Then it's no longer the truth.
        superseded = (
            probe_at is not None
            and (last_probe or {}).get("ok") is True
            and job_at is not None
            and probe_at >= job_at
        )
        if not superseded:
            return {"ok": False, "code": "lastJob",
                    "reason": "The most recent download failed."}

    return {"ok": True, "code": "ready", "reason": "Downloads are working."}


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
        cooldown: int | None = None
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
            cooldown = getattr(exc, "cooldown_seconds", None)
        except Exception as exc:  # pragma: no cover - defensive
            detail = f"Unexpected probe error: {exc}"
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        global _last_probe_epoch, _next_probe_at
        now = time.time()
        cooldown_until: str | None = None
        if not ok and cooldown:
            # On cooldown: don't re-probe until it expires (+ a small grace).
            wait = min(int(cooldown), _COOLDOWN_MAX_SECONDS) + _COOLDOWN_BUFFER_SECONDS
            _next_probe_at = now + wait
            cooldown_until = datetime.fromtimestamp(_next_probe_at, tz=timezone.utc).isoformat()
            detail = f"On cooldown — retrying in ~{max(1, round(wait / 60))} min. {detail or ''}".strip()
        else:
            _next_probe_at = now + _freshness_window_seconds(settings)
        _last_probe = {
            "ok": ok,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
            "elapsedSeconds": round(time.monotonic() - started, 1),
            # Set only when the failure was an upstream cooldown — lets the
            # dashboard show "on cooldown until X" vs a routine next check.
            # Rides along in last_probe.json via _persist_probe for free.
            "cooldownUntil": cooldown_until,
        }
        _last_probe_epoch = now
        _persist_probe(settings)  # survive restarts within the freshness / cooldown window
        _probe_history.append({"at": _last_probe["at"], "ok": ok, "source": "probe"})
        del _probe_history[:-_PROBE_HISTORY_MAX]  # keep the last N
        _persist_history(settings)
        log.info(
            "Downloader probe finished: ok=%s cooldown=%ss detail=%s",
            ok, cooldown, detail,
        )
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

    Ticks every minute and probes whenever one is due (``not probe_is_fresh``),
    skipping ticks while a real job runs (probes must not compete for the same
    rate-limited upstream services) — the next tick catches up. "Due" normally
    means one interval has passed, but after a cooldown failure it means the
    cooldown has expired, so we retry right when the server is back rather than
    hammering it (or waiting a full interval). The 1-minute tick is a cheap
    time-comparison; the deadline itself lives in ``_next_probe_at``.
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
            if (
                not adminstate.probes_paused()  # admin kill-switch (dashboard toggle)
                and not probe_is_fresh(settings)
                and not has_active_jobs()
                and not _probe_lock.locked()
            ):
                await probe(settings)
        except asyncio.CancelledError:
            return
        except Exception:  # pragma: no cover - defensive
            log.exception("Periodic probe pass failed")
        await asyncio.sleep(60)
