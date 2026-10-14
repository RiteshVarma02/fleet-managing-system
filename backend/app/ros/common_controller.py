"""The universal core every robot controller shares.

Owns only what is type-independent: node naming, config-driven publisher /
subscriber creation, shared state and the telemetry hand-off. Waypoint
navigation, safety and every other behaviour is a capability module.

Capabilities never name a ROS topic or message type. They ask for a
*logical* topic (``self.publisher("goal")``) and the name, type and QoS come
from `config/fleet_topics.yaml`. A logical topic the robot type does not
declare yields ``None`` so a capability can degrade gracefully.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from app.core.logging_config import get_logger
from app.ros.runtime import RosModules, message_class, qos_profile
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
            # Node name only; topics are absolute names from the config.
            super().__init__(f"fleet_controller_{robot_id}")
            self.robot_id = robot_id
            self.robot_type = robot_type
            self._ros = ros
            self._topics = resolve_topics(robot_type, robot_id)
            self._callback_group = ros.ReentrantCallbackGroup()
            self._state_lock = threading.RLock()

            self.current_position: Dict[str, float] = {"x": 0.0, "y": 0.0, "theta": 0.0}
            self.current_velocity: Dict[str, float] = {"linear": 0.0, "angular": 0.0}
            self.battery_percentage: Optional[float] = None
            # Monotonic time of the last message received on ANY robot topic;
            # drives online/offline detection.
            self.last_seen: Optional[float] = None

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

            self.report_telemetry(connected=True)
            logger.info(
                "Controller ready: %s (type=%s, capabilities=%s)",
                robot_id,
                robot_type,
                ",".join(self.capability_names),
            )

        # ------------------------------------------------------------------
        # config-driven ROS entities
        # ------------------------------------------------------------------
        def topic_spec(self, logical: str) -> Optional[Dict[str, Any]]:
            return self._topics.get(logical)

        def msg(self, logical: str) -> Any:
            """A new, empty message instance of the configured type."""
            spec = self._topics.get(logical)
            if spec is None:
                raise KeyError(f"{self.robot_type} has no topic '{logical}'")
            return message_class(spec["type"])()

        def publisher(self, logical: str) -> Optional[Any]:
            spec = self._topics.get(logical)
            if spec is None:
                return None
            return self.create_publisher(
                message_class(spec["type"]), spec["name"], qos_profile(self._ros, spec["qos"])
            )

        def subscribe(self, logical: str, callback: Callable[[Any], None]) -> Optional[Any]:
            spec = self._topics.get(logical)
            if spec is None:
                return None

            def _wrapped(msg: Any) -> None:
                self.mark_seen()
                callback(msg)

            return self.create_subscription(
                message_class(spec["type"]),
                spec["name"],
                _wrapped,
                qos_profile(self._ros, spec["qos"]),
                callback_group=self._callback_group,
            )

        def has_capability(self, capability: str) -> bool:
            return capability in self.capability_names

        def topic_map(self) -> Dict[str, str]:
            return {logical: spec["name"] for logical, spec in self._topics.items()}

        # ------------------------------------------------------------------
        # liveness + telemetry hand-off (never writes to Mongo from a ROS thread)
        # ------------------------------------------------------------------
        def mark_seen(self) -> None:
            now = time.monotonic()
            with self._state_lock:
                first = self.last_seen is None
                self.last_seen = now
            if first:
                self.report_telemetry(seen=True)

        def seconds_since_seen(self) -> Optional[float]:
            with self._state_lock:
                if self.last_seen is None:
                    return None
                return time.monotonic() - self.last_seen

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
                    "seconds_since_seen": (
                        None if self.last_seen is None else time.monotonic() - self.last_seen
                    ),
                }
            data["nav"] = self.get_nav_status() if self.has_capability("waypoint_nav") else None
            data["stop_active"] = bool(getattr(self, "stop_active", False))
            data["emergency_active"] = bool(getattr(self, "emergency_active", False))
            for capability in self.capability_names:
                extra = getattr(self, f"{capability}_snapshot", None)
                if callable(extra):
                    data.update(extra())
            return data

        # A robot without the movement capability still needs a safe `stop()`.
        def stop(self) -> None:  # pragma: no cover - overridden by MovementCapability
            return None

        def shutdown(self) -> None:
            try:
                self.stop()
            except Exception:  # pragma: no cover - best effort
                pass
            telemetry_bus.publish(self.robot_id, connected=False)

    return BaseRobotController


__all__ = ["build_base_controller_class", "capabilities_for"]
