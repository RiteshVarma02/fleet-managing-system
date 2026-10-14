"""Pose (localisation) and battery — the state every robot reports."""

from __future__ import annotations

from typing import Any, Dict

from app.ros.runtime import quaternion_to_yaw


class TelemetryCapability:
    name = "telemetry"

    def setup_telemetry(self) -> None:
        self.subscribe("pose", self._on_pose)
        self.subscribe("battery", self._on_battery)
        self.localized = False

    def _on_pose(self, msg: Any) -> None:
        pose = msg.pose.pose
        q = pose.orientation
        position = {
            "x": float(pose.position.x),
            "y": float(pose.position.y),
            "theta": float(quaternion_to_yaw(q.x, q.y, q.z, q.w)),
        }
        with self._state_lock:
            self.current_position = position
            self.localized = True
        self.report_telemetry(position=position)

    def _on_battery(self, msg: Any) -> None:
        percentage = float(getattr(msg, "percentage", 0.0) or 0.0)
        # ROS publishes 0..1; tolerate drivers that already send 0..100.
        if percentage <= 1.0:
            percentage *= 100.0
        percentage = max(0.0, min(100.0, percentage))
        with self._state_lock:
            self.battery_percentage = percentage
        self.report_telemetry(battery=percentage)

    def telemetry_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return {"localized": self.localized}
