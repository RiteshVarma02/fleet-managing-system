"""Teleoperation: `cmd_vel` out (and `odom` in, when the type declares it)."""

from __future__ import annotations

from typing import Any


class MovementCapability:
    """Provides `move()` / `stop()`."""

    name = "movement"

    def setup_movement(self) -> None:
        self._cmd_vel_pub = self.publisher("cmd_vel")
        self.subscribe("odom", self._on_odom)  # optional: None if not configured

    def _on_odom(self, msg: Any) -> None:
        velocity = {
            "linear": float(msg.twist.twist.linear.x),
            "angular": float(msg.twist.twist.angular.z),
        }
        with self._state_lock:
            self.current_velocity = velocity

    def move(self, linear: float, angular: float) -> None:
        if self._cmd_vel_pub is None:
            return
        msg = self.msg("cmd_vel")
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self._cmd_vel_pub.publish(msg)
        with self._state_lock:
            self.current_velocity = {"linear": float(linear), "angular": float(angular)}

    def stop(self) -> None:
        self.move(0.0, 0.0)
