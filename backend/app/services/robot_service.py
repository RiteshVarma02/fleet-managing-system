"""Robot-facing business logic shared by HTTP endpoints and the scheduler.

The endpoints stay thin: everything that needs both Mongo *and* the ROS runtime
lives here, so there is exactly one definition of "connect a robot" and one
definition of "what does this robot look like right now".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import NotFoundError, RobotNotConnectedError
from app.core.logging_config import get_logger
from app.db.documents import RobotStatus
from app.db.repositories import robots_repo
from app.ros.manager import ros_manager
from app.ros.topics_registry import capabilities_for, default_robot_type
from app.services.robot_status import derive_status
from app.services.telemetry_bus import telemetry_bus

logger = get_logger(__name__)


async def get_robot(db, robot_id: str) -> Dict[str, Any]:
    robot = await robots_repo.get(db, robot_id)
    if robot is None:
        raise NotFoundError(f"Robot '{robot_id}' not found")
    return robot


def robot_type_of(robot: Dict[str, Any]) -> str:
    return str(robot.get("robot_type") or default_robot_type())


def require_controller(robot_id: str, capability: Optional[str] = None):
    controller = ros_manager.get_controller(robot_id)
    if controller is None:
        raise RobotNotConnectedError(f"Robot '{robot_id}' is not connected")
    if capability and not controller.has_capability(capability):
        raise NotFoundError(
            f"Robot '{robot_id}' does not support the '{capability}' capability"
        )
    return controller


async def connect(db, robot_id: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Start the controller for a stored robot (same ROS domain, /{robot}/ topics)."""
    robot = await get_robot(db, robot_id)
    ok, message = ros_manager.start_controller(robot_id, robot_type_of(robot))
    robot = await robots_repo.upsert(
        db, robot_id, status=RobotStatus.idle if ok else RobotStatus.error
    )
    return ok, message, robot


async def disconnect(db, robot_id: str) -> Dict[str, Any]:
    ros_manager.stop_controller(robot_id)
    telemetry_bus.forget(robot_id)
    return await robots_repo.upsert(db, robot_id, status=RobotStatus.offline)


def live_snapshot(robot_id: str) -> Optional[Dict[str, Any]]:
    """Controller snapshot when attached, else the last telemetry-bus frame.

    Reading the bus instead of Mongo keeps per-request cost at zero I/O for the
    hot path (fleet list, operator console polling).
    """
    controller = ros_manager.get_controller(robot_id)
    if controller is not None:
        return controller.snapshot()
    return telemetry_bus.snapshot(robot_id)


def status_of(robot_id: str) -> RobotStatus:
    """Current derived status (see `robot_status.derive_status`)."""
    from app.services.task_service import task_engine  # local: avoids import cycle

    controller = ros_manager.get_controller(robot_id)
    if controller is None:
        return RobotStatus.offline
    snap = controller.snapshot()
    progress = task_engine.robot_progress(robot_id) or {}
    return derive_status(
        connected=True,
        seconds_since_seen=snap.get("seconds_since_seen"),
        stale_after_seconds=settings.telemetry_stale_after_seconds,
        stop_active=bool(snap.get("stop_active")),
        emergency_active=bool(snap.get("emergency_active")),
        task_status=progress.get("status"),
        nav_status=(snap.get("nav") or {}).get("status"),
    )


def view(robot: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the stored document with live state — no database round trip."""
    robot_id = str(robot.get("robot_id") or "")
    return {
        "document": robot,
        "connected": ros_manager.get_controller(robot_id) is not None,
        "status": status_of(robot_id).value,
        "live": live_snapshot(robot_id),
        "capabilities": capabilities_for(robot_type_of(robot)),
    }


async def fleet_view(db, *, approved_only: bool = False) -> List[Dict[str, Any]]:
    rows = await robots_repo.list_all(db, approved_only=approved_only)
    return [view(row) for row in rows]


async def idle_robot_ids(db, *, robot_type: Optional[str] = None) -> List[str]:
    """Approved robots whose derived status is `idle` — scheduler candidates."""
    candidates: List[str] = []
    for robot in await robots_repo.list_all(db, approved_only=True):
        robot_id = str(robot.get("robot_id") or "")
        if robot.get("active_task_id") or status_of(robot_id) != RobotStatus.idle:
            continue
        if robot_type and robot_type_of(robot) != robot_type:
            continue
        candidates.append(robot_id)
    return candidates
