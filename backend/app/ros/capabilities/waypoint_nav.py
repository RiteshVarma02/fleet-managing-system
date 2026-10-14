"""Waypoint navigation through the robot's route_manager (no Nav2).

Same interface `mission_commander.py` uses on the robot:

* ``goal``          publish the waypoint NAME (std_msgs/String) to dispatch a leg
* ``goal_reached``  TRUE on real arrival (route_manager's *filtered* signal;
                    the raw ``amr/goal_reached`` also fires at traffic waits)
* ``route_abort``   an EMPTY nav_msgs/Path halts the robot in place

Topic names/types come from `config/fleet_topics.yaml`.

`goal_reached` carries no goal id, so a late TRUE from the previous leg could
end the current one. `WaypointTracker` guards against that with an epoch per
goal plus a short debounce window after each send.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

NAV_IDLE = "idle"
NAV_ACTIVE = "active"
NAV_SUCCEEDED = "succeeded"
NAV_FAILED = "failed"
NAV_CANCELLED = "cancelled"
NAV_PAUSED = "paused"

TERMINAL_NAV_STATES = {NAV_SUCCEEDED, NAV_FAILED, NAV_CANCELLED}


class WaypointTracker:
    """Pure state machine for one robot's current leg (no ROS; unit-tested)."""

    def __init__(
        self,
        debounce_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._debounce = max(0.0, float(debounce_seconds))
        self._clock = clock
        self._lock = threading.RLock()
        self._epoch = 0
        self._sent_at = 0.0
        self._state: Dict[str, Any] = {
            "status": NAV_IDLE,
            "goal": None,
            "message": None,
            "epoch": 0,
            "updated_at": time.time(),
        }
        self._paused_goal: Optional[str] = None
        self.done = threading.Event()
        self.done.set()

    def _set(self, **fields: Any) -> Dict[str, Any]:
        self._state.update(fields)
        self._state["updated_at"] = time.time()
        if self._state["status"] in TERMINAL_NAV_STATES:
            self.done.set()
        return dict(self._state)

    def start(self, waypoint: str) -> int:
        with self._lock:
            self._epoch += 1
            self._sent_at = self._clock()
            self._paused_goal = None
            self.done.clear()
            self._set(status=NAV_ACTIVE, goal=waypoint, message=f"Going to {waypoint}", epoch=self._epoch)
            return self._epoch

    def on_reached(self, reached: bool) -> bool:
        """Feed one `goal_reached` sample. True when it completed the current leg."""
        with self._lock:
            if not reached or self._state["status"] != NAV_ACTIVE:
                return False
            if self._clock() - self._sent_at < self._debounce:
                logger.debug("Ignoring goal_reached inside debounce window (stale)")
                return False
            self._set(status=NAV_SUCCEEDED, message=f"Arrived at {self._state['goal']}")
            return True

    def cancel(self, message: str = "Cancelled") -> Dict[str, Any]:
        with self._lock:
            return self._set(status=NAV_CANCELLED, message=message)

    def fail(self, message: str) -> Dict[str, Any]:
        with self._lock:
            return self._set(status=NAV_FAILED, message=message)

    def pause(self, message: str = "Paused") -> Optional[str]:
        """Remember the active goal and mark paused. Returns the goal, if any."""
        with self._lock:
            if self._state["status"] == NAV_ACTIVE:
                self._paused_goal = self._state["goal"]
            self._set(status=NAV_PAUSED, message=message)
            # A pause must release anyone waiting for a terminal state.
            self.done.set()
            return self._paused_goal

    def paused_goal(self) -> Optional[str]:
        with self._lock:
            return self._paused_goal

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)


class WaypointNavCapability:
    name = "waypoint_nav"

    def setup_waypoint_nav(self) -> None:
        self._goal_pub = self.publisher("goal")
        self._route_abort_pub = self.publisher("route_abort")
        self.subscribe("goal_reached", self._on_goal_reached)
        self._tracker = WaypointTracker(settings.waypoint_arrival_debounce_seconds)

    # ---------------- inbound ----------------
    def _on_goal_reached(self, msg: Any) -> None:
        if self._tracker.on_reached(bool(getattr(msg, "data", False))):
            logger.info("%s arrived at %s", self.robot_id, self._tracker.status().get("goal"))
            self.report_telemetry(nav=self._tracker.status())

    # ---------------- commands ----------------
    def send_waypoint(self, waypoint_name: str) -> Tuple[bool, str]:
        if self._goal_pub is None:
            return False, f"Robot type '{self.robot_type}' has no 'goal' topic"
        name = str(waypoint_name).strip()
        if not name:
            return False, "Waypoint name is empty"
        msg = self.msg("goal")
        msg.data = name
        epoch = self._tracker.start(name)
        self._goal_pub.publish(msg)
        self.report_telemetry(nav=self._tracker.status())
        logger.info("%s -> waypoint '%s' [epoch %d]", self.robot_id, name, epoch)
        return True, f"Dispatched to {name}"

    def _publish_route_abort(self) -> None:
        if self._route_abort_pub is None:
            return
        msg = self.msg("route_abort")
        header = getattr(msg, "header", None)
        if header is not None:
            header.frame_id = "map"
            header.stamp = self.get_clock().now().to_msg()
        self._route_abort_pub.publish(msg)

    def abort_waypoint(self, message: str = "Aborted by operator") -> None:
        self._publish_route_abort()
        self._tracker.cancel(message)
        self.report_telemetry(nav=self._tracker.status())
        logger.warning("%s route aborted: %s", self.robot_id, message)

    def pause_waypoint(self, message: str = "Paused by operator") -> Tuple[bool, str]:
        """Halt in place but remember the goal so it can be re-sent."""
        if self._route_abort_pub is None:
            return False, f"Robot type '{self.robot_type}' has no 'route_abort' topic"
        self._publish_route_abort()
        self._tracker.pause(message)
        self.report_telemetry(nav=self._tracker.status())
        return True, message

    def resume_waypoint(self) -> Tuple[bool, str]:
        goal = self._tracker.paused_goal()
        if not goal:
            return False, "No paused waypoint to resume"
        return self.send_waypoint(goal)

    def get_nav_status(self) -> Dict[str, Any]:
        return self._tracker.status()

    def wait_for_nav_done(self, timeout: float) -> Optional[str]:
        if not self._tracker.done.wait(timeout=timeout):
            return None
        return self._tracker.status().get("status")
