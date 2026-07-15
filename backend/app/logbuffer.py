"""In-memory log ring buffer feeding the /logs endpoint (admin dashboard).

Single process, no persistence by design — the dashboard only needs a live
tail. Two sources feed it:

- a ``logging.Handler`` on the root logger (job/probe/ingest lifecycle lines
  that previously went nowhere because the app configures no handlers), and
- explicit ``append()`` calls for engine output (``spotiflac_adapter`` streams
  the ``spotiflac-dl`` subprocess's lines from an executor thread).

Thread-safety: appenders include executor threads. ``deque.append`` with a
maxlen is atomic under the GIL, ``list(_buf)`` takes an atomic snapshot, and
``next()`` on an ``itertools.count`` is atomic in CPython — so no lock is
needed here.
"""
from __future__ import annotations

import collections
import itertools
import logging
from datetime import datetime, timezone

_buf: collections.deque = collections.deque(maxlen=1000)
_seq = itertools.count(1)


def append(line: str) -> None:
    """Add one line to the buffer (safe from any thread)."""
    _buf.append({
        "seq": next(_seq),
        "ts": datetime.now(timezone.utc).isoformat(),
        "line": line,
    })


def since(after: int = 0, limit: int = 500) -> list[dict]:
    """Entries with seq > ``after``, oldest first, capped at ``limit``."""
    entries = [e for e in list(_buf) if e["seq"] > after]
    return entries[-limit:] if limit > 0 else entries


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            append(self.format(record))
        except Exception:  # pragma: no cover - never let logging break the app
            pass


def install() -> None:
    """Attach the buffer to the root logger (idempotent).

    Sets the root level to INFO so module ``log.info`` lines are captured.
    Also adds a stderr StreamHandler: once the root logger has ANY handler,
    Python's last-resort handler (which used to print WARNING+ to the
    terminal) steps aside — without our own stream handler, app warnings
    would vanish from the terminal. As a bonus the terminal now shows INFO
    lifecycle lines too. uvicorn's own loggers have their own handlers and
    don't propagate here, so nothing double-prints.
    """
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
