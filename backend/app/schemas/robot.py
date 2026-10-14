"""Robot and registration schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Position, Velocity

# robot_id IS the ROS namespace (/{robot_id}/amr/goal …), so it must be a
# valid ROS name segment: letter first, then letters/digits/underscore.
ROBOT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def validate_robot_id(value: str) -> str:
    value = value.strip()
    if not ROBOT_ID_RE.match(value):
        raise ValueError(
            "robot_id must be a ROS namespace: start with a letter, then letters, digits or '_'"
        )
    return value


class RobotIdBody(BaseModel):
    robot_id: str

    _v = field_validator("robot_id")(validate_robot_id)


class MoveCommand(RobotIdBody):
    linear: float = Field(ge=-5.0, le=5.0)
    angular: float = Field(ge=-5.0, le=5.0)


class DockCommand(RobotIdBody):
    command: str = Field(pattern="^(dock|undock)$")


class ForkCommand(RobotIdBody):
    height: float = Field(ge=0.0, le=5.0)


class GripperCommand(RobotIdBody):
    command: str = Field(pattern="^(open|close|home)$")


class RobotOut(BaseModel):
    id: str
    name: str
    type: str
    status: str
    battery: float = 100.0
    position: Position = Position()
    capabilities: List[str] = []
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    approved: bool = False
    connected: bool = False
    stop_active: bool = False
    emergency_active: bool = False
    active_task_id: Optional[str] = None
    last_seen_at: Optional[datetime] = None

    @classmethod
    def from_document(
        cls,
        doc: Dict[str, Any],
        *,
        connected: bool = False,
        capabilities: Optional[List[str]] = None,
        live: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
    ) -> "RobotOut":
        position = (live or {}).get("position") or doc.get("last_position") or {}
        battery = (live or {}).get("battery")
        return cls(
            id=str(doc.get("robot_id")),
            name=str(doc.get("display_name") or doc.get("robot_id")),
            type=str(doc.get("robot_type") or ""),
            status=str(status or doc.get("status") or "offline"),
            battery=float(
                battery if battery is not None else doc.get("battery_percentage") or 0.0
            ),
            position=Position(**{k: float(position.get(k, 0.0)) for k in ("x", "y", "theta")}),
            capabilities=capabilities or [],
            mac_address=doc.get("mac_address"),
            hostname=doc.get("hostname"),
            ip_address=doc.get("ip_address"),
            approved=bool(doc.get("approved")),
            connected=connected,
            stop_active=bool((live or {}).get("stop_active")),
            emergency_active=bool((live or {}).get("emergency_active")),
            active_task_id=doc.get("active_task_id"),
            last_seen_at=doc.get("last_seen_at"),
        )


class RobotTelemetryOut(BaseModel):
    robot_id: str
    connected: bool = False
    status: str = "offline"
    position: Position = Position()
    velocity: Velocity = Velocity()
    battery: Optional[float] = None
    nav: Optional[Dict[str, Any]] = None
    dock_state: Optional[str] = None
    fork_height: Optional[float] = None
    arm_state: Optional[str] = None
    emergency_active: bool = False
    stop_active: bool = False
    safety_hold: Optional[str] = None
    capabilities: List[str] = []
    topics: Dict[str, str] = {}


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
    robot_type: Optional[str] = Field(default=None, max_length=64)

    @field_validator("robot_id")
    @classmethod
    def _check_id(cls, value: Optional[str]) -> Optional[str]:
        return validate_robot_id(value) if value else value


class RobotCreateRequest(BaseModel):
    """Add a robot by hand (no MAC registration): its id is its ROS namespace."""

    robot_id: str
    name: Optional[str] = Field(default=None, max_length=128)
    robot_type: Optional[str] = Field(default=None, max_length=64)
    connect: bool = True

    _v = field_validator("robot_id")(validate_robot_id)


class RobotRegisterRequest(MacAddressBody):
    hostname: Optional[str] = Field(default=None, max_length=128)
    ip_address: Optional[str] = Field(default=None, max_length=64)


class PendingRegistrationOut(BaseModel):
    mac_address: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    status: str = "pending"
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None


class RobotTypeOut(BaseModel):
    name: str
    description: str
    capabilities: List[str]
    extends: Optional[str] = None
    topics: Dict[str, Dict[str, str]] = {}
