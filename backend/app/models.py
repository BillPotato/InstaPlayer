"""ORM models: tracks, playlists, the join table, and download jobs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    # ISRC is the de-dupe key; nullable because some sources omit it.
    isrc: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    title: Mapped[str] = mapped_column(String, default="")
    artist: Mapped[str] = mapped_column(String, default="")
    album: Mapped[str] = mapped_column(String, default="")
    album_artist: Mapped[str] = mapped_column(String, default="")
    track_number: Mapped[int | None] = mapped_column(Integer)
    disc_number: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    file_path: Mapped[str] = mapped_column(String)  # absolute path on backend disk
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String, default="audio/flac")
    quality: Mapped[str | None] = mapped_column(String)
    source_service: Mapped[str | None] = mapped_column(String)

    art_path: Mapped[str | None] = mapped_column(String)
    lyrics: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    playlist_links: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    spotify_url: Mapped[str | None] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, default="Imported playlist")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    track_links: Mapped[list["PlaylistTrack"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistTrack.position",
    )


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    __table_args__ = (UniqueConstraint("playlist_id", "track_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id"), index=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    playlist: Mapped[Playlist] = relationship(back_populates="track_links")
    track: Mapped[Track] = relationship(back_populates="playlist_links")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    spotify_url: Mapped[str] = mapped_column(String)
    preferred_source: Mapped[str | None] = mapped_column(String)

    # queued | running | completed | failed
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    # Label of the track currently being fetched (for live progress).
    current: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(Text)
    playlist_id: Mapped[str | None] = mapped_column(ForeignKey("playlists.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
