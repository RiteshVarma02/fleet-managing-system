"""Shared document enums and (de)serialisation helpers for MongoDB."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional

from bson import ObjectId
from bson.errors import InvalidId


class Role(str, Enum):
    """developer > admin > operator. Every role can do what the roles below it can."""

    developer = "developer"
    admin = "admin"
    operator = "operator"


ROLE_RANK = {Role.operator.value: 1, Role.admin.value: 2, Role.developer.value: 3}


def role_rank(role: str) -> int:
    """0 for unknown/retired roles (e.g. the old read-only `viewer`): no access."""
    return ROLE_RANK.get(str(role), 0)


class RobotStatus(str, Enum):
    """Derived by `services.robot_status.derive_status` — never set by hand."""

    offline = "offline"
    idle = "idle"
    moving = "moving"
    paused = "paused"
    awaiting_approval = "awaiting_approval"
    stop_active = "stop_active"
    e_stopped = "e_stopped"
    error = "error"


class RegistrationStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    awaiting_approval = "awaiting_approval"
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
