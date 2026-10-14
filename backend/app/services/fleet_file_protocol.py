"""Shared, ROS-free logic for pushing fleet files (graph JSON, map) to robots.

Used by `push_fleet_files.py` (fleet PC) and `fleet_file_receiver.py`
(each robot). Keep this file next to both scripts.

Message on  /{robot}/fleet/file_update   (std_msgs/String, JSON):
    {
      "protocol": 1,
      "kind": "graph" | "map",
      "version": "2026-10-15T01:30:00Z",
      "sender": "fleet-pc",
      "files": [ {"role": "graph", "name": "amr_path.json",
                  "sha256": "...", "encoding": "base64", "data": "..."} ]
    }
    A map update carries two files: role "map_yaml" and role "map_image".

Reply on    /{robot}/fleet/file_ack      (std_msgs/String, JSON):
    {"robot": "robot1", "kind": "graph", "version": "...", "ok": true,
     "written": ["/home/hs/.../amr_path.json"], "sha256": {...}, "error": null}
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROTOCOL = 1
DEFAULT_TOPICS = {
    "file_update": "/{robot}/fleet/file_update",
    "file_ack": "/{robot}/fleet/file_ack",
    "goal": "/{robot}/amr/goal",
}


class FleetFileError(ValueError):
    pass


# ---------------------------------------------------------------------------
# topic names: read from the same fleet_topics.yaml the backend uses
# ---------------------------------------------------------------------------
def load_topic_templates(config_path: Optional[str], robot_type: Optional[str] = None) -> Dict[str, str]:
    """`{logical: "/{robot}/..."}` for file_update/file_ack/goal.

    Falls back to the defaults above when no config file is available (e.g. on
    a robot that only has this folder copied onto it).
    """
    templates = dict(DEFAULT_TOPICS)
    if not config_path or not Path(config_path).is_file():
        return templates
    import yaml  # PyYAML; only needed when a config file is given

    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    types = data.get("robot_types") or {}
    name = robot_type or data.get("default_robot_type") or next(iter(types), None)
    chain: List[Dict[str, Any]] = []
    while name and name in types and len(chain) < 20:
        chain.append(types[name])
        name = types[name].get("extends")
    for spec in reversed(chain):  # parent first, child overrides
        for logical, topic in (spec.get("topics") or {}).items():
            if logical in templates and isinstance(topic, dict) and topic.get("name"):
                templates[logical] = str(topic["name"])
    return templates


def topic_for(template: str, robot: str) -> str:
    return template.format(robot=robot)


def robots_from_topics(goal_template: str, topic_names: List[str]) -> List[str]:
    """Discover robot namespaces from live topic names (e.g. /robot1/amr/goal)."""
    pattern = re.escape(goal_template).replace(re.escape("{robot}"), r"([A-Za-z][A-Za-z0-9_]*)")
    regex = re.compile(f"^{pattern}$")
    found = {m.group(1) for name in topic_names if (m := regex.match(name))}
    return sorted(found)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def validate_graph(raw: bytes) -> Dict[str, Any]:
    """Same rules mission_commander.py relies on: unique int ids, unique names."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FleetFileError(f"graph is not valid JSON: {exc}") from exc
    waypoints = data.get("waypoints") if isinstance(data, dict) else None
    if not isinstance(waypoints, list) or not waypoints:
        raise FleetFileError("graph must contain a non-empty 'waypoints' list")
    ids, names = set(), set()
    for index, wp in enumerate(waypoints):
        if not isinstance(wp, dict) or "id" not in wp or "name" not in wp:
            raise FleetFileError(f"waypoints[{index}] needs 'id' and 'name'")
        if not isinstance(wp["id"], int) or isinstance(wp["id"], bool):
            raise FleetFileError(f"waypoints[{index}].id must be an integer, got {wp['id']!r}")
        if wp["id"] in ids:
            raise FleetFileError(f"duplicate waypoint id {wp['id']}")
        if wp["name"] in names:
            raise FleetFileError(f"duplicate waypoint name {wp['name']!r}")
        ids.add(wp["id"])
        names.add(wp["name"])
    return {"waypoints": len(waypoints)}


def map_image_name(map_yaml: bytes) -> str:
    import yaml

    try:
        meta = yaml.safe_load(map_yaml.decode("utf-8")) or {}
    except Exception as exc:
        raise FleetFileError(f"map yaml is not valid YAML: {exc}") from exc
    for key in ("image", "resolution", "origin"):
        if key not in meta:
            raise FleetFileError(f"map yaml is missing '{key}'")
    return str(meta["image"])


