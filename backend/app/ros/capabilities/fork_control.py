"""Fork-lift mast control (forklift_bot)."""

from __future__ import annotations

from typing import Any, Optional


class ForkControlCapability:
    name = "fork_control"

    MIN_HEIGHT_M = 0.0
    MAX_HEIGHT_M = 3.0

    def setup_fork_control(self) -> None:
        self._fork_pub = self.publisher("fork_command", self._ros.Float32)
        self.subscribe("fork_height", self._ros.Float32, self._on_fork_height, qos=10)
        self.fork_height: Optional[float] = None

    def _on_fork_height(self, msg: Any) -> None:
        self.fork_height = float(getattr(msg, "data", 0.0) or 0.0)

    def set_fork_height(self, height_m: float) -> float:
        """Clamp then publish. Returns the commanded height."""
        target = max(self.MIN_HEIGHT_M, min(self.MAX_HEIGHT_M, float(height_m)))
        if self._fork_pub is not None:
            msg = self._ros.Float32()
            msg.data = target
            self._fork_pub.publish(msg)
        return target

    def lift(self) -> float:
        return self.set_fork_height(self.MAX_HEIGHT_M)

    def lower(self) -> float:
        return self.set_fork_height(self.MIN_HEIGHT_M)
