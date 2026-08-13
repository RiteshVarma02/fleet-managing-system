"""Teleoperation: `cmd_vel` out, `odom` in."""

from __future__ import annotations

from typing import Any, Dict

from app.ros.runtime import quaternion_to_yaw


class MovementCapability:
    """Provides `move()` / `stop()` and keeps position + velocity state."""

    name = "movement"

    def setup_movement(self) -> None:
        self._cmd_vel_pub = self.publisher("cmd_vel", self._ros.Twist)
        self.subscribe("odom", self._ros.Odometry, self._on_odom, qos=10)

    # ---------------- inbound ----------------
    def _on_odom(self, msg: Any) -> None:
        q = msg.pose.pose.orientation
        position = {
            "x": float(msg.pose.pose.position.x),
            "y": float(msg.pose.pose.position.y),
            "theta": float(quaternion_to_yaw(q.x, q.y, q.z, q.w)),
        }
        velocity = {
            "linear": float(msg.twist.twist.linear.x),
            "angular": float(msg.twist.twist.angular.z),
        }
        with self._state_lock:
            self.current_position = position
            self.current_velocity = velocity
        self.report_telemetry(position=position)

    # ---------------- outbound ----------------
    def move(self, linear: float, angular: float) -> None:
        if self._cmd_vel_pub is None:
            return
        msg = self._ros.Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self._cmd_vel_pub.publish(msg)

    def stop(self) -> None:
        self.move(0.0, 0.0)

    def movement_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return {
                "position": dict(self.current_position),
                "velocity": dict(self.current_velocity),
            }
