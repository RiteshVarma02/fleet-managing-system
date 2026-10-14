"""Single owner of the ROS 2 lifecycle for the whole process.

Responsibilities:
* `rclpy.init` / `shutdown` exactly once
* one `MultiThreadedExecutor` per node group, spun on daemon threads
* the registry of per-robot controllers (thread-safe), composed by
  `robot_factory` from the capabilities declared in `config/fleet_topics.yaml`
* the shared emergency-stop node (works even when no controller is attached)

V1: every robot is on the same ROS domain, namespaced as /{robot}/...; there
is no domain_bridge and no server-side /map publisher.

Nothing else in the codebase touches `rclpy` state directly.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import RosUnavailableError
from app.core.logging_config import get_logger
from app.ros.registration_listener import build_registration_listener_class
from app.ros.robot_factory import robot_factory
from app.ros.runtime import RosModules, load_ros, message_class, qos_profile, ros_error
from app.ros.topics_registry import default_robot_type, topic_registry

logger = get_logger(__name__)


class _NodeRunner:
    """A node plus the executor thread spinning it."""

    def __init__(self, ros: RosModules, node: Any, name: str) -> None:
        self.node = node
        self._executor = ros.MultiThreadedExecutor()
        self._executor.add_node(node)
        self._thread = threading.Thread(target=self._spin, name=f"ros-{name}", daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except Exception as exc:  # pragma: no cover - shutdown races
            logger.debug("Executor stopped: %s", exc)

    def shutdown(self) -> None:
        try:
            self._executor.shutdown(timeout_sec=2.0)
        except Exception:  # pragma: no cover
            pass
        try:
            self.node.destroy_node()
        except Exception:  # pragma: no cover
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)


class RosManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ros: Optional[RosModules] = None
        self._started = False

        self._controllers: Dict[str, Any] = {}
        self._runners: Dict[str, _NodeRunner] = {}

        self._emergency_runner: Optional[_NodeRunner] = None
        self._emergency_publishers: Dict[str, Any] = {}
        self._registration_runner: Optional[_NodeRunner] = None
        self._registration_cls: Optional[type] = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._ros is not None

    def require_ros(self) -> RosModules:
        if self._ros is None:
            raise RosUnavailableError(ros_error() or "ROS 2 runtime is not initialised")
        return self._ros

    def start(self) -> bool:
        """Initialise rclpy and the shared nodes. Idempotent."""
        with self._lock:
            if self._started:
                return self.available
            self._started = True

            if not settings.ros_enabled:
                logger.warning("ROS integration disabled via ROS_ENABLED=false")
                return False

            ros = load_ros()
            if ros is None:
                return False
            self._ros = ros

            if not ros.rclpy.ok():
                ros.rclpy.init(args=None)

            robot_factory.bind(ros)
            self._registration_cls = build_registration_listener_class(ros)

            emergency_node = ros.rclpy.create_node("emergency_publisher_node")
            self._emergency_runner = _NodeRunner(ros, emergency_node, "emergency")

            logger.info(
                "ROS 2 runtime initialised (fleet domain=%s, topics=%s)",
                settings.ros_domain_id,
                topic_registry.path,
            )
            return True

    def start_registration_listener(
        self, handle: Callable[[str, Optional[str], Optional[str]], Dict[str, Any]]
    ) -> None:
        """`handle` is called from a ROS thread and must be non-blocking-safe."""
        with self._lock:
            if self._registration_runner is not None or self._ros is None:
                return
            node = self._registration_cls(handle=handle)  # type: ignore[misc]
            self._registration_runner = _NodeRunner(self._ros, node, "registration")

    def reload_topics(self) -> Dict[str, Any]:
        """Re-read fleet_topics.yaml. Connected robots pick it up on reconnect."""
        from app.ros.topics_registry import topic_registry as registry

        with self._lock:
            config = registry.reload()
            if self._ros is not None:
                robot_factory.bind(self._ros)
            return {
                "path": str(registry.path),
                "robot_types": sorted(config["robot_types"]),
                "reconnect_required": sorted(self._controllers),
            }

    def shutdown(self) -> None:
        with self._lock:
            for robot_id in list(self._runners):
                self.stop_controller(robot_id)
            for runner in (self._registration_runner, self._emergency_runner):
                if runner:
                    runner.shutdown()
            self._registration_runner = self._emergency_runner = None
            self._emergency_publishers.clear()

            if self._ros is not None:
                try:
                    if self._ros.rclpy.ok():
                        self._ros.rclpy.shutdown()
                except Exception:  # pragma: no cover
                    pass
            self._started = False
            logger.info("ROS 2 runtime shut down")

    # ------------------------------------------------------------------
    # controllers
    # ------------------------------------------------------------------
    def start_controller(self, robot_id: str, robot_type: Optional[str] = None) -> Tuple[bool, str]:
        """Start the per-robot controller node (topics from fleet_topics.yaml)."""
        robot_type = robot_type or default_robot_type()
        with self._lock:
            if robot_id in self._controllers:
                return True, "Already connected"
            if self._ros is None:
                return False, ros_error() or "ROS 2 runtime unavailable"
            try:
                controller = robot_factory.create(robot_id, robot_type)
                self._runners[robot_id] = _NodeRunner(self._ros, controller, robot_id)
                self._controllers[robot_id] = controller
                logger.info("Controller started for %s (type=%s)", robot_id, robot_type)
                return True, "Connected successfully"
            except Exception as exc:
                logger.exception("Failed to start controller for %s", robot_id)
                return False, f"Connection failed: {exc}"

    def stop_controller(self, robot_id: str) -> Tuple[bool, str]:
        with self._lock:
            controller = self._controllers.pop(robot_id, None)
            runner = self._runners.pop(robot_id, None)
        if controller is None and runner is None:
            return True, "Not connected"
        try:
            if controller is not None:
                controller.shutdown()
        except Exception:  # pragma: no cover - best effort
            pass
        if runner is not None:
            runner.shutdown()
        logger.info("Controller stopped for %s", robot_id)
        return True, "Disconnected"

    def get_controller(self, robot_id: str) -> Optional[Any]:
        with self._lock:
            return self._controllers.get(robot_id)

    def connected_robot_ids(self) -> List[str]:
        with self._lock:
            return list(self._controllers)

    # ------------------------------------------------------------------
    # shared publishers
    # ------------------------------------------------------------------
    def publish_emergency(
        self, robot_id: str, value: bool = True, robot_type: Optional[str] = None
    ) -> None:
        """Emergency stop must work even when no controller is attached."""
        ros = self.require_ros()
        rid = str(robot_id).strip()
        if not rid:
            raise ValueError("robot_id is required for emergency publish")

        with self._lock:
            if self._emergency_runner is None:
                raise RosUnavailableError()
            spec = topic_registry.topic(robot_type or default_robot_type(), rid, "emergency_stop")
            if spec is None:
                raise ValueError("Robot type has no 'emergency_stop' topic configured")
            publisher = self._emergency_publishers.get(spec["name"])
            if publisher is None:
                publisher = self._emergency_runner.node.create_publisher(
                    message_class(spec["type"]), spec["name"], qos_profile(ros, spec["qos"])
                )
                self._emergency_publishers[spec["name"]] = publisher

        msg = message_class(spec["type"])()
        msg.data = bool(value)
        publisher.publish(msg)
        logger.info("Published emergency=%s to %s", msg.data, spec["name"])


ros_manager = RosManager()
