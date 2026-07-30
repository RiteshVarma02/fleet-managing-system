"""ORM models for robots, locations, tasks and the registration workflow."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_uuid, utcnow


class RobotStatusEnum(str, enum.Enum):
    online = "online"
    offline = "offline"
    error = "error"
    charging = "charging"


class TaskStatusEnum(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class RegistrationStatusEnum(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Robot(TimestampMixin, Base):
    __tablename__ = "robots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(64), default="generic", nullable=False)
    status: Mapped[RobotStatusEnum] = mapped_column(
        SAEnum(RobotStatusEnum, name="robot_status"), default=RobotStatusEnum.offline, nullable=False
    )
    battery: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    x: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    y: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    theta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    mac_address: Mapped[Optional[str]] = mapped_column(String(32), unique=True, index=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(128))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Soft delete: history rows keep pointing at the robot.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)

    tasks: Mapped[List["Task"]] = relationship(back_populates="robot")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Location(TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("name", "map_name", name="uq_location_name_map"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    theta: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    map_name: Mapped[Optional[str]] = mapped_column(String(128), index=True)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_robot_status", "robot_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    type: Mapped[str] = mapped_column(String(64), default="pick_drop", nullable=False)
    status: Mapped[TaskStatusEnum] = mapped_column(
        SAEnum(TaskStatusEnum, name="task_status"), default=TaskStatusEnum.pending, nullable=False, index=True
    )

    robot_id: Mapped[Optional[str]] = mapped_column(ForeignKey("robots.id"), index=True)
    from_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"))

    repeats: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    robot: Mapped[Optional[Robot]] = relationship(back_populates="tasks")
    history: Mapped[List["TaskHistory"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskHistory.timestamp"
    )


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False)
    robot_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="history")


class PendingRequest(TimestampMixin, Base):
    """A transport request waiting for a free robot."""

    __tablename__ = "pending_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    from_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[Optional[str]] = mapped_column(ForeignKey("locations.id"))
    robot_type: Mapped[Optional[str]] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    assigned_task_id: Mapped[Optional[str]] = mapped_column(ForeignKey("tasks.id"), index=True)


class PendingRegistration(Base):
    """A robot that announced itself and awaits operator approval."""

    __tablename__ = "pending_registrations"

    mac_address: Mapped[str] = mapped_column(String(32), primary_key=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(128))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[RegistrationStatusEnum] = mapped_column(
        SAEnum(RegistrationStatusEnum, name="registration_status"),
        default=RegistrationStatusEnum.pending,
        nullable=False,
        index=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="operator", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
