"""E-stops: the physical button on the robot and the software stop.

* ``stop_active``     robot -> server. TRUE while the physical E-stop button
                      is pressed. The running mission is paused (not failed);
                      when the button is released the robot stays paused
                      until an operator presses Continue.
* ``emergency_stop``  server -> robot. Software E-stop from the dashboard.

Both put the controller in a *safety hold* (`safety_hold()`), which the task
engine checks on every poll tick.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class EmergencyCapability:
    name = "emergency"

    def setup_emergency(self) -> None:
        self._emergency_pub = self.publisher("emergency_stop")
        self.subscribe("stop_active", self._on_stop_active)
        self.stop_active = False
        self.emergency_active = False

    # ---------------- physical button ----------------
    def _on_stop_active(self, msg: Any) -> None:
        active = bool(getattr(msg, "data", False))
        changed = active != self.stop_active
        self.stop_active = active
        if not changed:
            return
        if active:
            logger.warning("%s: physical E-stop PRESSED", self.robot_id)
            self._halt_for_safety("Physical E-stop pressed")
        else:
            logger.warning("%s: physical E-stop released — waiting for operator", self.robot_id)
        self.report_telemetry(stop_active=active)

    # ---------------- software stop ----------------
    def publish_emergency(self, active: bool = True) -> None:
        self.emergency_active = bool(active)
        if self._emergency_pub is not None:
            msg = self.msg("emergency_stop")
            msg.data = bool(active)
            self._emergency_pub.publish(msg)
        if active:
            self._halt_for_safety("Software E-stop engaged")
        logger.warning("Software E-stop %s for %s", "engaged" if active else "released", self.robot_id)
        self.report_telemetry(emergency_active=self.emergency_active)

    # ---------------- shared ----------------
    def _halt_for_safety(self, reason: str) -> None:
        if hasattr(self, "stop"):
            self.stop()
        if hasattr(self, "pause_waypoint") and self.get_nav_status().get("status") == "active":
            self.pause_waypoint(reason)

    def safety_hold(self) -> Optional[str]:
        """Reason the robot must not move, or None."""
        if self.stop_active:
            return "Physical E-stop pressed"
        if self.emergency_active:
            return "Software E-stop engaged"
        return None

    def emergency_snapshot(self) -> Dict[str, Any]:
        return {"safety_hold": self.safety_hold()}
