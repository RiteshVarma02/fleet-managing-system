"""Emergency stop — the lowest-latency path in the system.

The publisher lives on the persistent controller node so an e-stop never waits
on MongoDB or a fresh ROS entity.
"""

from __future__ import annotations

from typing import Any

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class EmergencyCapability:
    name = "emergency"

    def setup_emergency(self) -> None:
        self._emergency_pub = self.publisher("emergency_stop", self._ros.Bool)
        self.subscribe("emergency_stop", self._ros.Bool, self._on_emergency, qos=10)
        self.emergency_active = False

    def publish_emergency(self, active: bool = True) -> None:
        if self._emergency_pub is None:
            return
        msg = self._ros.Bool()
        msg.data = bool(active)
        self._emergency_pub.publish(msg)
        if active and hasattr(self, "stop"):
            self.stop()
        logger.warning("Emergency stop %s for %s", "engaged" if active else "released", self.robot_id)

    def _on_emergency(self, msg: Any) -> None:
        active = bool(getattr(msg, "data", False))
        self.emergency_active = active
        if not active:
            return
        if hasattr(self, "stop"):
            self.stop()
        if hasattr(self, "cancel_nav_goal"):
            self.cancel_nav_goal()
        self.report_telemetry(status="error")
