"""Task, pending-request and location schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from app.db.documents import TaskStatus


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    x: float
    y: float
    theta: float = 0.0
    map_name: Optional[str] = Field(default=None, max_length=128)

    @field_validator("name", "map_name")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value


class LocationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    x: Optional[float] = None
    y: Optional[float] = None
    theta: Optional[float] = None
    map_name: Optional[str] = Field(default=None, max_length=128)


class LocationOut(BaseModel):
    id: str
    name: str
    x: float
    y: float
    theta: float
    map_name: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "LocationOut":
        return cls(
            id=str(doc.get("id")),
            name=str(doc.get("name")),
            x=float(doc.get("x", 0.0)),
            y=float(doc.get("y", 0.0)),
            theta=float(doc.get("theta", 0.0)),
            map_name=doc.get("map_name"),
            created_at=doc.get("created_at"),
        )


class TaskCreate(BaseModel):
    type: str = Field(default="pick_drop", max_length=64)
    robot_id: Optional[str] = None
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    repeats: int = Field(default=1, ge=1, le=1000)
    payload: Optional[Dict[str, Any]] = None


class TaskUpdate(BaseModel):
    status: TaskStatus
    message: Optional[str] = Field(default=None, max_length=500)


class PickDropStart(BaseModel):
    robot_id: str = Field(min_length=1, max_length=64)
    pickup_location_id: str = Field(min_length=1)
    drop_location_id: str = Field(min_length=1)
    repeats: int = Field(default=1, ge=1, le=1000)


class TaskOut(BaseModel):
    id: str
    type: str
    status: str
    robot_id: Optional[str] = None
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    repeats: int = 1
    completed_repeats: int = 0
    message: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "TaskOut":
        return cls(
            id=str(doc.get("id")),
            type=str(doc.get("task_type") or "pick_drop"),
            status=str(doc.get("status") or TaskStatus.pending.value),
            robot_id=doc.get("robot_id"),
            from_location_id=doc.get("from_location_id"),
            to_location_id=doc.get("to_location_id"),
            repeats=int(doc.get("repeats") or 1),
            completed_repeats=int(doc.get("completed_repeats") or 0),
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


class TaskRequestCreate(BaseModel):
    """Unassigned work: the scheduler picks a free robot for it."""

    type: str = Field(default="pick_drop", max_length=64)
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    robot_type: Optional[str] = Field(default=None, max_length=64)
    repeats: int = Field(default=1, ge=1, le=1000)


class TaskRequestOut(BaseModel):
    id: str
    task_type: str
    status: str
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    robot_type: Optional[str] = None
    repeats: int = 1
    assigned_task_id: Optional[str] = None
    assigned_robot_id: Optional[str] = None
    created_at: Optional[datetime] = None

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "TaskRequestOut":
        return cls(
            id=str(doc.get("id")),
            task_type=str(doc.get("task_type") or "pick_drop"),
            status=str(doc.get("status") or "pending"),
            from_location_id=doc.get("from_location_id"),
            to_location_id=doc.get("to_location_id"),
            robot_type=doc.get("robot_type"),
            repeats=int(doc.get("repeats") or 1),
            assigned_task_id=doc.get("assigned_task_id"),
            assigned_robot_id=doc.get("assigned_robot_id"),
            created_at=doc.get("created_at"),
        )
