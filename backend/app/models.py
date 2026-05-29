"""ORM models. The backend persists nothing but transient download jobs —
songs live only on the user's device, so there are no track/playlist tables."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
