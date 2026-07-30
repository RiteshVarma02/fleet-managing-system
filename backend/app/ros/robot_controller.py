"""Per-robot ROS 2 node: telemetry in, velocity/goals out."""

from __future__ import annotations

import base64
import io
import threading
import time
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import RobotStatusEnum
from app.db.repositories import robots as robot_repo
from app.db.session import session_scope
from app.ros.runtime import RosModules, quaternion_to_yaw, yaw_to_quaternion

logger = get_logger(__name__)

# Navigation states exposed to the API.
NAV_IDLE = "idle"
NAV_SENDING = "sending"
NAV_ACTIVE = "active"
NAV_SUCCEEDED = "succeeded"
NAV_FAILED = "failed"
NAV_REJECTED = "rejected"
NAV_CANCELLED = "cancelled"

_TERMINAL_NAV_STATES = {NAV_SUCCEEDED, NAV_FAILED, NAV_REJECTED, NAV_CANCELLED}

# Maps a token found in the incoming status string to our internal state.
# Ordered: the first match wins, so more specific tokens come first.
_STATUS_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("SENDING_GOAL", NAV_SENDING),
    ("REJECTED", NAV_REJECTED),
    ("CANCELLED", NAV_CANCELLED),
    ("CANCELED", NAV_CANCELLED),
    ("SUCCEEDED", NAV_SUCCEEDED),
    ("COMPLETED", NAV_SUCCEEDED),
    ("FAILED", NAV_FAILED),
    ("ABORTED", NAV_FAILED),
    ("IN_PROGRESS", NAV_ACTIVE),
    ("ACCEPTED", NAV_ACTIVE),
)


