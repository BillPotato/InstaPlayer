"""Thin adapter around an optional Spooty instance, used as a fallback when
SpotiFLAC returns zero tracks (e.g. all of its proxy sources are down).

Spooty resolves track metadata from the Spotify API and fetches audio from
YouTube via yt-dlp+ffmpeg — a categorically lower-quality (lossy) source than
SpotiFLAC's lossless providers. We treat it strictly as a last resort.

Unlike SpotiFLAC (an in-process blocking call), Spooty is a separate stateful
HTTP service: it persists playlists/tracks in its own DB and on its own disk
until explicitly deleted. So this adapter must drive it through its REST API —
create a playlist, poll until every track reaches a terminal status, stream the
completed files into our job dir, and always clean up afterwards.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

ProgressCb = Callable[[dict[str, Any]], None]

# Mirrors Spooty's TrackStatusEnum (New=0, Searching=1, Queued=2, Downloading=3,
# Completed=4, Error=5). Exposed only as numbers over its REST API.
_STATUS_COMPLETED = 4
_STATUS_TERMINAL = 4  # >= this is Completed or Error — track is done either way

_POLL_INTERVAL = 3.0
_OVERALL_TIMEOUT = 60.0 * 30  # generous: yt-dlp search+download per track is slow

_ILLEGAL_CHARS_RE = re.compile(r'[/\\?%*:|"<>]')


class SpootyError(RuntimeError):
    pass


def _sanitize(name: str) -> str:
    return _ILLEGAL_CHARS_RE.sub("-", name)


def _find_playlist(client: httpx.Client, spotify_url: str) -> dict[str, Any]:
    resp = client.get("/api/playlist")
    resp.raise_for_status()
    matches = [p for p in resp.json() if p.get("spotifyUrl") == spotify_url]
    if not matches:
        raise SpootyError("Spooty did not register the playlist after creation")
    # Most recently created wins, in case a stale entry from a previous run lingers.
    return max(matches, key=lambda p: p.get("createdAt", 0))


def _wait_for_tracks(
    client: httpx.Client, playlist_id: int, progress_cb: ProgressCb | None
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + _OVERALL_TIMEOUT
    while True:
        resp = client.get(f"/api/track/playlist/{playlist_id}")
        resp.raise_for_status()
        tracks = resp.json()
        if tracks:
            pending = [t for t in tracks if t.get("status", 0) < _STATUS_TERMINAL]
            if progress_cb is not None:
                update: dict[str, Any] = {"total": len(tracks)}
                if pending:
                    update["current"] = f"{pending[0]['artist']} - {pending[0]['name']}"
                progress_cb(update)
            if not pending:
                return tracks
        if time.monotonic() > deadline:
            raise SpootyError("Timed out waiting for Spooty to finish downloading")
        time.sleep(_POLL_INTERVAL)


def _download_track(
    client: httpx.Client, track: dict[str, Any], dest_dir: Path, audio_format: str
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{track['index']:02d} - {_sanitize(track['artist'])} - {_sanitize(track['name'])}.{audio_format}"
    dest = dest_dir / name
    with client.stream("GET", f"/api/track/download/{track['id']}") as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)


def run_spooty(
    url: str,
    output_dir: Path,
    base_url: str,
    audio_format: str = "flac",
    progress_cb: ProgressCb | None = None,
) -> None:
    """Download everything behind ``url`` into ``output_dir`` via Spooty (blocking).

    Raises SpootyError on any failure so callers can treat it uniformly with
    SpotiFlacError. Always deletes the playlist from Spooty afterwards — it has
    no retention policy of its own.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    playlist_id: int | None = None
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            try:
                resp = client.post("/api/playlist", json={"spotifyUrl": url})
                resp.raise_for_status()

                playlist = _find_playlist(client, url)
                playlist_id = playlist["id"]
                if playlist.get("error"):
                    raise SpootyError(f"Spooty could not resolve the playlist: {playlist['error']}")

                playlist_name = playlist.get("name") or "Imported playlist"
                tracks = _wait_for_tracks(client, playlist_id, progress_cb)

                completed = [t for t in tracks if t.get("status") == _STATUS_COMPLETED]
                if not completed:
                    raise SpootyError("Spooty could not download any tracks")

                dest_dir = output_dir / _sanitize(playlist_name)
                for track in completed:
                    _download_track(client, track, dest_dir, audio_format)
            finally:
                if playlist_id is not None:
                    try:
                        client.delete(f"/api/playlist/{playlist_id}")
                    except httpx.HTTPError:
                        log.warning("Failed to delete Spooty playlist %s during cleanup", playlist_id)
    except SpootyError:
        raise
    except httpx.HTTPError as exc:
        raise SpootyError(f"Spooty request failed: {exc}") from exc
    except Exception as exc:
        raise SpootyError(f"Spooty download failed: {exc}") from exc
