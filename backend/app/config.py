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

    # Source priority handed to the engine. First that succeeds wins; each also
    # falls back to its community source internally. Only qobuz/tidal/amazon are
    # download providers upstream (deezer is metadata/art only — no downloader),
    # so it's dropped from this list. Override via DEFAULT_SERVICES in .env.
    default_services: list[str] = ["qobuz", "tidal", "amazon"]

    # Quality profile: "LOSSLESS" (16-bit) or "HI_RES" (24-bit). The engine maps
    # this onto each provider's own quality code.
    quality: str = "LOSSLESS"

    # Optional custom Qobuz API base URL (https://...) passed to the engine as
    # --qobuz-token; leave unset to use the built-in community endpoint.
    qobuz_token: str | None = None

    # How many times the engine retries a community-endpoint request on transient
    # errors (429/502/504) before giving up, with backoff between tries — the
    # "waiting Ns before retry (i/N)" lines. 0 = a single attempt, no retries.
    # Lower it to fail faster when the community servers are flaky; 6 is the
    # engine's own default. Override via TRACK_MAX_RETRIES.
    track_max_retries: int = 6

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

    # Track used by POST /downloader/probe to verify SpotiFLAC can actually
    # download (its upstream resolver services break regularly). Any single
    # Spotify track URL that exists on the configured services works.
    probe_spotify_url: str = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"

    # Hard cap on a probe run. One track normally lands well inside this.
    probe_timeout_seconds: float = 240.0

    # Run the deep probe automatically every N minutes so clients get an
    # instant, recent answer instead of waiting for a live download.
    # 0 disables the periodic probe. Note each probe downloads one track.
    probe_interval_minutes: float = 60.0

    # How many days of daily log files (data/logs/YYYY-MM-DD.jsonl) to keep;
    # older ones are pruned on startup. 0 = keep forever. Override via
    # LOG_RETENTION_DAYS.
    log_retention_days: int = 30

    @property
    def logs_dir(self) -> Path:
        # Per-day log files for the admin dashboard's calendar view.
        return self.data_dir / "logs"

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
