"""fleet_topics.yaml is the single source of truth for topic names/types."""

from __future__ import annotations

import pytest

from app.ros import topics_registry as tr

SHIPPED = tr.load_config(tr.settings.fleet_topics_file)


def _registry(config):
    reg = tr.TopicRegistry()
    reg.use_config(config)
    return reg


def _base(**robot_types):
    return {
        "default_robot_type": "base",
        "robot_types": {
            "base": {
                "capabilities": ["waypoint_nav", "telemetry"],
                "topics": {
                    "goal": {"name": "/{robot}/amr/goal", "type": "std_msgs/msg/String"},
                    "pose": {
                        "name": "/{robot}/amcl_pose",
                        "type": "geometry_msgs/msg/PoseWithCovarianceStamped",
                        "qos": "latched",
                    },
                },
            },
            **robot_types,
        },
    }


def test_shipped_config_defines_the_waypoint_interface():
    reg = _registry(SHIPPED)
    topics = reg.resolve_topics("waypoint_amr", "robot1")
    assert topics["goal"] == {"name": "/robot1/amr/goal", "type": "std_msgs/msg/String", "qos": "default"}
    assert topics["goal_reached"]["name"] == "/robot1/amr/final_goal_reached"
    assert topics["route_abort"]["type"] == "nav_msgs/msg/Path"
    assert topics["stop_active"]["name"] == "/robot1/stop_active"
    assert topics["pose"]["qos"] == "latched"
    assert reg.default_robot_type == "waypoint_amr"
    assert reg.fleet_topic("registration")["name"] == "/robot/register"


def test_every_topic_is_namespaced_by_robot():
    reg = _registry(SHIPPED)
    for robot_type in reg.robot_types():
        for spec in reg.resolve_topics(robot_type, "kumki").values():
            assert spec["name"].startswith("/kumki/"), spec


def test_renaming_a_topic_is_a_config_change_only():
    config = _base()
    config["robot_types"]["base"]["topics"]["goal"]["name"] = "/{robot}/custom/goal"
    reg = _registry(tr.parse_config(config))
    assert reg.topic("base", "r2", "goal")["name"] == "/r2/custom/goal"


def test_extends_inherits_adds_and_removes():
    config = tr.parse_config(
        _base(
            forklift={
                "extends": "base",
                "capabilities": ["fork_control"],
                "topics": {
                    "fork_command": {"name": "/{robot}/fork", "type": "std_msgs/msg/Float32"},
                    "pose": None,
                },
            }
        )
    )
    reg = _registry(config)
    assert reg.capabilities_for("forklift") == ["waypoint_nav", "telemetry", "fork_control"]
    topics = reg.resolve_topics("forklift", "f1")
    assert topics["goal"]["name"] == "/f1/amr/goal"
    assert topics["fork_command"]["name"] == "/f1/fork"
    assert "pose" not in topics


def test_unknown_type_falls_back_to_default():
    reg = _registry(tr.parse_config(_base()))
    assert reg.capabilities_for("does_not_exist") == ["waypoint_nav", "telemetry"]


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda c: c["robot_types"]["base"]["topics"]["goal"].update(type="String"), "pkg/msg/Name"),
        (lambda c: c["robot_types"]["base"]["topics"]["goal"].update(name="amr/goal"), "absolute"),
        (lambda c: c["robot_types"]["base"]["topics"]["goal"].update(qos="fast"), "qos"),
        (lambda c: c.update(default_robot_type="nope"), "default_robot_type"),
        (lambda c: c["robot_types"]["base"].update(extends="base"), "cycle"),
    ],
)
def test_bad_config_is_rejected_with_a_clear_message(mutate, message):
    config = _base()
    mutate(config)
    with pytest.raises(tr.TopicConfigError, match=message):
        tr.parse_config(config)


@pytest.mark.parametrize("bad_id", ["1robot", "robot-1", "", "a/b"])
def test_robot_id_must_be_a_ros_namespace(bad_id):
    reg = _registry(SHIPPED)
    with pytest.raises(tr.TopicConfigError):
        reg.resolve_topics("waypoint_amr", bad_id)


def test_reload_keeps_old_config_when_file_is_broken(tmp_path):
    good = tmp_path / "topics.yaml"
    good.write_text(tr.settings.fleet_topics_file.read_text())
    reg = tr.TopicRegistry(good)
    assert "waypoint_amr" in reg.robot_types()
    good.write_text("robot_types: [")
    with pytest.raises(tr.TopicConfigError):
        reg.reload()
    assert "waypoint_amr" in reg.robot_types()
