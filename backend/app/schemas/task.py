"""Task, pending-request and location schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.db.models import TaskStatusEnum
from app.schemas.common import ORMModel
from app.schemas.robot import validate_robot_id


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


class LocationOut(ORMModel):
    id: str
    name: str
    x: float
    y: float
    theta: float
    map_name: Optional[str] = None
    created_at: Optional[datetime] = None


class TaskCreate(BaseModel):
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    robot_id: Optional[str] = None
    type: str = "pick_drop"
    repeats: int = Field(default=1, ge=1, le=1000)


class TaskUpdate(BaseModel):
    status: TaskStatusEnum
    message: Optional[str] = Field(default=None, max_length=2000)


class TaskOut(ORMModel):
    id: str
    type: str
    status: TaskStatusEnum
    robot_id: Optional[str] = None
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    repeats: int
    message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class TaskHistoryOut(ORMModel):
    id: str
    task_id: str
    robot_id: Optional[str] = None
    event_type: str
    message: Optional[str] = None
    timestamp: Optional[datetime] = None


class PickDropStart(BaseModel):
    robot_id: str
    pickup_location_id: str
    drop_location_id: str
    repeats: int = Field(default=1, ge=1, le=1000)

    _v = field_validator("robot_id")(validate_robot_id)


class PendingRequestCreate(BaseModel):
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    robot_type: Optional[str] = Field(default=None, max_length=64)
    priority: int = Field(default=0, ge=0, le=100)
    scheduled_for: Optional[datetime] = None


class PendingRequestOut(ORMModel):
    id: str
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    robot_type: Optional[str] = None
    priority: int
    scheduled_for: Optional[datetime] = None
    assigned_task_id: Optional[str] = None
    created_at: Optional[datetime] = None
