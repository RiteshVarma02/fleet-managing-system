"""Shared document enums and (de)serialisation helpers for MongoDB."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional

from bson import ObjectId
from bson.errors import InvalidId


class Role(str, Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class RobotStatus(str, Enum):
    online = "online"
    offline = "offline"
    error = "error"
    busy = "busy"


class RegistrationStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_TASK_STATUSES = {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalise a datetime to aware UTC so Mongo stores a comparable BSON date.

    Naive values (e.g. from client payloads) are assumed to already be UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_object_id(value: Any) -> Optional[ObjectId]:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


def serialize(document: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert a Mongo document into a JSON-friendly dict (`_id` -> `id`)."""
    if document is None:
        return None
    out: Dict[str, Any] = {}
    for key, value in document.items():
        if key == "_id":
            out["id"] = str(value)
        elif isinstance(value, ObjectId):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def normalize_mac(mac: Optional[str]) -> Optional[str]:
    if not mac:
        return None
    return mac.strip().upper() or None
