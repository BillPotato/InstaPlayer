"""System / storage report for the admin dashboard (GET /admin/system).

Read-only: disk usage of the data volume, size of the transient job store and
the log files, server uptime, and a summary of the effective (env-driven)
config. All values are cheap to compute for a personal single-user backend.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _count_dirs(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for e in os.scandir(path) if e.is_dir())
    except OSError:
        return 0


def _count(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for _ in path.glob(pattern))
    except OSError:
        return 0


def system_report(settings: Settings, started_at: datetime) -> dict:
    now = datetime.now(timezone.utc)
    try:
        du = shutil.disk_usage(settings.data_dir)
        disk = {"total": du.total, "used": du.used, "free": du.free}
    except OSError:
        disk = None
    return {
        "startedAt": started_at.isoformat(),
        "uptimeSeconds": max(0, int((now - started_at).total_seconds())),
        "disk": disk,
        "jobStore": {
            "bytes": _dir_size(settings.jobs_dir),
            "activeDirs": _count_dirs(settings.jobs_dir),
        },
        "logs": {
            "bytes": _dir_size(settings.logs_dir),
            "days": _count(settings.logs_dir, "*.jsonl"),
        },
        "config": {
            "services": list(settings.default_services),
            "quality": settings.quality,
            "trackMaxRetries": settings.track_max_retries,
            "jobRetentionHours": settings.job_retention_hours,
            "probeIntervalMinutes": settings.probe_interval_minutes,
            "logRetentionDays": settings.log_retention_days,
            "spootyEnabled": bool(settings.spooty_base_url),
            "qobuzTokenSet": bool(settings.qobuz_token),
        },
    }
