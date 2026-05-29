"""SQLAlchemy engine, session factory and schema creation."""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    # WAL journal (set in init_db) allows concurrent reads during writes.
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _enable_wal() -> None:
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))


def _migrate() -> None:
    """Add any columns that exist in the ORM models but not yet in the DB.

    ``create_all`` only creates missing *tables*; we use ``PRAGMA table_info``
    to detect and ADD missing columns so existing databases survive upgrades
    without a full Alembic setup.
    """
    # Map table_name → {col_name} for columns that exist in the DB right now.
    existing: dict[str, set[str]] = {}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = conn.execute(text(f"PRAGMA table_info({table.name})")).fetchall()
            existing[table.name] = {row[1] for row in rows}

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            db_cols = existing.get(table.name, set())
            for col in table.columns:
                if col.name not in db_cols:
                    # Build the simplest possible column definition; SQLite
                    # ALTER TABLE only supports adding nullable columns.
                    col_type = col.type.compile(dialect=engine.dialect)
                    default_clause = ""
                    if col.default is not None and col.default.is_scalar:
                        val = col.default.arg
                        if isinstance(val, str):
                            val = f"'{val}'"
                        default_clause = f" DEFAULT {val}"
                    ddl = (
                        f"ALTER TABLE {table.name} "
                        f"ADD COLUMN {col.name} {col_type}{default_clause}"
                    )
                    log.info("Migrating: %s", ddl)
                    conn.execute(text(ddl))


def init_db() -> None:
    # Import models so they register with Base before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate()
    _enable_wal()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