# ---------------------------------------------------------------------------
# building + applying updates
# ---------------------------------------------------------------------------
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_entry(role: str, name: str, data: bytes) -> Dict[str, Any]:
    return {
        "role": role,
        "name": name,
        "sha256": sha256(data),
        "encoding": "base64",
        "data": base64.b64encode(data).decode("ascii"),
    }


def build_graph_update(path: str, sender: str = "") -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    validate_graph(raw)
    return _envelope("graph", [_file_entry("graph", Path(path).name, raw)], sender)


def build_map_update(yaml_path: str, sender: str = "") -> Dict[str, Any]:
    yaml_file = Path(yaml_path)
    raw_yaml = yaml_file.read_bytes()
    image_name = map_image_name(raw_yaml)
    image_path = (yaml_file.parent / image_name).resolve()
    if not image_path.is_file():
        raise FleetFileError(f"map image '{image_name}' (from {yaml_file.name}) not found")
    return _envelope(
        "map",
        [
            _file_entry("map_yaml", yaml_file.name, raw_yaml),
            _file_entry("map_image", image_path.name, image_path.read_bytes()),
        ],
        sender,
    )


def build_update(
    kind: str,
    files: List[tuple],
    sender: str = "",
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an update from in-memory files: `files` = [(role, name, bytes)].

    Used by the backend, which stores files in the database instead of on disk.
    """
    if kind == "graph":
        graph = [f for f in files if f[0] == "graph"]
        if len(graph) != 1:
            raise FleetFileError("graph update needs exactly one graph file")
        validate_graph(graph[0][2])
    elif kind == "map":
        roles = {f[0]: f for f in files}
        if "map_yaml" not in roles or "map_image" not in roles:
            raise FleetFileError("map update needs map_yaml and map_image")
        map_image_name(roles["map_yaml"][2])
    else:
        raise FleetFileError(f"unknown kind {kind!r}")
    return _envelope(kind, [_file_entry(r, n, d) for r, n, d in files], sender, version)


def _envelope(
    kind: str, files: List[Dict[str, Any]], sender: str, version: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "kind": kind,
        "version": version or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sender": sender,
        "files": files,
    }


def _atomic_write(target: Path, data: bytes, keep_backup: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if keep_backup and target.exists():
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply_update(
    update: Dict[str, Any],
    *,
    graph_path: Optional[str],
    map_dir: Optional[str],
    keep_backup: bool = True,
) -> Dict[str, Any]:
    """Verify every file, then write them. Nothing is written if any check fails.

    graph -> written to exactly `graph_path` (the file route_manager /
             mission_commander loads), whatever the sender called it.
    map   -> yaml + image written into `map_dir` under the sender's names.
    """
    if update.get("protocol") != PROTOCOL:
        raise FleetFileError(f"unsupported protocol {update.get('protocol')!r}")
    kind = update.get("kind")
    files = update.get("files") or []
    decoded: List[tuple] = []
    for entry in files:
        try:
            data = base64.b64decode(entry["data"], validate=True)
        except Exception as exc:
            raise FleetFileError(f"{entry.get('name')}: bad base64 ({exc})") from exc
        if sha256(data) != entry.get("sha256"):
            raise FleetFileError(f"{entry.get('name')}: sha256 mismatch (corrupted in transit)")
        name = Path(str(entry.get("name") or "")).name  # never trust paths
        if not name:
            raise FleetFileError("file entry without a name")
        decoded.append((entry.get("role"), name, data))

    targets: List[tuple] = []
    if kind == "graph":
        if not graph_path:
            raise FleetFileError("this robot has no --graph-path configured")
        graph = [d for d in decoded if d[0] == "graph"]
        if len(graph) != 1:
            raise FleetFileError("graph update must contain exactly one graph file")
        validate_graph(graph[0][2])
        targets.append((Path(graph_path).expanduser(), graph[0][2]))
    elif kind == "map":
        if not map_dir:
            raise FleetFileError("this robot has no --map-dir configured")
        roles = {d[0]: d for d in decoded}
        if "map_yaml" not in roles or "map_image" not in roles:
            raise FleetFileError("map update needs map_yaml and map_image")
        map_image_name(roles["map_yaml"][2])
        base = Path(map_dir).expanduser()
        targets += [(base / roles[r][1], roles[r][2]) for r in ("map_image", "map_yaml")]
    else:
        raise FleetFileError(f"unknown kind {kind!r}")

    for target, data in targets:
        _atomic_write(target, data, keep_backup)
    return {
        "written": [str(t) for t, _ in targets],
        "sha256": {str(t): sha256(d) for t, d in targets},
    }
