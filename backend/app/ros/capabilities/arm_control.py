"""Manipulator / gripper control (arm_bot)."""

from __future__ import annotations

from typing import Any, Optional

from app.core.exceptions import ValidationError

GRIPPER_COMMANDS = {"open", "close", "home"}


class ArmControlCapability:
    name = "arm_control"

    def setup_arm_control(self) -> None:
        self._gripper_pub = self.publisher("gripper_command")
        self.subscribe("arm_state", self._on_arm_state)
        self.arm_state: Optional[str] = None

    def _on_arm_state(self, msg: Any) -> None:
        self.arm_state = str(getattr(msg, "data", "") or "")

    def send_gripper_command(self, command: str) -> bool:
        normalized = command.strip().lower()
        if normalized not in GRIPPER_COMMANDS:
            raise ValidationError(f"command must be one of {sorted(GRIPPER_COMMANDS)}")
        if self._gripper_pub is None:
            return False
        msg = self.msg("gripper_command")
        msg.data = normalized
        self._gripper_pub.publish(msg)
        return True

    def arm_control_snapshot(self):
        return {"arm_state": self.arm_state}
