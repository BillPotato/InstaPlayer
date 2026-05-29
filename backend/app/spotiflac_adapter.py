"""Thin adapter around the SpotiFLAC module.

SpotiFLAC runs as a side effect: given a Spotify URL it downloads FLAC files
(with metadata + lyrics embedded) into ``output_dir`` and returns nothing useful.
We therefore treat it as a black box here and recover all metadata afterwards by
scanning the produced files (see ``ingest.py``).

For progress we parse the text SpotiFLAC prints/logs while running (it has no
callback API): the "Found N track(s)" line gives the total, and each
"Trying: <artist> — <title>" line gives the current track. Both stdout (plain
``print``) and stderr (logging) are teed so we catch either form. This is
best-effort — if the format changes, progress simply stays coarse, never crashes.
"""
from __future__ import annotations

import contextlib
import io
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable

ProgressCb = Callable[[dict[str, Any]], None]

_FOUND_RE = re.compile(r"Found\s+(\d+)\s+track", re.IGNORECASE)
_TRYING_RE = re.compile(r"Trying:\s*(.+?)\s*$")


class SpotiFlacError(RuntimeError):
    pass


class _ProgressTee(io.TextIOBase):
    """Wraps a real text stream: forwards writes through, parses progress lines."""

    def __init__(self, original: Any, on_line: Callable[[str], None]) -> None:
        self._original = original
        self._on_line = on_line
        self._buf = ""

    def write(self, s: str) -> int:  # type: ignore[override]
        if self._original is not None:
            self._original.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            with contextlib.suppress(Exception):
                self._on_line(line)
        return len(s)

    def flush(self) -> None:
        if self._original is not None:
            self._original.flush()


def _parse_line(line: str, cb: ProgressCb) -> None:
    found = _FOUND_RE.search(line)
    if found:
        cb({"total": int(found.group(1))})
    trying = _TRYING_RE.search(line)
    if trying:
        cb({"current": trying.group(1).strip()})


def run_spotiflac(
    url: str,
    output_dir: Path,
    services: list[str],
    quality: str = "LOSSLESS",
    qobuz_token: str | None = None,
    track_max_retries: int = 2,
    progress_cb: ProgressCb | None = None,
) -> None:
    """Download everything behind ``url`` into ``output_dir`` (blocking).

    Raises SpotiFlacError on import or runtime failure so callers can mark the
    job failed with a clear message.
    """
    try:
        from SpotiFLAC import SpotiFLAC  # imported lazily; heavy + optional at dev time
    except Exception as exc:  # pragma: no cover - depends on runtime env
        raise SpotiFlacError(f"SpotiFLAC is not importable: {exc}") from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    def _download() -> None:
        SpotiFLAC(
            url=url,
            output_dir=str(output_dir),
            services=services,
            quality=quality,
            allow_fallback=True,  # fall through the source list on per-track failure
            track_max_retries=track_max_retries,
            embed_lyrics=True,
            enrich_metadata=True,
            qobuz_token=qobuz_token,
            log_level=logging.INFO,
        )

    try:
        if progress_cb is None:
            _download()
        else:
            on_line = lambda line: _parse_line(line, progress_cb)  # noqa: E731
            # Tee both streams: "Found N" is printed to stdout, "Trying:" is
            # logged to stderr. Single-user backend → global redirect is fine.
            with contextlib.redirect_stdout(_ProgressTee(sys.stdout, on_line)), \
                    contextlib.redirect_stderr(_ProgressTee(sys.stderr, on_line)):
                _download()
    except Exception as exc:
        raise SpotiFlacError(f"SpotiFLAC download failed: {exc}") from exc
