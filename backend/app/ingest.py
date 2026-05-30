"""Read metadata out of the FLAC files SpotiFLAC produced and build a per-job
manifest the device can use to pull everything down.

The backend stores nothing permanently: it parses tags with mutagen, writes an
album-art sidecar next to each track, and emits a ``manifest.json`` describing
the job. The device downloads the files + manifest, then the job dir is deleted.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.flac import FLAC

log = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
ART_DIRNAME = "art"

# Serialises manifest read-modify-write so the watcher and the final pass can't
# corrupt the file or double-append when they overlap.
_manifest_lock = threading.Lock()


@dataclass
class FlacMeta:
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    track_number: int | None = None
    disc_number: int | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    quality: str | None = None
    lyrics: str | None = None
    art_bytes: bytes | None = field(default=None, repr=False)
    art_mime: str | None = None


def _first(tags: FLAC, *keys: str) -> str | None:
    for key in keys:
        value = tags.get(key)
        if value:
            return str(value[0]).strip()
    return None


def _as_int(value: str | None) -> int | None:
    if not value:
        return None
    head = value.split("/")[0].strip()  # "3/12" → 3
    return int(head) if head.isdigit() else None


def scan_flacs(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.rglob("*.flac") if p.is_file())


def parse_flac(path: Path) -> FlacMeta:
    audio = FLAC(str(path))
    meta = FlacMeta(
        title=_first(audio, "title") or path.stem,
        artist=_first(audio, "artist") or "",
        album=_first(audio, "album") or "",
        album_artist=_first(audio, "albumartist", "album artist") or "",
        track_number=_as_int(_first(audio, "tracknumber")),
        disc_number=_as_int(_first(audio, "discnumber")),
        isrc=_first(audio, "isrc"),
        quality=_first(audio, "quality"),
        lyrics=_first(audio, "lyrics", "unsyncedlyrics", "syncedlyrics"),
    )
    if audio.info and audio.info.length:
        meta.duration_ms = int(audio.info.length * 1000)
    if audio.pictures:
        pic = audio.pictures[0]
        meta.art_bytes = pic.data
        meta.art_mime = pic.mime or "image/jpeg"
    return meta


def _playlist_name(job_dir: Path, files: list[Path]) -> str:
    if files:
        rel = files[0].relative_to(job_dir)
        if len(rel.parts) > 1:
            return rel.parts[0]  # SpotiFLAC writes an album/playlist sub-folder
    return "Imported playlist"


def _track_entry(job_dir: Path, path: Path, n: int) -> dict | None:
    """Parse one FLAC into a manifest entry with index ``n``, writing its art
    sidecar. Returns None (and logs) if the file can't be read — e.g. it's still
    being written — so the caller can retry it on a later pass."""
    try:
        meta = parse_flac(path)
    except Exception:
        log.warning("Skipping unreadable %s (may still be downloading)", path)
        return None

    art_file: str | None = None
    has_art = False
    if meta.art_bytes:
        art_dir = job_dir / ART_DIRNAME
        art_dir.mkdir(parents=True, exist_ok=True)
        ext = "png" if (meta.art_mime or "").endswith("png") else "jpg"
        art_path = art_dir / f"{n}.{ext}"
        art_path.write_bytes(meta.art_bytes)
        art_file = str(art_path.relative_to(job_dir).as_posix())
        has_art = True

    return {
        "n": n,
        "file": str(path.relative_to(job_dir).as_posix()),
        "title": meta.title,
        "artist": meta.artist,
        "album": meta.album,
        "albumArtist": meta.album_artist or meta.artist,
        "trackNumber": meta.track_number,
        "durationMs": meta.duration_ms,
        "isrc": meta.isrc,
        "quality": meta.quality,
        "mime": "audio/flac",
        "fileSize": path.stat().st_size,
        "hasArt": has_art,
        "artFile": art_file,
        "lyrics": meta.lyrics,
    }


def update_manifest(job_dir: Path, spotify_url: str | None = None) -> dict:
    """Append any FLACs not yet in the manifest and persist it.

    Append-only with stable ``n`` indices: a track's index never changes once
    assigned, so the device can safely fetch ``/files/{n}`` while more tracks
    are still arriving. Safe to call repeatedly during a download (idempotent
    per file) and thread-safe. Unreadable/partial files are skipped and picked
    up on a later pass. Returns the current manifest.
    """
    with _manifest_lock:
        files = scan_flacs(job_dir)
        manifest = load_manifest(job_dir) or {
            "name": _playlist_name(job_dir, files),
            "spotifyUrl": spotify_url,
            "trackCount": 0,
            "tracks": [],
        }
        known = {t["file"] for t in manifest["tracks"]}
        changed = False
        for path in files:
            rel = str(path.relative_to(job_dir).as_posix())
            if rel in known:
                continue
            entry = _track_entry(job_dir, path, len(manifest["tracks"]))
            if entry is None:
                continue
            manifest["tracks"].append(entry)
            known.add(rel)
            changed = True

        if manifest.get("spotifyUrl") is None and spotify_url is not None:
            manifest["spotifyUrl"] = spotify_url
            changed = True
        if not manifest["name"] or manifest["name"] == "Imported playlist":
            name = _playlist_name(job_dir, files)
            if name != manifest["name"]:
                manifest["name"] = name
                changed = True

        manifest["trackCount"] = len(manifest["tracks"])
        if changed or not (job_dir / MANIFEST_NAME).exists():
            (job_dir / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        return manifest


# Backwards-compatible name: a one-shot build is just an update from empty.
def build_manifest(job_dir: Path, spotify_url: str | None = None) -> dict:
    return update_manifest(job_dir, spotify_url)


def load_manifest(job_dir: Path) -> dict | None:
    path = job_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Corrupt manifest in %s", job_dir)
        return None
