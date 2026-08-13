"""One module per capability — never one module per robot type.

A robot's controller class is assembled at connect time from
`common_controller.BaseRobotController` plus every mixin listed for its type in
`topics_registry.ROBOT_TYPE_REGISTRY`.
"""

from __future__ import annotations

from typing import Dict, Type

from app.ros.capabilities.arm_control import ArmControlCapability
from app.ros.capabilities.docking import DockingCapability
from app.ros.capabilities.emergency import EmergencyCapability
from app.ros.capabilities.fork_control import ForkControlCapability
from app.ros.capabilities.movement import MovementCapability
from app.ros.capabilities.navigation import NavigationCapability
from app.ros.capabilities.telemetry import TelemetryCapability

CAPABILITY_REGISTRY: Dict[str, Type] = {
    "movement": MovementCapability,
    "navigation": NavigationCapability,
    "telemetry": TelemetryCapability,
    "emergency": EmergencyCapability,
    "docking": DockingCapability,
    "fork_control": ForkControlCapability,
    "arm_control": ArmControlCapability,
}

__all__ = ["CAPABILITY_REGISTRY"]
