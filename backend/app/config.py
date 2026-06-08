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
    # Tidal is last: its proxy network is frequently down and wastes 3-4 min
    # per track when unreachable. Override via DEFAULT_SERVICES in .env.
    default_services: list[str] = ["deezer", "amazon", "qobuz", "tidal"]

    # SpotiFLAC quality string ("LOSSLESS", "HI_RES", ...).
    quality: str = "LOSSLESS"

    # Optional Qobuz token to unlock hi-res via SpotiFLAC.
    qobuz_token: str | None = None

    # Per-track download retries before giving up (transient source failures).
    # 1 = one retry (2 total attempts). Higher values cause more zarz.moe 429s
    # when the shared resolver is rate-limited. Override via TRACK_MAX_RETRIES.
    track_max_retries: int = 1

    # How long a finished job's files are kept for the device to fetch before
    # the reaper deletes them. The backend stores nothing permanently.
    job_retention_hours: float = 6.0

    # Base URL of an optional Spooty instance (https://github.com/Raiper34/spooty)
    # used as a fallback when SpotiFLAC returns zero tracks — e.g. its proxy
    # sources are all down. Spooty fetches lossy audio from YouTube, so it's a
    # last resort, not a replacement. Unset (default) = fallback disabled.
    # Override via SPOOTY_BASE_URL in .env, e.g. http://spooty:3000
    spooty_base_url: str | None = None

    # File extension Spooty is configured to produce (its FORMAT env var).
    # Must be "flac" — ingest.py only scans for *.flac files. Override only if
    # you change both this and Spooty's FORMAT together.
    spooty_format: str = "flac"

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
