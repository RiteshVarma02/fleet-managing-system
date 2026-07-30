"""Robot and registration schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.db.models import RobotStatusEnum
from app.schemas.common import ORMModel, Position

ROBOT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def validate_robot_id(value: str) -> str:
    value = value.strip()
    if not ROBOT_ID_RE.match(value):
        raise ValueError("robot_id must be 1-64 chars of letters, digits, '-' or '_'")
    return value


class RobotIdBody(BaseModel):
    robot_id: str

    _v = field_validator("robot_id")(validate_robot_id)


class MoveCommand(RobotIdBody):
    linear: float = Field(ge=-5.0, le=5.0)
    angular: float = Field(ge=-5.0, le=5.0)


class PoseCommand(RobotIdBody):
    x: float
    y: float
    theta: float = 0.0


class RobotOut(ORMModel):
    id: str
    name: str
    type: str
    status: RobotStatusEnum
    battery: int
    position: Position
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    approved: bool
    last_seen_at: Optional[datetime] = None

    @classmethod
    def from_model(cls, robot) -> "RobotOut":
        return cls(
            id=robot.id,
            name=robot.name,
            type=robot.type,
            status=robot.status,
            battery=robot.battery,
            position=Position(x=robot.x, y=robot.y, theta=robot.theta),
            mac_address=robot.mac_address,
            hostname=robot.hostname,
            ip_address=robot.ip_address,
            approved=robot.approved,
            last_seen_at=robot.last_seen_at,
        )


class MacAddressBody(BaseModel):
    mac_address: str

    @field_validator("mac_address")
    @classmethod
    def _normalize(cls, value: str) -> str:
        value = value.strip().upper()
        if not MAC_RE.match(value):
            raise ValueError("mac_address must look like AA:BB:CC:DD:EE:FF")
        return value


class RobotApproveRequest(MacAddressBody):
    custom_name: str = Field(min_length=1, max_length=128)
    robot_id: Optional[str] = Field(default=None, description="Defaults to a slug of custom_name")


class RobotRegisterRequest(MacAddressBody):
    hostname: Optional[str] = Field(default=None, max_length=128)
    ip_address: Optional[str] = Field(default=None, max_length=64)


class PendingRegistrationOut(ORMModel):
    mac_address: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
