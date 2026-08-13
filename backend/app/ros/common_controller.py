"""The universal core every robot controller shares.

Owns only what is type-independent: node naming, registry-driven publisher /
subscriber creation, shared state and the telemetry hand-off. Movement,
navigation and every other behaviour is a capability module.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from app.core.logging_config import get_logger
from app.ros.runtime import RosModules, sensor_qos
from app.ros.topics_registry import capabilities_for, resolve_topics
from app.services.telemetry_bus import telemetry_bus

logger = get_logger(__name__)


def build_base_controller_class(ros: RosModules):
    """Create the base class bound to the imported ROS modules.

    Building it lazily keeps `rclpy` out of import time so the service starts on
    hosts without ROS installed.
    """

    class BaseRobotController(ros.Node):  # type: ignore[misc, valid-type]
        capability_names: tuple[str, ...] = ()

        def __init__(self, robot_id: str, robot_type: str) -> None:
            super().__init__(f"robot_controller_{robot_id}")
            self.robot_id = robot_id
            self.robot_type = robot_type
            self._ros = ros
            self._topics = resolve_topics(robot_type, robot_id)
            self._callback_group = ros.ReentrantCallbackGroup()
            self._state_lock = threading.RLock()

            self.current_position: Dict[str, float] = {"x": 0.0, "y": 0.0, "theta": 0.0}
            self.current_velocity: Dict[str, float] = {"linear": 0.0, "angular": 0.0}
            self.battery_percentage: float = 100.0

            for capability in self.capability_names:
                setup = getattr(self, f"setup_{capability}", None)
                if setup is None:
                    logger.warning(
                        "Capability '%s' has no setup_%s() — skipped for %s",
                        capability,
                        capability,
                        robot_id,
                    )
                    continue
                setup()

            self.report_telemetry(status="online")
            logger.info(
                "Controller ready: %s (type=%s, capabilities=%s)",
                robot_id,
                robot_type,
                ",".join(self.capability_names),
            )

        # ------------------------------------------------------------------
        # registry-driven ROS entities
        # ------------------------------------------------------------------
        def publisher(self, logical: str, msg_type: Any, qos: int = 10) -> Optional[Any]:
            topic = self._topics.get(logical)
            if topic is None:
                return None
            return self.create_publisher(msg_type, topic["server"], qos)

        def subscribe(
            self,
            logical: str,
            msg_type: Any,
            callback: Callable[[Any], None],
            *,
            qos: int = 10,
            best_effort: bool = False,
        ) -> Optional[Any]:
            topic = self._topics.get(logical)
            if topic is None:
                return None
            profile: Any = sensor_qos(self._ros, depth=qos) if best_effort else qos
            return self.create_subscription(
                msg_type,
                topic["server"],
                callback,
                profile,
                callback_group=self._callback_group,
            )

        def has_capability(self, capability: str) -> bool:
            return capability in self.capability_names

        def topic_map(self) -> Dict[str, str]:
            return {logical: spec["server"] for logical, spec in self._topics.items()}

        # ------------------------------------------------------------------
        # telemetry hand-off (never writes to Mongo from a ROS thread)
        # ------------------------------------------------------------------
        def report_telemetry(self, **fields: Any) -> None:
            telemetry_bus.publish(self.robot_id, **fields)

        # ------------------------------------------------------------------
        # snapshot consumed by the API layer
        # ------------------------------------------------------------------
        def snapshot(self) -> Dict[str, Any]:
            with self._state_lock:
                data: Dict[str, Any] = {
                    "robot_id": self.robot_id,
                    "robot_type": self.robot_type,
                    "capabilities": list(self.capability_names),
                    "position": dict(self.current_position),
                    "velocity": dict(self.current_velocity),
                    "battery": self.battery_percentage,
                }
            data["nav"] = self.get_nav_status() if self.has_capability("navigation") else None
            if self.has_capability("docking"):
                data["dock_state"] = getattr(self, "dock_state", None)
            if self.has_capability("fork_control"):
                data["fork_height"] = getattr(self, "fork_height", None)
            if self.has_capability("arm_control"):
                data["arm_state"] = getattr(self, "arm_state", None)
            data["emergency_active"] = bool(getattr(self, "emergency_active", False))
            return data

        # A robot without the movement capability still needs a safe `stop()`.
        def stop(self) -> None:  # pragma: no cover - overridden by MovementCapability
            return None

        def shutdown(self) -> None:
            try:
                self.stop()
            except Exception:  # pragma: no cover - best effort
                pass
            telemetry_bus.publish(self.robot_id, status="offline")

    return BaseRobotController


__all__ = ["build_base_controller_class", "capabilities_for"]
