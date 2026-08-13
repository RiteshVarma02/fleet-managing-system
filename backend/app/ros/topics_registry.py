"""THE single file to edit when wiring a new robot model.

Every robot *type* declares:

* `topics`   — the logical topic contract. Each entry carries the ROS message
               type, the name on the **robot** domain, the name on the
               **server** domain, and the bridge `direction`:
                 * ``up``   robot domain -> server domain (sensors / state)
                 * ``down`` server domain -> robot domain (commands)
* `actions`  — long-running actions. Actions are NOT bridged across domains;
               they are driven on the robot side by `robot_action_forwarder.py`
               through a goal topic + a status topic (see `deploy/`).
* `capabilities` — the capability modules (`ros/capabilities/*.py`) the type is
               composed from.

Onboarding a new model = add one entry here (+ a new capability module only if
the behaviour genuinely does not exist yet). No existing file is edited.
"""

from __future__ import annotations

from typing import Any, Dict, List

UP = "up"
DOWN = "down"

# --- reusable topic groups -------------------------------------------------
_STATE_TOPICS: Dict[str, Dict[str, Any]] = {
    "odom": {
        "type": "nav_msgs/msg/Odometry",
        "robot": "/odom",
        "server": "/{robot_id}/odom",
        "direction": UP,
    },
    "scan": {
        "type": "sensor_msgs/msg/LaserScan",
        "robot": "/scan",
        "server": "/{robot_id}/scan",
        "direction": UP,
    },
    "amcl_pose": {
        "type": "geometry_msgs/msg/PoseWithCovarianceStamped",
        "robot": "/amcl_pose",
        "server": "/{robot_id}/amcl_pose",
        "direction": UP,
    },
    "battery_state": {
        "type": "sensor_msgs/msg/BatteryState",
        "robot": "/battery_state",
        "server": "/{robot_id}/battery_state",
        "direction": UP,
    },
    "navigation_status": {
        "type": "std_msgs/msg/String",
        "robot": "/navigation_status",
        "server": "/{robot_id}/navigation_status",
        "direction": UP,
    },
    "tf": {
        "type": "tf2_msgs/msg/TFMessage",
        "robot": "/tf",
        "server": "/{robot_id}/tf",
        "direction": UP,
    },
    "tf_static": {
        "type": "tf2_msgs/msg/TFMessage",
        "robot": "/tf_static",
        "server": "/{robot_id}/tf_static",
        "direction": UP,
    },
    "map": {
        "type": "nav_msgs/msg/OccupancyGrid",
        "robot": "/map",
        "server": "/{robot_id}/map",
        "direction": UP,
    },
}

_COMMAND_TOPICS: Dict[str, Dict[str, Any]] = {
    "cmd_vel": {
        "type": "geometry_msgs/msg/Twist",
        "robot": "/cmd_vel",
        "server": "/{robot_id}/cmd_vel",
        "direction": DOWN,
    },
    "goal_request": {
        "type": "geometry_msgs/msg/PoseStamped",
        "robot": "/goal_request",
        "server": "/{robot_id}/goal_request",
        "direction": DOWN,
    },
    "goal_cancel": {
        "type": "std_msgs/msg/Bool",
        "robot": "/goal_cancel",
        "server": "/{robot_id}/goal_cancel",
        "direction": DOWN,
    },
    "initial_pose": {
        "type": "geometry_msgs/msg/PoseWithCovarianceStamped",
        "robot": "/initialpose",
        "server": "/{robot_id}/initialpose",
        "direction": DOWN,
    },
    "emergency_stop": {
        "type": "std_msgs/msg/Bool",
        "robot": "/emergency_stop",
        "server": "/{robot_id}/emergency_stop",
        "direction": DOWN,
    },
}

_DOCK_TOPICS: Dict[str, Dict[str, Any]] = {
    "dock_command": {
        "type": "std_msgs/msg/String",
        "robot": "/dock_command",
        "server": "/{robot_id}/dock_command",
        "direction": DOWN,
    },
    "dock_state": {
        "type": "std_msgs/msg/String",
        "robot": "/dock_state",
        "server": "/{robot_id}/dock_state",
        "direction": UP,
    },
}


def _topics(*groups: Dict[str, Dict[str, Any]], **extra: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for group in groups:
        merged.update({key: dict(value) for key, value in group.items()})
    merged.update(extra)
    return merged


ROBOT_TYPE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "differential_drive": {
        "description": "Standard Nav2 AMR with lidar and a charging dock.",
        "capabilities": ["movement", "navigation", "telemetry", "emergency", "docking"],
        "topics": _topics(_STATE_TOPICS, _COMMAND_TOPICS, _DOCK_TOPICS),
    },
    "forklift_bot": {
        "description": "AMR with a fork-lift mast.",
        "capabilities": [
            "movement",
            "navigation",
            "telemetry",
            "emergency",
            "docking",
            "fork_control",
        ],
        "topics": _topics(
            _STATE_TOPICS,
            _COMMAND_TOPICS,
            _DOCK_TOPICS,
            fork_command={
                "type": "std_msgs/msg/Float32",
                "robot": "/fork_lift_cmd",
                "server": "/{robot_id}/fork_lift_cmd",
                "direction": DOWN,
            },
            fork_height={
                "type": "std_msgs/msg/Float32",
                "robot": "/fork_height",
                "server": "/{robot_id}/fork_height",
                "direction": UP,
            },
        ),
    },
    "arm_bot": {
        "description": "Mobile base with a manipulator arm.",
        "capabilities": ["movement", "navigation", "telemetry", "emergency", "arm_control"],
        "topics": _topics(
            _STATE_TOPICS,
            _COMMAND_TOPICS,
            gripper_command={
                "type": "std_msgs/msg/String",
                "robot": "/gripper_cmd",
                "server": "/{robot_id}/gripper_cmd",
                "direction": DOWN,
            },
            arm_state={
                "type": "std_msgs/msg/String",
                "robot": "/arm_state",
                "server": "/{robot_id}/arm_state",
                "direction": UP,
            },
        ),
    },
}

DEFAULT_ROBOT_TYPE = "differential_drive"


def robot_types() -> List[str]:
    return sorted(ROBOT_TYPE_REGISTRY)


def type_spec(robot_type: str) -> Dict[str, Any]:
    return ROBOT_TYPE_REGISTRY.get(robot_type) or ROBOT_TYPE_REGISTRY[DEFAULT_ROBOT_TYPE]


def capabilities_for(robot_type: str) -> List[str]:
    return list(type_spec(robot_type)["capabilities"])


def resolve_topics(robot_type: str, robot_id: str) -> Dict[str, Dict[str, Any]]:
    """Concrete topic contract for one robot instance."""
    resolved: Dict[str, Dict[str, Any]] = {}
    for logical, spec in type_spec(robot_type)["topics"].items():
        resolved[logical] = {
            **spec,
            "server": spec["server"].format(robot_id=robot_id),
            "robot": spec["robot"].format(robot_id=robot_id),
        }
    return resolved


def server_topic(robot_type: str, robot_id: str, logical: str) -> str:
    topic = resolve_topics(robot_type, robot_id).get(logical)
    if topic is None:
        raise KeyError(f"Robot type '{robot_type}' does not declare topic '{logical}'")
    return topic["server"]


def has_topic(robot_type: str, logical: str) -> bool:
    return logical in type_spec(robot_type)["topics"]
