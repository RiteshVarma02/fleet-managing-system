"""Robot connect/disconnect, telemetry and registration orchestration."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, RobotNotConnectedError, ValidationError
from app.core.logging_config import get_logger
from app.db.models import Robot, RobotStatusEnum
from app.db.repositories import robots as robot_repo
from app.ros.manager import ros_manager

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_robot_id(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "robot"


def connect(db: Session, robot_id: str) -> Tuple[Robot, str]:
    if ros_manager.get_controller(robot_id) is None:
        ok, message = ros_manager.start_controller(robot_id)
        if not ok:
            robot_repo.upsert_robot(db, robot_id=robot_id, status=RobotStatusEnum.error)
            raise ConflictError(message, code="controller_start_failed")
    else:
        message = "Already connected"

    robot = robot_repo.upsert_robot(
        db,
        robot_id=robot_id,
        name=robot_id,
        status=RobotStatusEnum.online,
    )
    return robot, message


def disconnect(db: Session, robot_id: str) -> Tuple[Robot, str]:
    _, message = ros_manager.stop_controller(robot_id)
    robot = robot_repo.upsert_robot(db, robot_id=robot_id, status=RobotStatusEnum.offline)
    return robot, message


def require_controller(robot_id: str) -> Any:
    controller = ros_manager.get_controller(robot_id)
    if controller is None:
        raise RobotNotConnectedError(robot_id)
    return controller


def move(robot_id: str, linear: float, angular: float) -> None:
    require_controller(robot_id).move(linear, angular)


def emergency_stop(robot_id: str) -> None:
    ros_manager.publish_emergency(robot_id, True)


def emergency_stop_all() -> int:
    robot_ids = ros_manager.connected_robot_ids()
    for robot_id in robot_ids:
        try:
            ros_manager.publish_emergency(robot_id, True)
        except Exception as exc:  # pragma: no cover - keep stopping the rest
            logger.error("Emergency publish failed for %s: %s", robot_id, exc)
    return len(robot_ids)


def get_status(db: Session, robot_id: str) -> Dict[str, Any]:
    """Live telemetry when connected, last known DB state otherwise."""
    controller = ros_manager.get_controller(robot_id)
    if controller is not None:
        snapshot = controller.snapshot()
        robot_repo.upsert_robot(
            db,
            robot_id=robot_id,
            status=RobotStatusEnum.online,
            x=snapshot["position"]["x"],
            y=snapshot["position"]["y"],
            theta=snapshot["position"]["theta"],
            battery=snapshot["battery"],
        )
        return {
            "connected": True,
            "position": snapshot["position"],
            "velocity": snapshot["velocity"],
            "battery": snapshot["battery"],
            "nav": snapshot["nav"],
        }

    robot = robot_repo.get_robot(db, robot_id)
    if robot is None:
        raise NotFoundError(f"Robot '{robot_id}' not found")
    return {
        "connected": False,
        "position": {"x": robot.x, "y": robot.y, "theta": robot.theta},
        "velocity": {"linear": 0.0, "angular": 0.0},
        "battery": float(robot.battery),
        "nav": None,
    }


def list_robots(db: Session) -> List[Robot]:
    return robot_repo.list_robots(db)


def delete_robot(db: Session, robot_id: str) -> None:
    """Soft delete: history keeps referencing the robot."""
    ros_manager.stop_controller(robot_id)
    if not robot_repo.soft_delete_robot(db, robot_id):
        raise NotFoundError(f"Robot '{robot_id}' not found")


# --------------------------------------------------------------------------
# Registration workflow
# --------------------------------------------------------------------------
def register(db: Session, mac_address: str, hostname: Optional[str], ip_address: Optional[str]) -> Dict[str, Any]:
    robot = robot_repo.get_robot_by_mac(db, mac_address)
    if robot and robot.approved and not robot.is_deleted:
        robot_repo.upsert_robot(db, robot_id=robot.id, hostname=hostname, ip_address=ip_address)
        return {
            "status": "approved",
            "robot_id": robot.id,
            "namespace": f"/{robot.id}",
            "message": f"Welcome back! Registered as {robot.id}",
        }

    robot_repo.upsert_pending_registration(db, mac_address, hostname, ip_address)
    return {
        "status": "pending",
        "message": f"Registration submitted for MAC {mac_address}. Awaiting operator approval.",
    }


def approve(db: Session, mac_address: str, custom_name: str, robot_id: Optional[str] = None) -> Dict[str, Any]:
    custom_name = custom_name.strip()
    if not custom_name:
        raise ValidationError("custom_name is required")

    resolved_id = (robot_id or slugify_robot_id(custom_name)).strip()
    existing = robot_repo.get_robot(db, resolved_id, include_deleted=True)
    if existing and existing.mac_address and existing.mac_address != mac_address:
        raise ConflictError(f"Robot id '{resolved_id}' is already used by another robot")

    robot = robot_repo.approve_pending_registration(db, mac_address, resolved_id, custom_name)
    if robot is None:
        raise NotFoundError("Pending registration not found")

    started, message = ros_manager.start_controller(robot.id)
    if started:
        robot_repo.upsert_robot(db, robot_id=robot.id, status=RobotStatusEnum.online)
    else:
        logger.warning("Controller not started for %s: %s", robot.id, message)

    return {
        "robot_id": robot.id,
        "name": robot.name,
        "namespace": f"/{robot.id}",
        "controller_started": started,
        "message": f"Robot approved as {robot.name} ({robot.id})",
    }


def reject(db: Session, mac_address: str) -> None:
    if robot_repo.reject_pending_registration(db, mac_address) is None:
        raise NotFoundError("Pending registration not found")


def autostart_controllers(db: Session) -> None:
    """Bring up a controller for every known robot at boot."""
    robots = robot_repo.list_robots(db)
    logger.info("Starting controllers for %d robot(s)", len(robots))
    for robot in robots:
        ok, message = ros_manager.start_controller(robot.id)
        status = RobotStatusEnum.online if ok else RobotStatusEnum.offline
        if not ok:
            logger.warning("Controller not started for %s: %s", robot.id, message)
        try:
            robot_repo.upsert_robot(db, robot_id=robot.id, status=status, touch_last_seen=ok)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Status update failed for %s: %s", robot.id, exc)
