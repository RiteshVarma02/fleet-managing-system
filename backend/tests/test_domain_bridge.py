"""Domain bridge config tests.

`build_bridge_config` / `write_bridge_config` turn the topic registry into the
`domain_bridge` YAML for one robot. The focus is the map-share flag added in M4:
sharing the fleet's `/map` down to a robot must add exactly one DOWN topic whose
key `/map` does not collide with the robot's own UP `/map` entry (key `map`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import app.ros.domain_bridge as db
from app.ros.topics_registry import resolve_topics

SERVER_DOMAIN = 0
ROBOT_DOMAIN = 2


class _FakeSettings:
    ros_domain_id = SERVER_DOMAIN
    domain_bridge_config_dir: Path = Path("/tmp/nonexistent-bridges")
    domain_bridge_default_robot_domain = ROBOT_DOMAIN
    domain_bridge_enabled = True
    domain_bridge_command = ["ros2", "run", "domain_bridge", "domain_bridge"]
    domain_bridge_restart_backoff_seconds = 0.01
    domain_bridge_max_restarts = 1


@pytest.fixture
def fake_settings(tmp_path, monkeypatch):
    settings = _FakeSettings()
    settings.domain_bridge_config_dir = tmp_path
    monkeypatch.setattr(db, "settings", settings)
    return settings


def test_config_shape_without_share_map(fake_settings):
    config = db.build_bridge_config("robot_1", "differential_drive", ROBOT_DOMAIN)
    assert config["name"] == "robot_1_bridge"
    assert isinstance(config["topics"], dict)
    assert "/map" not in config["topics"], "share_map=False must not add the DOWN /map topic"


def test_up_topics_flow_robot_to_server(fake_settings):
    config = db.build_bridge_config("robot_1", "differential_drive", ROBOT_DOMAIN)
    topics = config["topics"]
    spec = resolve_topics("differential_drive", "robot_1")["odom"]
    key = spec["robot"].lstrip("/")
    assert topics[key] == {
        "type": "nav_msgs/msg/Odometry",
        "from_domain": ROBOT_DOMAIN,
        "to_domain": SERVER_DOMAIN,
        "remap": spec["server"],
    }


def test_down_topics_flow_server_to_robot(fake_settings):
    config = db.build_bridge_config("robot_1", "differential_drive", ROBOT_DOMAIN)
    topics = config["topics"]
    spec = resolve_topics("differential_drive", "robot_1")["cmd_vel"]
    key = spec["server"].lstrip("/")
    assert topics[key] == {
        "type": "geometry_msgs/msg/Twist",
        "from_domain": SERVER_DOMAIN,
        "to_domain": ROBOT_DOMAIN,
        "remap": spec["robot"],
    }


def test_share_map_adds_down_map_topic(fake_settings):
    config = db.build_bridge_config("robot_1", "differential_drive", ROBOT_DOMAIN, share_map=True)
    topics = config["topics"]
    assert topics["/map"] == {
        "type": "nav_msgs/msg/OccupancyGrid",
        "from_domain": SERVER_DOMAIN,
        "to_domain": ROBOT_DOMAIN,
        "remap": "/map",
    }
    # The robot's own UP /map entry is untouched — no key collision.
    assert topics["map"]["type"] == "nav_msgs/msg/OccupancyGrid"
    assert topics["map"]["to_domain"] == SERVER_DOMAIN


def test_write_bridge_config_yaml_round_trip(fake_settings, tmp_path):
    path = db.write_bridge_config("robot_1", "differential_drive", ROBOT_DOMAIN, share_map=True)
    assert path == tmp_path / "robot_1.yaml"
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = db.build_bridge_config("robot_1", "differential_drive", ROBOT_DOMAIN, share_map=True)
    assert written == expected


def test_configure_defaults_domain_when_none(fake_settings):
    path = db.domain_bridge_manager.configure("robot_1", "differential_drive", None)
    written = yaml.safe_load(path.read_text(encoding="utf-8"))
    up = written["topics"]["odom"]
    assert up["from_domain"] == ROBOT_DOMAIN  # falls back to the configured default


def test_ensure_skips_bridge_when_same_domain(fake_settings):
    result = db.domain_bridge_manager.ensure(
        "robot_1", "differential_drive", SERVER_DOMAIN, share_map=False
    )
    assert result["running"] is False
    assert "same domain" in result["reason"]


def test_ensure_reports_not_available(fake_settings, monkeypatch):
    monkeypatch.setattr(db.shutil, "which", lambda _name: None)
    result = db.domain_bridge_manager.ensure("robot_1", "differential_drive", ROBOT_DOMAIN)
    assert result["running"] is False
    assert "not installed" in result["reason"]


def test_reconfigure_keeps_share_flag(fake_settings, monkeypatch):
    """reconfigure regenerates the YAML with the requested share_map value."""
    monkeypatch.setattr(db.shutil, "which", lambda _name: None)  # never spawn a real bridge
    result = db.domain_bridge_manager.reconfigure(
        "robot_1", "differential_drive", ROBOT_DOMAIN, share_map=True
    )
    assert result["running"] is False
    written = yaml.safe_load(
        (fake_settings.domain_bridge_config_dir / "robot_1.yaml").read_text(encoding="utf-8")
    )
    assert "/map" in written["topics"]