def build_robot_controller_class(ros: RosModules):
    """Build the controller class bound to the imported ROS modules.

    Defining the class lazily keeps `rclpy` out of import time so the service
    starts on hosts without ROS installed.
    """

    class RobotController(ros.Node):  # type: ignore[misc, valid-type]
        def __init__(self, robot_id: str) -> None:
            super().__init__(f"robot_controller_{robot_id}")
            self.robot_id = robot_id

            ns = f"/{robot_id}"
            self.cmd_vel_pub = self.create_publisher(ros.Twist, f"{ns}/cmd_vel", 10)
            self.initial_pose_pub = self.create_publisher(
                ros.PoseWithCovarianceStamped, f"{ns}/initialpose", 10
            )
            self.goal_request_pub = self.create_publisher(ros.PoseStamped, f"{ns}/goal_request", 10)

            self.create_subscription(ros.Odometry, f"{ns}/odom", self._on_odom, 10)
            self.create_subscription(ros.LaserScan, f"{ns}/scan", self._on_scan, 10)
            self.create_subscription(ros.BatteryState, f"{ns}/battery_state", self._on_battery, 10)
            self.create_subscription(ros.Bool, f"{ns}/emergency_stop", self._on_emergency, 10)
            self.create_subscription(ros.String, f"{ns}/navigation_status", self._on_nav_status, 10)
            # The map is global, not namespaced.
            self.create_subscription(ros.OccupancyGrid, settings.map_topic, self._on_map, 10)

            self._state_lock = threading.Lock()
            self.current_position: Dict[str, float] = {"x": 0.0, "y": 0.0, "theta": 0.0}
            self.current_velocity: Dict[str, float] = {"linear": 0.0, "angular": 0.0}
            self.battery_percentage: float = 100.0
            self.current_map = None
            self.current_scan = None

            self._nav_done = threading.Event()
            self._nav_done.set()
            self._nav_state: Dict[str, Any] = {
                "status": NAV_IDLE,
                "goal": None,
                "message": None,
                "updated_at": time.time(),
            }

            self._last_db_write = 0.0
            self._db_write_lock = threading.Lock()

        # ---------------- telemetry -> state ----------------
        def _on_odom(self, msg) -> None:
            q = msg.pose.pose.orientation
            with self._state_lock:
                self.current_position = {
                    "x": msg.pose.pose.position.x,
                    "y": msg.pose.pose.position.y,
                    "theta": quaternion_to_yaw(q.x, q.y, q.z, q.w),
                }
                self.current_velocity = {
                    "linear": msg.twist.twist.linear.x,
                    "angular": msg.twist.twist.angular.z,
                }
                position = dict(self.current_position)
            self._persist(x=position["x"], y=position["y"], theta=position["theta"])

        def _on_scan(self, msg) -> None:
            self.current_scan = msg

        def _on_map(self, msg) -> None:
            self.current_map = msg

        def _on_battery(self, msg) -> None:
            percentage = float(msg.percentage)
            # ROS publishes 0..1; tolerate drivers that already send 0..100.
            if percentage <= 1.0:
                percentage *= 100.0
            with self._state_lock:
                self.battery_percentage = max(0.0, min(100.0, percentage))
            self._persist(battery=self.battery_percentage)

        def _on_emergency(self, msg) -> None:
            if not msg.data:
                return
            self.stop()
            self._persist(status=RobotStatusEnum.error, force=True)

        # ---------------- persistence ----------------
        def _persist(self, *, force: bool = False, **fields) -> None:
            """Throttled write-through to the database.

            A short-lived session per write; a session must never be shared
            between the executor thread and request threads.
            """
            now = time.time()
            with self._db_write_lock:
                if not force and now - self._last_db_write < settings.robot_db_update_interval_seconds:
                    return
                self._last_db_write = now
            try:
                with session_scope() as db:
                    robot_repo.upsert_robot(
                        db,
                        robot_id=self.robot_id,
                        status=fields.pop("status", RobotStatusEnum.online),
                        **fields,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("DB update failed for %s: %s", self.robot_id, exc)

        # ---------------- commands ----------------
        def move(self, linear: float, angular: float) -> None:
            msg = ros.Twist()
            msg.linear.x = float(linear)
            msg.angular.z = float(angular)
            self.cmd_vel_pub.publish(msg)

        def stop(self) -> None:
            self.move(0.0, 0.0)

        def set_initial_pose(self, x: float, y: float, theta: float) -> None:
            msg = ros.PoseWithCovarianceStamped()
            msg.header.frame_id = "map"
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.pose.pose.position.x = float(x)
            msg.pose.pose.position.y = float(y)
            msg.pose.pose.position.z = 0.0
            qz, qw = yaw_to_quaternion(theta)
            msg.pose.pose.orientation.z = qz
            msg.pose.pose.orientation.w = qw
            self.initial_pose_pub.publish(msg)

        def send_goal(self, x: float, y: float, theta: float = 0.0) -> Tuple[bool, str]:
            """Publish a goal to `/{robot_id}/goal_request`.

            The domain bridge remaps it onto the robot's domain where
            `robot_action_forwarder` forwards it to the nav2 action server and
            reports back on `/{robot_id}/navigation_status`.
            """
            try:
                msg = ros.PoseStamped()
                msg.header.frame_id = "map"
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.pose.position.x = float(x)
                msg.pose.position.y = float(y)
                msg.pose.position.z = 0.0
                qz, qw = yaw_to_quaternion(theta)
                msg.pose.orientation.z = qz
                msg.pose.orientation.w = qw

                self._nav_done.clear()
                self._set_nav_state(
                    status=NAV_SENDING,
                    goal={"x": float(x), "y": float(y), "theta": float(theta)},
                    message="Publishing goal",
                )
                self.goal_request_pub.publish(msg)
                logger.info("[%s] goal published (%.2f, %.2f, %.2f)", self.robot_id, x, y, theta)
                return True, "Goal published"
            except Exception as exc:
                message = f"Failed to publish goal: {exc}"
                logger.error("[%s] %s", self.robot_id, message)
                self._set_nav_state(status=NAV_FAILED, message=message)
                self._nav_done.set()
                return False, message

        # ---------------- navigation state ----------------
        def _set_nav_state(self, **updates) -> None:
            with self._state_lock:
                self._nav_state.update(updates)
                self._nav_state["updated_at"] = time.time()

        def _on_nav_status(self, msg) -> None:
            raw = (msg.data or "").upper()
            new_status = next((state for token, state in _STATUS_TOKENS if token in raw), None)
            if new_status is None:
                logger.debug("[%s] unrecognised nav status: %s", self.robot_id, msg.data)
                return

            self._set_nav_state(status=new_status, message=msg.data)
            if new_status in _TERMINAL_NAV_STATES:
                self._nav_done.set()
            logger.info("[%s] nav status -> %s", self.robot_id, new_status)

        def wait_for_nav_done(self, timeout: Optional[float] = None) -> bool:
            return self._nav_done.wait(timeout=timeout)

        def get_nav_status(self) -> Dict[str, Any]:
            with self._state_lock:
                return dict(self._nav_state)

        def cancel_navigation(self) -> None:
            self.stop()
            self._set_nav_state(status=NAV_CANCELLED, message="Cancelled by operator")
            self._nav_done.set()

        # ---------------- snapshots ----------------
        def snapshot(self) -> Dict[str, Any]:
            with self._state_lock:
                return {
                    "position": dict(self.current_position),
                    "velocity": dict(self.current_velocity),
                    "battery": self.battery_percentage,
                    "nav": dict(self._nav_state),
                }

        def get_map_image(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
            import numpy as np
            from PIL import Image

            grid = self.current_map
            if grid is None:
                return None, None

            width, height = grid.info.width, grid.info.height
            data = np.asarray(grid.data, dtype=np.int16).reshape((height, width))

            img_data = np.zeros((height, width), dtype=np.uint8)
            img_data[data == -1] = 127
            img_data[data == 0] = 255
            img_data[data > 0] = 0

            buffer = io.BytesIO()
            Image.fromarray(img_data, mode="L").save(buffer, format="PNG")
            metadata = {
                "width": width,
                "height": height,
                "resolution": grid.info.resolution,
                "origin_x": grid.info.origin.position.x,
                "origin_y": grid.info.origin.position.y,
            }
            return base64.b64encode(buffer.getvalue()).decode(), metadata

    return RobotController
