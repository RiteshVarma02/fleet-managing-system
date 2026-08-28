"""Nav2 goals across ROS domains.

The server never talks to the Nav2 action server directly: actions do not cross
a `domain_bridge`. Instead a goal is published on `/{robot_id}/goal_request`,
bridged down to `/goal_request` on the robot domain, where
`deploy/robot_action_forwarder.py` turns it into a `NavigateToPose` action goal
and publishes progress back on `/navigation_status`.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

from app.core.logging_config import get_logger
from app.ros.runtime import yaw_to_quaternion

logger = get_logger(__name__)

NAV_IDLE = "idle"
NAV_SENDING = "sending"
NAV_ACTIVE = "active"
NAV_SUCCEEDED = "succeeded"
NAV_FAILED = "failed"
NAV_REJECTED = "rejected"
NAV_CANCELLED = "cancelled"
NAV_PAUSED = "paused"

TERMINAL_NAV_STATES = {NAV_SUCCEEDED, NAV_FAILED, NAV_REJECTED, NAV_CANCELLED}

# First match wins, so the specific tokens come first.
_STATUS_TOKENS: Tuple[Tuple[str, str], ...] = (
    ("SENDING_GOAL", NAV_SENDING),
    ("GOAL_RECEIVED", NAV_SENDING),
    ("REJECTED", NAV_REJECTED),
    ("CANCELLED", NAV_CANCELLED),
    ("CANCELED", NAV_CANCELLED),
    ("SUCCEEDED", NAV_SUCCEEDED),
    ("COMPLETED", NAV_SUCCEEDED),
    ("FAILED", NAV_FAILED),
    ("ABORTED", NAV_FAILED),
    ("ERROR", NAV_FAILED),
    ("IN_PROGRESS", NAV_ACTIVE),
    ("ACCEPTED", NAV_ACTIVE),
    ("READY", NAV_IDLE),
)


class NavigationCapability:
    name = "navigation"

    def setup_navigation(self) -> None:
        self._goal_pub = self.publisher("goal_request", self._ros.PoseStamped)
        self._goal_cancel_pub = self.publisher("goal_cancel", self._ros.Bool)
        self._initial_pose_pub = self.publisher("initial_pose", self._ros.PoseWithCovarianceStamped)
        self.subscribe("navigation_status", self._ros.String, self._on_nav_status, qos=10)

        self._nav_done = threading.Event()
        self._nav_done.set()
        # Epoch increments on every goal send. Status updates carry the epoch
        # they belong to, so a delayed terminal message from the previous leg
        # (bridge jitter, queued status) can never satisfy the *current* wait.
        self._nav_epoch = 0
        self._nav_state: Dict[str, Any] = {
            "status": NAV_IDLE,
            "goal": None,
            "message": None,
            "updated_at": time.time(),
            "epoch": 0,
        }
        # Last commanded goal, kept so a paused goal can be re-sent on resume.
        # Nav2 has no native pause for NavigateToPose — the industry pattern is
        # cancel-then-reissue, which this capability implements.
        self._last_goal: Optional[Dict[str, float]] = None

    # ---------------- state ----------------
    def _set_nav_state(self, **fields: Any) -> None:
        with self._state_lock:
            self._nav_state.update(fields)
            self._nav_state["updated_at"] = time.time()
            status = self._nav_state["status"]
        if status in TERMINAL_NAV_STATES:
            self._nav_done.set()
        self.report_telemetry(nav=self.get_nav_status())

    def get_nav_status(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self._nav_state)

    def _on_nav_status(self, msg: Any) -> None:
        raw = str(getattr(msg, "data", "") or "")
        upper = raw.upper()
        for token, state in _STATUS_TOKENS:
            if token in upper:
                # The forwarder confirms our pause-cancel with CANCELLED;
                # keep the operator-facing state as paused instead.
                with self._state_lock:
                    if self._nav_state.get("status") == NAV_PAUSED and state == NAV_CANCELLED:
                        return
                self._set_nav_state(status=state, message=raw)
                return
        self._set_nav_state(message=raw)

    # ---------------- commands ----------------
    def send_nav2_goal(self, x: float, y: float, theta: float = 0.0) -> Tuple[bool, str]:
        if self._goal_pub is None:
            return False, "Robot type has no navigation goal topic"
        msg = self._ros.PoseStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.position.x = float(x)
        msg.pose.position.y = float(y)
        msg.pose.position.z = 0.0
        qz, qw = yaw_to_quaternion(theta)
        msg.pose.orientation.z = qz
        msg.pose.orientation.w = qw

        goal = {"x": float(x), "y": float(y), "theta": float(theta)}
        with self._state_lock:
            self._nav_epoch += 1
            epoch = self._nav_epoch
            self._last_goal = dict(goal)

        self._nav_done.clear()
        self._set_nav_state(
            status=NAV_SENDING,
            goal=goal,
            message="Goal published",
            epoch=epoch,
        )
        self._goal_pub.publish(msg)
        logger.info("%s goal -> (%.2f, %.2f, %.2f) [epoch %d]", self.robot_id, x, y, theta, epoch)
        return True, "Goal published"

    def cancel_nav_goal(self) -> None:
        if self._goal_cancel_pub is not None:
            msg = self._ros.Bool()
            msg.data = True
            self._goal_cancel_pub.publish(msg)
        self._set_nav_state(status=NAV_CANCELLED, message="Cancelled by operator")

    def pause_nav_goal(self) -> Tuple[bool, str]:
        """Cancel the active goal but remember it so `resume_nav_goal()` can re-send it.

        Nav2 has no native NavigateToPose pause; the standard approach is to
        cancel the action (the robot stops immediately) and re-issue the same
        goal on resume.
        """
        if self._goal_cancel_pub is None:
            return False, "Robot type has no navigation goal topic"
        current = self.get_nav_status().get("goal")
        if current and self.get_nav_status().get("status") not in TERMINAL_NAV_STATES:
            with self._state_lock:
                self._last_goal = {
                    "x": float(current["x"]),
                    "y": float(current["y"]),
                    "theta": float(current.get("theta", 0.0)),
                }
        self.cancel_nav_goal()
        # Override the terminal CANCELLED state: paused is recoverable.
        self._set_nav_state(status=NAV_PAUSED, message="Paused by operator")
        logger.info("%s nav paused", self.robot_id)
        return True, "Goal paused"

    def resume_nav_goal(self) -> Tuple[bool, str]:
        """Re-send the last paused goal (no-op when nothing is paused)."""
        with self._state_lock:
            goal = dict(self._last_goal) if self._last_goal else None
        if goal is None:
            return False, "No paused goal to resume"
        ok, detail = self.send_nav2_goal(goal["x"], goal["y"], goal.get("theta", 0.0))
        if ok:
            with self._state_lock:
                self._last_goal = None
        return ok, detail

    def wait_for_nav_done(self, timeout: float) -> Optional[str]:
        """Block until a terminal nav state arrives. `None` on timeout."""
        if not self._nav_done.wait(timeout=timeout):
            return None
        return self.get_nav_status().get("status")

    def set_initial_pose(self, x: float, y: float, theta: float) -> None:
        if self._initial_pose_pub is None:
            return
        msg = self._ros.PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.position.z = 0.0
        qz, qw = yaw_to_quaternion(theta)
        msg.pose.pose.orientation.z = qz
        msg.pose.pose.orientation.w = qw
        self._initial_pose_pub.publish(msg)
