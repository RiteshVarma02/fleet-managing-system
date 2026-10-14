"""Composes a controller class from the common controller + capability mixins.

Classes are built once per (robot_type) and cached: connecting the 21st robot
costs one node, not one class construction.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Type

from app.core.logging_config import get_logger
from app.ros.capabilities import CAPABILITY_REGISTRY
from app.ros.common_controller import build_base_controller_class
from app.ros.runtime import RosModules
from app.ros.topics_registry import capabilities_for, default_robot_type, is_known_type

logger = get_logger(__name__)


class RobotFactory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._base: Optional[Type] = None
        self._classes: Dict[str, Type] = {}

    def bind(self, ros: RosModules) -> None:
        with self._lock:
            # Also called after a topic-config reload: rebuild every class.
            self._base = build_base_controller_class(ros)
            self._classes.clear()

    def controller_class(self, robot_type: str) -> Type:
        if self._base is None:
            raise RuntimeError("RobotFactory.bind() must be called after rclpy init")

        # An unknown type falls back to the default rather than failing connect.
        resolved_type = robot_type if is_known_type(robot_type) else default_robot_type()

        with self._lock:
            cached = self._classes.get(resolved_type)
            if cached is not None:
                return cached

            capabilities = capabilities_for(resolved_type)
            mixins = []
            for name in capabilities:
                mixin = CAPABILITY_REGISTRY.get(name)
                if mixin is None:
                    logger.error("Unknown capability '%s' for robot type '%s'", name, resolved_type)
                    continue
                mixins.append(mixin)

            # Mixins first so their methods win over the base defaults.
            cls = type(
                f"RobotController_{resolved_type}",
                (*mixins, self._base),
                {"capability_names": tuple(capabilities)},
            )
            self._classes[resolved_type] = cls
            return cls

    def create(self, robot_id: str, robot_type: str):
        return self.controller_class(robot_type)(robot_id, robot_type)


robot_factory = RobotFactory()
