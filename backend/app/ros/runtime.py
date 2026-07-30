"""Guarded access to the `rclpy` runtime.

The API must still boot (and its non-ROS endpoints must still work) on a host
without a ROS 2 installation — CI, containers, developer laptops. Every ROS
import goes through this module so a missing installation is a clean 503
instead of an ImportError at startup.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RosModules:
    rclpy: Any
    Node: Any
    MultiThreadedExecutor: Any
    Twist: Any
    PoseStamped: Any
    PoseWithCovarianceStamped: Any
    OccupancyGrid: Any
    Odometry: Any
    LaserScan: Any
    BatteryState: Any
    Bool: Any
    String: Any


_modules: Optional[RosModules] = None
_import_error: Optional[str] = None


def load_ros() -> Optional[RosModules]:
    """Import rclpy + message types once. Returns None when unavailable."""
    global _modules, _import_error
    if _modules is not None or _import_error is not None:
        return _modules

    try:
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
        from nav_msgs.msg import OccupancyGrid, Odometry
        from sensor_msgs.msg import BatteryState, LaserScan
        from std_msgs.msg import Bool, String
    except Exception as exc:  # pragma: no cover - depends on host
        _import_error = str(exc)
        logger.warning("ROS 2 runtime unavailable: %s", exc)
        return None

    _modules = RosModules(
        rclpy=rclpy,
        Node=Node,
        MultiThreadedExecutor=MultiThreadedExecutor,
        Twist=Twist,
        PoseStamped=PoseStamped,
        PoseWithCovarianceStamped=PoseWithCovarianceStamped,
        OccupancyGrid=OccupancyGrid,
        Odometry=Odometry,
        LaserScan=LaserScan,
        BatteryState=BatteryState,
        Bool=Bool,
        String=String,
    )
    return _modules


def ros_available() -> bool:
    return load_ros() is not None


def ros_error() -> Optional[str]:
    load_ros()
    return _import_error


def yaw_to_quaternion(theta: float) -> tuple[float, float]:
    """Return `(z, w)` of the quaternion for a planar yaw."""
    return math.sin(float(theta) / 2.0), math.cos(float(theta) / 2.0)


def quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)
