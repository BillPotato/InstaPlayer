"""Pydantic response/request models for the API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    isrc: str | None
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int | None
    disc_number: int | None
    duration_ms: int | None
    file_size: int
    mime: str
    quality: str | None
    source_service: str | None
    has_art: bool = False
    has_lyrics: bool = False
    updated_at: datetime


class PlaylistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    spotify_url: str | None
    track_count: int = 0
    updated_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    spotify_url: str
    preferred_source: str | None
    status: str
    total: int
    completed: int
    current: str | None
    error: str | None
    playlist_id: str | None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    spotifyUrl: str
    preferredSource: str | None = None
