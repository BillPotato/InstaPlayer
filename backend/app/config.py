"""Application configuration, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Bearer token the client must send. MUST be overridden in production.
    api_key: str = "change-me-in-.env"

    # Where FLAC files, album art and the SQLite DB live.
    data_dir: Path = Path("./data")

    # Source priority handed to SpotiFLAC. First available wins.
    default_services: list[str] = ["tidal", "qobuz", "amazon", "deezer"]

    # SpotiFLAC quality string ("LOSSLESS", "HI_RES", ...).
    quality: str = "LOSSLESS"

    # Optional Qobuz token to unlock hi-res via SpotiFLAC.
    qobuz_token: str | None = None

    # Per-track download retries before giving up (transient source failures).
    track_max_retries: int = 2

    @property
    def music_dir(self) -> Path:
        return self.data_dir / "music"

    @property
    def jobs_dir(self) -> Path:
        # Scratch space where each job downloads before ingestion.
        return self.data_dir / "jobs"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'library.db').resolve()}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.music_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings
