"""Mission (task) and pending-request schemas.

A mission is an ordered list of waypoint NAMES visited in sequence, repeated
`repeats` times, in one of two modes:

* ``continuous``  go from stop to stop without waiting.
* ``step``        ("move on click") wait for an operator to approve every move
                  after the first leg.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.db.documents import TaskStatus

Mode = Literal["continuous", "step"]


def _clean_stops(stops: List[str]) -> List[str]:
    cleaned = [str(s).strip() for s in stops]
    if not cleaned:
        raise ValueError("a mission needs at least one stop")
    if any(not s for s in cleaned):
        raise ValueError("stop names cannot be empty")
    if len(cleaned) > settings.max_task_stops:
        raise ValueError(f"a mission can have at most {settings.max_task_stops} stops")
    return cleaned


class _StopsMixin(BaseModel):
    stops: List[str] = Field(min_length=1, description="Ordered waypoint names")

    @field_validator("stops")
    @classmethod
    def _stops(cls, value: List[str]) -> List[str]:
        return _clean_stops(value)


class TaskCreate(_StopsMixin):
    """Create a mission without starting it (use /tasks/{id}/start)."""

    robot_id: Optional[str] = None
    repeats: int = Field(default=1, ge=1, le=1000)
    mode: Mode = "continuous"
    type: str = Field(default="route", max_length=64)
    payload: Optional[Dict[str, Any]] = None


class MissionStart(_StopsMixin):
    """Create + start a mission on one robot (the Plus-button form)."""

    robot_id: str = Field(min_length=1, max_length=64)
    repeats: int = Field(default=1, ge=1, le=1000)
    mode: Mode = "continuous"


class WaypointSend(BaseModel):
    """Send one robot to one waypoint (the text box)."""

    robot_id: str = Field(min_length=1, max_length=64)
    waypoint: str = Field(min_length=1, max_length=128)

    @field_validator("waypoint")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("waypoint cannot be empty")
        return value


class TaskUpdate(BaseModel):
    status: TaskStatus
    message: Optional[str] = Field(default=None, max_length=500)


class TaskOut(BaseModel):
    id: str
    type: str
    status: str
    robot_id: Optional[str] = None
    stops: List[str] = []
    mode: str = "continuous"
    repeats: int = 1
    completed_repeats: int = 0
    cursor: Optional[Dict[str, int]] = None
    message: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "TaskOut":
        return cls(
            id=str(doc.get("id")),
            type=str(doc.get("task_type") or "route"),
            status=str(doc.get("status") or TaskStatus.pending.value),
            robot_id=doc.get("robot_id"),
            stops=list(doc.get("stops") or []),
            mode=str(doc.get("mode") or "continuous"),
            repeats=int(doc.get("repeats") or 1),
            completed_repeats=int(doc.get("completed_repeats") or 0),
            cursor=doc.get("cursor"),
            message=doc.get("message"),
            created_by=doc.get("created_by"),
            created_at=doc.get("created_at"),
            started_at=doc.get("started_at"),
            finished_at=doc.get("finished_at"),
        )


class TaskHistoryOut(BaseModel):
    id: str
    task_id: str
    status: str
    message: Optional[str] = None
    at: Optional[datetime] = None


class TaskRequestCreate(_StopsMixin):
    """Unassigned work: the scheduler picks a free robot for it."""

    type: str = Field(default="route", max_length=64)
    robot_type: Optional[str] = Field(default=None, max_length=64)
    repeats: int = Field(default=1, ge=1, le=1000)
    mode: Mode = "continuous"
    # When set, the request sits in the queue until this instant before the
    # scheduler will claim it (naive values are treated as local server time).
    scheduled_at: Optional[datetime] = Field(default=None, alias="scheduled_at")

    model_config = {"populate_by_name": True}


class TaskRequestOut(BaseModel):
    id: str
    task_type: str
    status: str
    stops: List[str] = []
    mode: str = "continuous"
    robot_type: Optional[str] = None
    repeats: int = 1
    scheduled_at: Optional[datetime] = None
    assigned_task_id: Optional[str] = None
    assigned_robot_id: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "TaskRequestOut":
        return cls(
            id=str(doc.get("id")),
            task_type=str(doc.get("task_type") or "route"),
            status=str(doc.get("status") or "pending"),
            stops=list(doc.get("stops") or []),
            mode=str(doc.get("mode") or "continuous"),
            robot_type=doc.get("robot_type"),
            repeats=int(doc.get("repeats") or 1),
            scheduled_at=doc.get("scheduled_at"),
            assigned_task_id=doc.get("assigned_task_id"),
            assigned_robot_id=doc.get("assigned_robot_id"),
            created_at=doc.get("created_at"),
        )
