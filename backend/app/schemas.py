"""Pydantic request/response models for the API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    spotify_url: str
    preferred_source: str | None
    quality: str | None = None
    status: str
    total: int
    completed: int
    current: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    spotifyUrl: str
    preferredSource: str | None = None
    # Optional per-job quality; omitted → server default (Settings.quality).
    quality: str | None = None

    @field_validator("spotifyUrl")
    @classmethod
    def validate_spotify_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("spotifyUrl must not be empty")
        if "spotify.com/" not in v and not v.startswith("spotify:"):
            raise ValueError(
                "spotifyUrl must be a Spotify URL (https://open.spotify.com/...) "
                "or Spotify URI (spotify:...)"
            )
        return v

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().upper()
        if v not in {"LOSSLESS", "HI_RES"}:
            raise ValueError("quality must be LOSSLESS or HI_RES")
        return v


class ManifestTrack(BaseModel):
    n: int
    title: str
    artist: str
    album: str
    albumArtist: str
    trackNumber: int | None = None
    durationMs: int | None = None
    isrc: str | None = None
    quality: str | None = None
    mime: str = "audio/flac"
    fileSize: int = 0
    hasArt: bool = False
    lyrics: str | None = None


class Manifest(BaseModel):
    name: str
    spotifyUrl: str | None = None
    trackCount: int
    tracks: list[ManifestTrack]
