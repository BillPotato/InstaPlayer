"""Thin adapter around the SpotiFLAC module.

SpotiFLAC runs as a side effect: given a Spotify URL it downloads FLAC files
(with metadata + lyrics embedded) into ``output_dir`` and returns nothing useful.
We therefore treat it as a black box here and recover all metadata afterwards by
scanning the produced files (see ``ingest.py``).

For progress we parse the text SpotiFLAC prints/logs while running (it has no
callback API). The authoritative signal is the per-track header SpotiFLAC writes
to stderr via ``tqdm.write`` for each track, e.g.::

    Track [1/2] Bohemian Rhapsody — Queen (A Night at the Opera)

which carries both the total (``[N/M]``) and the current track. We still honour
the older "Found N track(s)" (total) and "Trying: <artist> — <title>" (current)
lines as fallbacks for older SpotiFLAC versions. Note the "Trying:" lines come
from ``logging`` whose handler is bound to the real stderr and so bypass our
``redirect_stderr`` tee — the ``print``/``tqdm.write`` header does not, which is
why the header is the reliable source. Both stdout and stderr are teed so we
catch either form. This is best-effort — if the format changes, progress simply
stays coarse, never crashes.
"""
from __future__ import annotations

import contextlib
import io
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

ProgressCb = Callable[[dict[str, Any]], None]

_FOUND_RE = re.compile(r"Found\s+(\d+)\s+track", re.IGNORECASE)
_TRYING_RE = re.compile(r"Trying:\s*(.+?)\s*$")
# Per-track header: "Track [N/M] <title> — <artists> (<album>)". Anchored on
# "Track [" so the tqdm progress bars ("Track: <name>  : 12%|…") never match.
_TRACK_HDR_RE = re.compile(r"Track\s*\[(\d+)\s*/\s*(\d+)\]\s*(.+?)\s*$")


def _clean_current(tail: str) -> str:
    """Reduce a header tail ``<title> — <artists> (<album>)`` to
    ``<title> — <artists>``. Splits on the em dash so a title or artist that
    itself contains ``(...)`` survives, then drops the album, which is always the
    trailing parenthetical. Album truncation can leave an unbalanced ``(`` in the
    line, so we cut on the first ``" ("`` after the dash rather than match parens.
    """
    tail = tail.strip()
    if " — " in tail:
        title, rest = tail.split(" — ", 1)
        artists = rest.split(" (", 1)[0]
        return f"{title.strip()} — {artists.strip()}"
    return tail


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
    header = _TRACK_HDR_RE.search(line)
    if header:
        # Authoritative: total from [N/M] and the current track in one update.
        cb({"total": int(header.group(2)), "current": _clean_current(header.group(3))})
        return
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

    def _download(include_retries: bool = True) -> None:
        kwargs: dict[str, Any] = dict(
            url=url,
            output_dir=str(output_dir),
            services=services,
            quality=quality,
            allow_fallback=True,
            embed_lyrics=True,
            enrich_metadata=True,
            qobuz_token=qobuz_token,
            log_level=logging.INFO,
        )
        if include_retries:
            kwargs["track_max_retries"] = track_max_retries
        SpotiFLAC(**kwargs)

    def _run_download() -> None:
        try:
            _download(include_retries=True)
        except TypeError as te:
            # Older SpotiFLAC versions don't accept track_max_retries.
            if "track_max_retries" in str(te):
                log.warning(
                    "SpotiFLAC: track_max_retries not supported in this version, retrying without it"
                )
                _download(include_retries=False)
            else:
                raise

    try:
        if progress_cb is None:
            _run_download()
        else:
            on_line = lambda line: _parse_line(line, progress_cb)  # noqa: E731
            # Tee both streams: "Found N" is printed to stdout, "Trying:" is
            # logged to stderr. Single-user backend → global redirect is fine.
            with contextlib.redirect_stdout(_ProgressTee(sys.stdout, on_line)), \
                    contextlib.redirect_stderr(_ProgressTee(sys.stderr, on_line)):
                _run_download()
    except Exception as exc:
        raise SpotiFlacError(f"SpotiFLAC download failed: {exc}") from exc
