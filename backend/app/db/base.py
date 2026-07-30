"""SQLAlchemy declarative base and shared column helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp.

    Always use this instead of `datetime.utcnow()` (which returns a naive
    value and silently breaks comparisons against tz-aware columns).
    """
    return datetime.now(timezone.utc)
