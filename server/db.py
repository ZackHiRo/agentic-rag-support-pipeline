"""Database engine and session helpers. SQLite by default, Postgres via DATABASE_URL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .settings import settings


_clock: ContextVar[datetime | None] = ContextVar("clock", default=None)


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp (SQLModel stores it as UTC and returns it aware)."""
    return _clock.get() or datetime.now(UTC)


@contextmanager
def frozen_clock(at: datetime) -> Iterator[None]:
    """Make utcnow() return `at` in this context. Used by the demo seeder to
    replay realistic ticket histories through the normal domain logic."""
    token = _clock.set(at)
    try:
        yield
    finally:
        _clock.reset(token)


def _make_engine(url: str):
    if url.startswith("sqlite"):
        db_path = url.split("sqlite:///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            # WAL lets the AI worker threads write while requests read.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(settings.database_url)


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
