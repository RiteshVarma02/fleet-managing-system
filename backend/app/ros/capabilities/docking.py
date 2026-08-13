"""Charging-dock control for bases that have a dock."""

from __future__ import annotations

from typing import Any, Optional


class DockingCapability:
    name = "docking"

    def setup_docking(self) -> None:
        self._dock_pub = self.publisher("dock_command", self._ros.String)
        self.subscribe("dock_state", self._ros.String, self._on_dock_state, qos=10)
        self.dock_state: Optional[str] = None

    def _on_dock_state(self, msg: Any) -> None:
        self.dock_state = str(getattr(msg, "data", "") or "")

    def _send_dock_command(self, command: str) -> bool:
        if self._dock_pub is None:
            return False
        msg = self._ros.String()
        msg.data = command
        self._dock_pub.publish(msg)
        return True

    def dock(self) -> bool:
        return self._send_dock_command("dock")

    def undock(self) -> bool:
        return self._send_dock_command("undock")
