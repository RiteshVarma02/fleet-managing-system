"""Fleet file service: pure helpers + upload/push flow with fake storage and ROS."""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any, Dict, List

import pytest

from app.core.exceptions import ValidationError
from app.services import fleet_file_service as svc

GRAPH = json.dumps({"waypoints": [
    {"id": 1, "name": "WP_01", "x": 1.0, "y": 2.0},
    {"id": 2, "name": "WP_02", "pose": {"x": 3.5, "y": -1}},
    {"id": 5, "name": "Dock"},
]}).encode()


def _png(w=4, h=3) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (w, h), 255).save(buf, format="PNG")
    return buf.getvalue()


YAML = b"image: floor.png\nresolution: 0.05\norigin: [-1.0, -2.0, 0.0]\n"


def test_parse_waypoints_reads_flat_and_nested_coordinates():
    wps = svc.parse_waypoints(GRAPH)
    assert wps[0] == {"id": 1, "name": "WP_01", "x": 1.0, "y": 2.0}
    assert (wps[1]["x"], wps[1]["y"]) == (3.5, -1.0)
    assert wps[2]["x"] is None


def test_parse_map_meta():
    assert svc.parse_map_meta(YAML) == {
        "image": "floor.png", "resolution": 0.05, "origin_x": -1.0, "origin_y": -2.0}


@pytest.mark.parametrize("active,state,expected", [
    (None, None, "no_file"),
    (3, None, "never"),
    (3, {"acked_version": 3}, "in_sync"),
    (3, {"acked_version": 2}, "out_of_sync"),
    (3, {"acked_version": 2, "last_attempt_version": 3, "last_attempt_status": "failed"}, "failed"),
    (3, {"last_attempt_version": 3, "last_attempt_status": "no_ack"}, "failed"),
])
def test_sync_state(active, state, expected):
    assert svc.sync_state(active, state) == expected


# ---- fake storage + ROS ----------------------------------------------------
class FakeRepo:
    def __init__(self):
        self.blobs: Dict[int, bytes] = {}
        self.versions: List[Dict[str, Any]] = []
        self.state: Dict[tuple, Dict[str, Any]] = {}

    async def put_blob(self, db, name, data):
        self.blobs[len(self.blobs) + 1] = data
        return len(self.blobs)

    async def read_blob(self, db, blob_id):
        return self.blobs[blob_id]

    async def add_version(self, db, *, kind, files, created_by, note, meta):
        n = 1 + max([v["version"] for v in self.versions if v["kind"] == kind] or [0])
        for v in self.versions:
            if v["kind"] == kind:
                v["active"] = False
        doc = {"kind": kind, "version": n, "active": True, "files": files, "meta": meta,
               "note": note, "created_by": created_by, "created_at": None}
        self.versions.append(doc)
        return doc

    async def get_active(self, db, kind):
        return next((v for v in self.versions if v["kind"] == kind and v["active"]), None)

    async def get_version(self, db, kind, version):
        return next((v for v in self.versions if v["kind"] == kind and v["version"] == version), None)

    async def upsert_robot_state(self, db, rid, kind, **fields):
        self.state.setdefault((rid, kind), {}).update(fields)


class FakeController:
    def __init__(self, ack_ok=True, respond=True, caps=("fleet_files",)):
        self.ack_ok, self.respond, self.caps = ack_ok, respond, caps
        self.sent: List[Dict[str, Any]] = []
        self.ack = None

    def has_capability(self, c):
        return c in self.caps

    def push_file_update(self, update):
        self.sent.append(update)
        if self.respond:
            self.ack = {"kind": update["kind"], "version": update["version"], "ok": self.ack_ok,
                        "error": None if self.ack_ok else "disk full"}
        return True

    def file_ack(self, kind):
        return self.ack


class FakeRos:
    def __init__(self, controllers):
        self.c = controllers

    def get_controller(self, rid):
        return self.c.get(rid)

    def connected_robot_ids(self):
        return list(self.c)


@pytest.fixture
def env(monkeypatch):
    repo = FakeRepo()
    for name in ("put_blob", "read_blob", "add_version", "get_active", "get_version", "upsert_robot_state"):
        monkeypatch.setattr(svc.repo, name, getattr(repo, name))
    monkeypatch.setattr(svc.settings, "fleet_files_ack_timeout_seconds", 0.4)
    return repo


def run(coro):
    return asyncio.run(coro)


def test_upload_graph_versions_and_marks_active(env):
    v1 = run(svc.upload_graph(None, "amr_path.json", GRAPH, "dev"))
    v2 = run(svc.upload_graph(None, "amr_path.json", GRAPH, "dev", note="again"))
    assert (v1["version"], v2["version"]) == (1, 2)
    assert [v["active"] for v in env.versions] == [False, True]
    assert v2["meta"]["waypoints"] == 3 and v2["meta"]["has_coordinates"]


def test_upload_graph_rejects_bad_json(env):
    with pytest.raises(ValidationError):
        run(svc.upload_graph(None, "x.json", b'{"waypoints": [{"id": "a", "name": "n"}]}', "dev"))


def test_upload_map_requires_matching_image_name(env):
    with pytest.raises(ValidationError, match="floor.png"):
        run(svc.upload_map(None, "m.yaml", YAML, "other.png", _png(), "dev"))
    ok = run(svc.upload_map(None, "m.yaml", YAML, "floor.png", _png(), "dev"))
    assert ok["meta"]["width"] == 4 and ok["meta"]["origin_x"] == -1.0


def test_push_reports_ack_offline_and_failure(env, monkeypatch):
    run(svc.upload_graph(None, "amr_path.json", GRAPH, "dev"))
    good, bad, mute = FakeController(), FakeController(ack_ok=False), FakeController(respond=False)
    monkeypatch.setattr(svc, "ros_manager", FakeRos({"r1": good, "r2": bad, "r3": mute}))
    out = run(svc.push(None, "graph", "dev", ["r1", "r2", "r3", "ghost"]))
    by = {r["robot_id"]: r for r in out["results"]}
    assert by["r1"]["status"] == "acked"
    assert by["r2"]["status"] == "failed" and by["r2"]["error"] == "disk full"
    assert by["r3"]["status"] == "no_ack"
    assert by["ghost"]["status"] == "offline"
    assert env.state[("r1", "graph")]["acked_version"] == 1
    assert "acked_version" not in env.state[("r2", "graph")]
    assert good.sent[0]["version"] == "1" and good.sent[0]["kind"] == "graph"


def test_push_without_robots_is_conflict(env, monkeypatch):
    from app.core.exceptions import ConflictError

    run(svc.upload_graph(None, "amr_path.json", GRAPH, "dev"))
    monkeypatch.setattr(svc, "ros_manager", FakeRos({}))
    with pytest.raises(ConflictError):
        run(svc.push(None, "graph", "dev"))


def test_waypoint_names_from_active_graph(env):
    run(svc.upload_graph(None, "amr_path.json", GRAPH, "dev"))
    assert run(svc.waypoint_names(None)) == {"WP_01", "WP_02", "Dock"}
