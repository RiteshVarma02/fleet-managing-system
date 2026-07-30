"""Engine / session factory / FastAPI dependency.

Session rules used across the codebase:
* Request-scoped sessions come from `get_db` (FastAPI dependency).
* Background threads MUST use `session_scope()` — never share a session
  across threads, and never keep one open for the lifetime of a ROS node.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base  # re-exported for Alembic

__all__ = ["Base", "engine", "SessionLocal", "get_db", "session_scope", "init_db"]


def _build_engine() -> Engine:
    url = settings.database_url
    if url.startswith("sqlite"):
        # SQLite needs check_same_thread=False because ROS callbacks and task
        # runners touch the DB from worker threads.
        return create_engine(
            url,
            echo=settings.db_echo,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(
        url,
        echo=settings.db_echo,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


engine = _build_engine()

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional scope for background threads and startup hooks."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Dev/test convenience. Production should use `alembic upgrade head`."""
    from app.db import models  # noqa: F401  (ensure models are imported)

    Base.metadata.create_all(bind=engine)
