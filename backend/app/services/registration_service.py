"""MAC-based zero-touch onboarding, shared by the HTTP and ROS entry points.

The ROS registration listener runs on an `rclpy` thread and cannot await, so
`make_thread_handler()` returns a blocking shim that hands the coroutine to the
main event loop via `run_coroutine_threadsafe`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from app.core.logging_config import get_logger
from app.db.documents import RobotStatus
from app.db.mongo import get_database
from app.db.repositories import robot_registrations_repo, robots_repo
from app.ros.manager import ros_manager
from app.ros.topics_registry import DEFAULT_ROBOT_TYPE

logger = get_logger(__name__)

REGISTRATION_TIMEOUT_SECONDS = 10.0


async def handle_registration(
    db, mac_address: str, hostname: Optional[str], ip_address: Optional[str]
) -> Dict[str, Any]:
    """Approved MAC -> reconnect. Unknown MAC -> pending row awaiting approval."""
    robot = await robots_repo.get_by_mac(db, mac_address)
    if robot and bool(robot.get("approved")) and not bool(robot.get("is_deleted")):
        robot_id = str(robot["robot_id"])
        await robots_repo.upsert(
            db,
            robot_id,
            hostname=hostname,
            ip_address=ip_address,
            status=RobotStatus.online,
        )
        started, message = ros_manager.start_controller(
            robot_id,
            str(robot.get("robot_type") or DEFAULT_ROBOT_TYPE),
            robot.get("ros_domain_id"),
            share_map=bool(robot.get("map_share_enabled")),
        )
        if not started:
            logger.warning("Controller not started for %s: %s", robot_id, message)
        return {
            "status": "approved",
            "robot_id": robot_id,
            "namespace": f"/{robot_id}",
            "controller_started": started,
            "message": f"Welcome back! Registered as {robot_id}",
        }

    await robot_registrations_repo.check_in(db, mac_address, hostname, ip_address)
    return {
        "status": "pending",
        "message": (
            f"Registration submitted for MAC {mac_address}. Awaiting operator approval."
        ),
    }


def make_thread_handler(loop: asyncio.AbstractEventLoop):
    """Blocking `(mac, hostname, ip) -> dict` shim usable from a ROS thread."""

    def handler(
        mac_address: str, hostname: Optional[str], ip_address: Optional[str]
    ) -> Dict[str, Any]:
        future = asyncio.run_coroutine_threadsafe(
            handle_registration(get_database(), mac_address, hostname, ip_address), loop
        )
        try:
            return future.result(timeout=REGISTRATION_TIMEOUT_SECONDS)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Registration for %s failed: %s", mac_address, exc)
            return {"status": "error", "message": "Registration could not be processed"}

    return handler
