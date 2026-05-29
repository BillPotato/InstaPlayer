"""Scan FLAC files produced by SpotiFLAC and upsert them into the library DB.

All metadata (tags, album art, lyrics) is read back out of the FLAC files with
mutagen, so we never depend on SpotiFLAC returning structured data.
"""
from __future__ import annotations

import logging
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.flac import FLAC
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Playlist, PlaylistTrack, Track, _uuid

log = logging.getLogger(__name__)


@dataclass
class FlacMeta:
    src_path: Path
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
    # Tags like "3/12" → 3
    head = value.split("/")[0].strip()
    return int(head) if head.isdigit() else None


def scan_flacs(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.rglob("*.flac") if p.is_file())


def parse_flac(path: Path) -> FlacMeta:
    audio = FLAC(str(path))
    meta = FlacMeta(
        src_path=path,
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


def _safe_name(name: str) -> str:
    """Return a filesystem-safe directory name that preserves Unicode text.

    Strategy:
    1. NFKC normalise (collapse compatibility variants).
    2. Strip characters that are problematic on Windows/Linux (control chars,
       path separators, null bytes, leading/trailing dots and spaces).
    3. Truncate to 80 chars.
    4. Fall back to "untitled" if nothing is left.

    The file itself is always named by track ID so collisions are impossible
    even if two albums produce the same sanitised folder name.
    """
    # NFKC normalisation keeps CJK, Arabic, Cyrillic, etc. intact.
    name = unicodedata.normalize("NFKC", name)
    # Remove characters that are banned or cause trouble on any OS.
    banned = set('\x00/\\:*?"<>|\t\n\r\x0b\x0c')
    name = "".join(c for c in name if c not in banned and not unicodedata.category(c).startswith("C"))
    name = name.strip(". ")
    return name[:80] or "untitled"


def ingest_track(session: Session, meta: FlacMeta, settings: Settings) -> Track:
    """Upsert a single track keyed on ISRC, moving the file into the library."""
    existing: Track | None = None
    if meta.isrc:
        existing = session.scalar(select(Track).where(Track.isrc == meta.isrc))

    if existing:
        # Already have this recording; drop the freshly downloaded duplicate.
        meta.src_path.unlink(missing_ok=True)
        return existing

    track = Track(
        id=_uuid(),  # assign up front so we can build the file path before insert
        isrc=meta.isrc,
        title=meta.title,
        artist=meta.artist,
        album=meta.album,
        album_artist=meta.album_artist or meta.artist,
        track_number=meta.track_number,
        disc_number=meta.disc_number,
        duration_ms=meta.duration_ms,
        quality=meta.quality,
        lyrics=meta.lyrics,
    )

    album_dir = settings.music_dir / _safe_name(meta.album or "singles")
    album_dir.mkdir(parents=True, exist_ok=True)
    # File is always named by unique track ID, so no collision is possible.
    dest = album_dir / f"{track.id}.flac"
    shutil.move(str(meta.src_path), str(dest))
    track.file_path = str(dest)
    track.file_size = dest.stat().st_size

    if meta.art_bytes:
        ext = "png" if (meta.art_mime or "").endswith("png") else "jpg"
        art_path = album_dir / f"{track.id}.{ext}"
        art_path.write_bytes(meta.art_bytes)
        track.art_path = str(art_path)

    session.add(track)
    session.flush()
    return track


def link_to_playlist(session: Session, playlist: Playlist, track: Track, position: int) -> None:
    exists = session.scalar(
        select(PlaylistTrack).where(
            PlaylistTrack.playlist_id == playlist.id,
            PlaylistTrack.track_id == track.id,
        )
    )
    if not exists:
        session.add(
            PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position)
        )
        session.flush()  # so a repeated call in the same session sees this link


def ingest_directory(
    session: Session, directory: Path, playlist: Playlist, settings: Settings
) -> int:
    """Ingest every FLAC under ``directory`` into the library + playlist.

    Each file is wrapped in its own try/except: a corrupt or unreadable FLAC
    is logged and skipped so that one bad file can't abort the whole job.
    Returns the number of files successfully ingested.
    """
    files = scan_flacs(directory)
    ingested = 0
    for position, path in enumerate(files):
        try:
            meta = parse_flac(path)
            track = ingest_track(session, meta, settings)
            link_to_playlist(session, playlist, track, position)
            session.commit()
            ingested += 1
        except Exception:
            log.exception("Failed to ingest %s — skipping", path)
            try:
                session.rollback()
            except Exception:
                pass
    return ingested
