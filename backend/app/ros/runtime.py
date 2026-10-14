"""Guarded access to the `rclpy` runtime.

The API must still boot (and its non-ROS endpoints must still work) on a host
without a ROS 2 installation — CI, containers, developer laptops. Every ROS
import goes through this module so a missing installation is a clean 503
instead of an ImportError at startup.

Message classes are NOT imported by name here: they are resolved from the
type strings in `config/fleet_topics.yaml` via `message_class()`, so changing
a topic's type is a config edit, not a code edit.
"""

from __future__ import annotations

import importlib
import math
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RosModules:
    rclpy: Any
    Node: Any
    MultiThreadedExecutor: Any
    ReentrantCallbackGroup: Any
    QoSProfile: Any
    ReliabilityPolicy: Any
    HistoryPolicy: Any
    DurabilityPolicy: Any


_modules: Optional[RosModules] = None
_import_error: Optional[str] = None
_msg_cache: Dict[str, Any] = {}
_msg_lock = threading.Lock()


def load_ros() -> Optional[RosModules]:
    """Import rclpy once. Returns None when unavailable."""
    global _modules, _import_error
    if _modules is not None or _import_error is not None:
        return _modules

    try:
        import rclpy
        from rclpy.callback_groups import ReentrantCallbackGroup
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    except Exception as exc:  # pragma: no cover - depends on host
        _import_error = str(exc)
        logger.warning("ROS 2 runtime unavailable: %s", exc)
        return None

    _modules = RosModules(
        rclpy=rclpy,
        Node=Node,
        MultiThreadedExecutor=MultiThreadedExecutor,
        ReentrantCallbackGroup=ReentrantCallbackGroup,
        QoSProfile=QoSProfile,
        ReliabilityPolicy=ReliabilityPolicy,
        HistoryPolicy=HistoryPolicy,
        DurabilityPolicy=DurabilityPolicy,
    )
    return _modules


def ros_available() -> bool:
    return load_ros() is not None


def ros_error() -> Optional[str]:
    load_ros()
    return _import_error


def message_class(type_name: str) -> Any:
    """`"std_msgs/msg/String"` -> `std_msgs.msg.String` (cached)."""
    with _msg_lock:
        cls = _msg_cache.get(type_name)
        if cls is not None:
            return cls
        try:
            package, kind, name = type_name.split("/")
            cls = getattr(importlib.import_module(f"{package}.{kind}"), name)
        except (ValueError, ImportError, AttributeError) as exc:
            raise ImportError(f"Cannot import ROS message type '{type_name}': {exc}") from exc
        _msg_cache[type_name] = cls
        return cls


def qos_profile(ros: RosModules, profile: str = "default") -> Any:
    """Map the profile names used in fleet_topics.yaml to rclpy QoS objects."""
    if profile == "sensor":
        return ros.QoSProfile(
            depth=1,
            reliability=ros.ReliabilityPolicy.BEST_EFFORT,
            history=ros.HistoryPolicy.KEEP_LAST,
        )
    if profile == "latched":
        return ros.QoSProfile(
            depth=10,
            reliability=ros.ReliabilityPolicy.RELIABLE,
            durability=ros.DurabilityPolicy.TRANSIENT_LOCAL,
            history=ros.HistoryPolicy.KEEP_LAST,
        )
    return ros.QoSProfile(
        depth=10,
        reliability=ros.ReliabilityPolicy.RELIABLE,
        history=ros.HistoryPolicy.KEEP_LAST,
    )


def yaw_to_quaternion(theta: float) -> tuple[float, float]:
    """Return `(z, w)` of the quaternion for a planar yaw."""
    return math.sin(float(theta) / 2.0), math.cos(float(theta) / 2.0)


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)
