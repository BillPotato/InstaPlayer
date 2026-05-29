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

    # How long a finished job's files are kept for the device to fetch before
    # the reaper deletes them. The backend stores nothing permanently.
    job_retention_hours: float = 6.0

    @property
    def jobs_dir(self) -> Path:
        # Temporary per-job storage: SpotiFLAC downloads here, the device pulls
        # the files, then the dir is deleted. This is the only place audio ever
        # lives on the backend, and only transiently.
        return self.data_dir / "jobs"

    @property
    def database_url(self) -> str:
        # Only holds transient job status rows — never songs.
        return f"sqlite:///{(self.data_dir / 'jobs.db').resolve()}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    return settings
