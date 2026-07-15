"""Log capture for the admin dashboard: day-partitioned history.

Every log line is appended to a per-day JSONL file under ``DATA_DIR/logs``
(``YYYY-MM-DD.jsonl``, one ``{"seq","ts","line"}`` object per line, UTC), so the
dashboard can browse any day via a calendar / prev-next arrows. Files live in
the mounted data volume, so history survives restarts; a retention window
prunes old files on startup.

Two sources feed it: a ``logging.Handler`` on the root logger (job/probe/ingest
lifecycle lines that previously went nowhere because the app configures no
handlers) and explicit ``append()`` calls for engine output (``spotiflac_adapter``
streams the ``spotiflac-dl`` subprocess's lines from an executor thread).

Thread-safety: appenders include executor threads. Writes are serialised by a
lock (each line written whole, so lines never interleave); reads are lock-free
and tolerate a partial trailing line mid-write. The seq counter uses
``itertools.count`` (atomic ``next`` under the GIL).
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_seq = itertools.count(1)
_write_lock = threading.Lock()

_log_dir: Path | None = None
_retention_days = 30
_cur_date: str | None = None
_cur_file = None  # cached open append handle for _cur_date


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def today() -> str:
    """Server's current day (UTC), the dashboard's default view."""
    return _utc_today()


def _validate_date(date_str: str) -> str:
    """Return ``date_str`` if it's a valid YYYY-MM-DD, else raise ValueError.

    Also the guard against path traversal — the value becomes a filename."""
    datetime.strptime(date_str, "%Y-%m-%d")
    return date_str


def append(line: str) -> None:
    """Append one line to today's log file (safe from any thread).

    No-op until ``install()`` has set the log directory."""
    if _log_dir is None:
        return
    entry = {
        "seq": next(_seq),
        "ts": datetime.now(timezone.utc).isoformat(),
        "line": line,
    }
    data = json.dumps(entry, ensure_ascii=False) + "\n"
    day = _utc_today()
    try:
        with _write_lock:
            _write_locked(day, data)
    except Exception:  # pragma: no cover - never let logging break the app
        pass


def _write_locked(day: str, data: str) -> None:
    global _cur_date, _cur_file
    if _cur_file is None or _cur_date != day:
        if _cur_file is not None:
            try:
                _cur_file.close()
            except Exception:
                pass
        _cur_file = open(_log_dir / f"{day}.jsonl", "a", encoding="utf-8")
        _cur_date = day
    _cur_file.write(data)
    _cur_file.flush()


def available_days() -> list[str]:
    """Sorted (ascending) date strings that have a log file."""
    if _log_dir is None or not _log_dir.exists():
        return []
    days = []
    for p in _log_dir.glob("*.jsonl"):
        try:
            _validate_date(p.stem)
        except ValueError:
            continue
        days.append(p.stem)
    return sorted(days)


def read_day(date_str: str | None = None, after: int = 0, limit: int = 2000) -> dict:
    """Return log entries for one day (``date_str`` or today).

    ``after`` is a line offset (count already consumed) so a client can poll
    today's file cheaply for new lines. ``after <= 0`` returns the last
    ``limit`` lines (``truncated`` set if the day had more). Raises ValueError
    on a malformed date."""
    date_str = _validate_date(date_str) if date_str else _utc_today()
    result = {
        "date": date_str, "exists": False, "lines": [],
        "nextOffset": max(0, after), "total": 0, "truncated": False,
    }
    if _log_dir is None:
        return result
    path = _log_dir / f"{date_str}.jsonl"
    if not path.exists():
        return result
    result["exists"] = True
    entries: list[dict] = []
    try:
        # utf-8-sig tolerates a stray leading BOM (e.g. a hand-edited file).
        with path.open("r", encoding="utf-8-sig") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except Exception:
                    continue  # partial trailing line being written; skip
    except Exception:
        return result
    total = len(entries)
    result["total"] = total
    if after <= 0:
        start = max(0, total - limit) if limit > 0 else 0
        result["truncated"] = start > 0
    else:
        start = min(after, total)
    result["lines"] = entries[start:]
    result["nextOffset"] = total
    return result


def _prune_old() -> None:
    if _log_dir is None or _retention_days <= 0 or not _log_dir.exists():
        return
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=_retention_days)
    for p in _log_dir.glob("*.jsonl"):
        try:
            file_date = datetime.strptime(p.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                p.unlink()
            except Exception:
                pass


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            append(self.format(record))
        except Exception:  # pragma: no cover - never let logging break the app
            pass


def install(log_dir: Path, retention_days: int = 30) -> None:
    """Point the buffer at ``log_dir`` and attach it to the root logger.

    Idempotent. Sets the root level to INFO so module ``log.info`` lines are
    captured, adds a BufferHandler (→ daily files) and a stderr StreamHandler:
    once the root logger has ANY handler, Python's last-resort WARNING+ printer
    steps aside, so without our own stream handler app warnings would vanish
    from the terminal (and now INFO lifecycle lines show there too). uvicorn's
    own loggers don't propagate to root, so nothing double-prints.
    """
    global _log_dir, _retention_days
    _log_dir = Path(log_dir)
    _retention_days = retention_days
    _log_dir.mkdir(parents=True, exist_ok=True)
    _prune_old()

    root = logging.getLogger()
    if any(isinstance(h, BufferHandler) for h in root.handlers):
        return
    formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
    buffer_handler = BufferHandler()
    buffer_handler.setFormatter(formatter)
    buffer_handler.setLevel(logging.INFO)
    root.addHandler(buffer_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)
    root.addHandler(stream_handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
