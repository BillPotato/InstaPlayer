"""Thin adapter around the vendored SpotiFLAC Go engine (``spotiflac-dl``).

The engine is a self-contained static binary built from the upstream SpotiFLAC
``backend`` package (see ``backend/spotiflac-go/``). We invoke it as a
subprocess: given a Spotify URL it downloads title-tagged FLAC files (metadata +
cover + lyrics embedded) into ``output_dir`` and prints progress. We treat it as
a black box and recover all metadata afterwards by scanning the produced files
(see ``ingest.py``) — the filesystem contract is unchanged from the old pip
package, so ``jobs.py`` and ``ingest.py`` need no changes.

Progress comes from the per-track header the binary writes to stdout::

    Track [1/2] Bohemian Rhapsody — Queen

which carries both the total (``[N/M]``) and the current track. Parsing is
best-effort — if the format changes, progress simply stays coarse, never
crashes. The child's stderr is merged into stdout, and every line is echoed to
this process's stdout so the engine's output (progress, provider failures, the
final error) is visible in the server terminal — the app configures no logging
handlers, so routing it through ``logging`` at INFO would be swallowed.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from . import logbuffer

ProgressCb = Callable[[dict[str, Any]], None]

#: Name of the engine binary on PATH. Overridable via ``SPOTIFLAC_DL_BIN``.
BINARY_NAME = "spotiflac-dl"

# Per-track header: "Track [N/M] <title> — <artists>". Anchored on "Track [".
_TRACK_HDR_RE = re.compile(r"Track\s*\[(\d+)\s*/\s*(\d+)\]\s*(.+?)\s*$")

# Community rate-limit line, e.g. "... on scheduled cooldown (503), back in ~4534s".
_COOLDOWN_RE = re.compile(r"back in ~(\d+)s")


class SpotiFlacError(RuntimeError):
    """A run failed. ``cooldown_seconds`` is set when the failure was (only) a
    community-endpoint cooldown, so callers can retry once it expires."""

    cooldown_seconds: int | None = None


def resolve_binary() -> str | None:
    """Absolute path to the ``spotiflac-dl`` binary, or ``None`` if unavailable.

    Honours the ``SPOTIFLAC_DL_BIN`` env override (must point at an executable
    file); otherwise searches ``PATH``.
    """
    override = os.environ.get("SPOTIFLAC_DL_BIN")
    if override:
        path = Path(override)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return None
    return shutil.which(BINARY_NAME)


def binary_version() -> str | None:
    """Version string reported by ``spotiflac-dl --version``, or ``None``."""
    binary = resolve_binary()
    if binary is None:
        return None
    try:
        out = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    version = (out.stdout or out.stderr or "").strip()
    return version or None


def _clean_current(tail: str) -> str:
    """Reduce a header tail ``<title> — <artists>`` (optionally with a trailing
    ``(<album>)``) to ``<title> — <artists>``. Splits on the em dash so a title
    or artist containing ``(...)`` survives, then drops any trailing album.
    """
    tail = tail.strip()
    if " — " in tail:
        title, rest = tail.split(" — ", 1)
        artists = rest.split(" (", 1)[0]
        return f"{title.strip()} — {artists.strip()}"
    return tail


def _parse_line(line: str, cb: ProgressCb) -> None:
    header = _TRACK_HDR_RE.search(line)
    if header:
        # Authoritative: total from [N/M] and the current track in one update.
        cb({"total": int(header.group(2)), "current": _clean_current(header.group(3))})


def engine_home() -> Path | None:
    """Directory the engine uses as ``$HOME``, from ``SPOTIFLAC_ENGINE_HOME``.

    Since v7.2.0 the community endpoints need an HMAC session stored at
    ``$HOME/.spotiflac/community_session.json``. The headless engine can't
    create one (the one-time verification needs a browser), so the admin copies
    the file the official desktop app created after its captcha. Pointing the
    engine's HOME at a dir under the mounted data volume (the Docker image sets
    ``SPOTIFLAC_ENGINE_HOME=/data/engine-home``) makes that file easy to drop
    in from the host and persistent across restarts. Unset → engine inherits
    our own HOME (fine for local dev).
    """
    home = os.environ.get("SPOTIFLAC_ENGINE_HOME")
    return Path(home) if home else None


def _engine_env() -> dict | None:
    home = engine_home()
    if home is None:
        return None  # inherit our environment untouched
    with contextlib.suppress(Exception):
        home.mkdir(parents=True, exist_ok=True)
    # HOME for Linux (os.UserHomeDir), USERPROFILE for Windows dev runs.
    return {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}


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

    Raises ``SpotiFlacError`` when the binary is missing or the run fails so
    callers can mark the job failed / the probe unhealthy with a clear message.
    """
    binary = resolve_binary()
    if binary is None:
        raise SpotiFlacError(
            f"{BINARY_NAME} binary not found (set SPOTIFLAC_DL_BIN or add it to PATH)"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        binary,
        "--url", url,
        "--out", str(output_dir),
        "--services", ",".join(services),
        "--quality", quality,
        "--max-retries", str(max(0, track_max_retries)),
    ]
    if qobuz_token:
        cmd += ["--qobuz-token", qobuz_token]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge so failures/errors flow through too
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=_engine_env(),  # community session lives under the engine HOME
        )
    except OSError as exc:
        raise SpotiFlacError(f"failed to launch {BINARY_NAME}: {exc}") from exc

    tail: list[str] = []
    cooldown_seconds: int | None = None
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            print(f"[spotiflac-dl] {line}", file=sys.stdout, flush=True)
            logbuffer.append(f"[spotiflac-dl] {line}")  # /logs (admin dashboard)
            tail.append(line)
            if len(tail) > 20:
                del tail[0]
            m = _COOLDOWN_RE.search(line)
            if m:
                secs = int(m.group(1))
                # Earliest a service recovers is the shortest cooldown seen.
                cooldown_seconds = secs if cooldown_seconds is None else min(cooldown_seconds, secs)
            if progress_cb is not None:
                with contextlib.suppress(Exception):
                    _parse_line(line, progress_cb)
        returncode = proc.wait()
    except Exception as exc:  # pragma: no cover - defensive (I/O on the pipe)
        proc.kill()
        raise SpotiFlacError(f"SpotiFLAC download failed: {exc}") from exc

    if returncode != 0:
        detail = tail[-1] if tail else f"exit code {returncode}"
        err = SpotiFlacError(f"SpotiFLAC download failed (exit {returncode}): {detail}")
        err.cooldown_seconds = cooldown_seconds
        raise err
