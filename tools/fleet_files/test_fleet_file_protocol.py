"""ROS-free tests for the fleet file push protocol.  Run:  pytest tools/fleet_files"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_file_protocol as p  # noqa: E402

REPO_TOPICS = Path(__file__).resolve().parents[2] / "backend" / "config" / "fleet_topics.yaml"
GRAPH = {"waypoints": [{"id": 1, "name": "WP_01", "x": 0.0}, {"id": 5, "name": "Dock_A"}]}


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


def test_graph_round_trip_overwrites_target_and_keeps_backup(tmp_path):
    src = _write(tmp_path, "new_graph.json", json.dumps(GRAPH))
    (tmp_path / "robot").mkdir()
    target = _write(tmp_path / "robot", "drl_map.json", '{"waypoints": [{"id": 9, "name": "old"}]}')
    update = p.build_graph_update(str(src), "fleet-pc")
    result = p.apply_update(update, graph_path=str(target), map_dir=None)
    assert json.loads(target.read_text()) == GRAPH
    assert (target.parent / "drl_map.json.bak").exists()
    assert result["written"] == [str(target)]


def test_map_update_carries_yaml_and_image(tmp_path):
    _write(tmp_path, "fleet.pgm", b"P5\n2 2\n255\n\x00\xff\xff\x00")
    yaml_path = _write(tmp_path, "fleet.yaml", "image: fleet.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n")
    update = p.build_map_update(str(yaml_path))
    out = tmp_path / "robot_maps"
    p.apply_update(update, graph_path=None, map_dir=str(out))
    assert (out / "fleet.pgm").read_bytes() == (tmp_path / "fleet.pgm").read_bytes()
    assert (out / "fleet.yaml").exists()


def test_corrupted_payload_is_rejected_and_nothing_written(tmp_path):
    src = _write(tmp_path, "g.json", json.dumps(GRAPH))
    update = p.build_graph_update(str(src))
    update["files"][0]["sha256"] = "0" * 64
    target = tmp_path / "out.json"
    with pytest.raises(p.FleetFileError, match="sha256"):
        p.apply_update(update, graph_path=str(target), map_dir=None)
    assert not target.exists()


@pytest.mark.parametrize(
    "graph,message",
    [
        ({"waypoints": []}, "non-empty"),
        ({"waypoints": [{"id": 1}]}, "'id' and 'name'"),
        ({"waypoints": [{"id": "1", "name": "a"}]}, "integer"),
        ({"waypoints": [{"id": 1, "name": "a"}, {"id": 1, "name": "b"}]}, "duplicate waypoint id"),
        ({"waypoints": [{"id": 1, "name": "a"}, {"id": 2, "name": "a"}]}, "duplicate waypoint name"),
    ],
)
def test_bad_graph_is_refused_before_sending(tmp_path, graph, message):
    src = _write(tmp_path, "g.json", json.dumps(graph))
    with pytest.raises(p.FleetFileError, match=message):
        p.build_graph_update(str(src))


def test_sender_file_names_cannot_escape_the_map_dir(tmp_path):
    _write(tmp_path, "m.pgm", b"P5\n1 1\n255\n\x00")
    update = p.build_map_update(str(_write(tmp_path, "m.yaml", "image: m.pgm\nresolution: 1\norigin: [0,0,0]\n")))
    update["files"][1]["name"] = "../../etc/evil.pgm"
    out = tmp_path / "maps"
    p.apply_update(update, graph_path=None, map_dir=str(out))
    assert (out / "evil.pgm").exists()
    assert not (tmp_path.parent / "etc").exists()


def test_topic_names_come_from_fleet_topics_yaml():
    templates = p.load_topic_templates(str(REPO_TOPICS))
    assert templates["file_update"] == "/{robot}/fleet/file_update"
    assert templates["goal"] == "/{robot}/amr/goal"
    assert p.topic_for(templates["file_ack"], "kumki") == "/kumki/fleet/file_ack"


def test_robot_discovery_from_live_topics():
    names = ["/robot1/amr/goal", "/kumki/amr/goal", "/robot1/amcl_pose", "/amr/goal", "/a/b/amr/goal"]
    assert p.robots_from_topics("/{robot}/amr/goal", names) == ["kumki", "robot1"]


def test_build_update_from_bytes_roundtrip(tmp_path):
    import json as _json

    graph = _json.dumps({"waypoints": [{"id": 1, "name": "A"}]}).encode()
    update = p.build_update("graph", [("graph", "amr_path.json", graph)], "t", version="7")
    assert update["version"] == "7"
    out = tmp_path / "g.json"
    p.apply_update(update, graph_path=str(out), map_dir=None)
    assert out.read_bytes() == graph


def test_backend_copy_is_identical():
    from pathlib import Path

    here = Path(__file__).resolve().parent
    backend = here.parents[1] / "backend" / "app" / "services" / "fleet_file_protocol.py"
    assert backend.read_bytes() == (here / "fleet_file_protocol.py").read_bytes()
