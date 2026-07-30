"""Data-access layer for robots and registrations.

Repositories own SQL. Services own orchestration. Routers own HTTP.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import PendingRegistration, RegistrationStatusEnum, Robot, RobotStatusEnum

_UNSET = object()


def get_robot(db: Session, robot_id: str, *, include_deleted: bool = False) -> Optional[Robot]:
    robot = db.get(Robot, robot_id)
    if robot is None:
        return None
    if robot.is_deleted and not include_deleted:
        return None
    return robot


def get_robot_by_mac(db: Session, mac_address: str) -> Optional[Robot]:
    stmt = select(Robot).where(Robot.mac_address == mac_address.strip().upper())
    return db.execute(stmt).scalar_one_or_none()


def list_robots(db: Session, *, include_deleted: bool = False) -> List[Robot]:
    stmt = select(Robot).order_by(Robot.id)
    if not include_deleted:
        stmt = stmt.where(Robot.deleted_at.is_(None))
    return list(db.execute(stmt).scalars())


def list_available_robots(db: Session, robot_type: Optional[str] = None) -> List[Robot]:
    stmt = select(Robot).where(
        Robot.deleted_at.is_(None),
        Robot.status == RobotStatusEnum.online,
    )
    if robot_type:
        stmt = stmt.where(Robot.type == robot_type)
    return list(db.execute(stmt).scalars())


def upsert_robot(
    db: Session,
    *,
    robot_id: str,
    name: Optional[str] = None,
    robot_type: Optional[str] = None,
    status: Optional[RobotStatusEnum] = None,
    battery: Optional[float] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    theta: Optional[float] = None,
    mac_address: Optional[str] = None,
    hostname: Optional[str] = None,
    ip_address: Optional[str] = None,
    approved: Optional[bool] = None,
    touch_last_seen: bool = True,
) -> Robot:
    """Create or partially update a robot row. `None` means "leave unchanged"."""
    robot = db.get(Robot, robot_id)
    if robot is None:
        robot = Robot(id=robot_id, name=name or robot_id, type=robot_type or "generic")
        db.add(robot)

    if name is not None:
        robot.name = name
    if robot_type is not None:
        robot.type = robot_type
    if status is not None:
        robot.status = status
    if battery is not None:
        # Column is an int; incoming ROS values are floats in [0, 100].
        robot.battery = max(0, min(100, int(round(float(battery)))))
    if x is not None:
        robot.x = float(x)
    if y is not None:
        robot.y = float(y)
    if theta is not None:
        robot.theta = float(theta)
    if mac_address is not None:
        robot.mac_address = mac_address.strip().upper()
    if hostname is not None:
        robot.hostname = hostname
    if ip_address is not None:
        robot.ip_address = ip_address
    if approved is not None:
        robot.approved = approved
    if touch_last_seen:
        robot.last_seen_at = utcnow()

    db.commit()
    db.refresh(robot)
    return robot


def soft_delete_robot(db: Session, robot_id: str) -> bool:
    robot = get_robot(db, robot_id)
    if robot is None:
        return False
    robot.deleted_at = utcnow()
    robot.status = RobotStatusEnum.offline
    db.commit()
    return True


def mark_all_offline(db: Session) -> None:
    for robot in list_robots(db):
        robot.status = RobotStatusEnum.offline
    db.commit()


# --------------------------------------------------------------------------
# Registration workflow
# --------------------------------------------------------------------------
def list_pending_registrations(db: Session) -> List[PendingRegistration]:
    stmt = (
        select(PendingRegistration)
        .where(PendingRegistration.status == RegistrationStatusEnum.pending)
        .order_by(PendingRegistration.first_seen_at)
    )
    return list(db.execute(stmt).scalars())


def upsert_pending_registration(
    db: Session,
    mac_address: str,
    hostname: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> PendingRegistration:
    mac = mac_address.strip().upper()
    pending = db.get(PendingRegistration, mac)
    if pending is None:
        pending = PendingRegistration(mac_address=mac)
        db.add(pending)
    pending.hostname = hostname or pending.hostname
    pending.ip_address = ip_address or pending.ip_address
    pending.status = RegistrationStatusEnum.pending
    pending.last_seen_at = utcnow()
    db.commit()
    db.refresh(pending)
    return pending


def approve_pending_registration(db: Session, mac_address: str, robot_id: str, name: str) -> Optional[Robot]:
    mac = mac_address.strip().upper()
    pending = db.get(PendingRegistration, mac)
    if pending is None or pending.status != RegistrationStatusEnum.pending:
        return None

    robot = get_robot_by_mac(db, mac)
    if robot is None:
        robot = Robot(id=robot_id, name=name, mac_address=mac)
        db.add(robot)
    robot.name = name
    robot.approved = True
    robot.deleted_at = None
    robot.hostname = pending.hostname
    robot.ip_address = pending.ip_address
    robot.status = RobotStatusEnum.offline
    robot.last_seen_at = utcnow()

    pending.status = RegistrationStatusEnum.approved
    db.commit()
    db.refresh(robot)
    return robot


def reject_pending_registration(db: Session, mac_address: str) -> Optional[PendingRegistration]:
    pending = db.get(PendingRegistration, mac_address.strip().upper())
    if pending is None:
        return None
    pending.status = RegistrationStatusEnum.rejected
    db.commit()
    return pending
