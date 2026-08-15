"""Compatibility enums and lightweight model aliases.

This file preserves import paths from the previous SQLAlchemy code while the
Mongo migration is completed.
"""

from __future__ import annotations

from enum import Enum


class RobotStatusEnum(str, Enum):
    online = "online"
    offline = "offline"
    error = "error"
    busy = "busy"


class TaskStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    done = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Robot(dict):
    """Legacy placeholder type used for annotations only."""
