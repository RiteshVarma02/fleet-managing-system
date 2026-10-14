"""Fleet-wide graph JSON and map: one versioned copy, pushed to every robot.

The backend never touches a robot's disk. It stores the files (GridFS),
builds a protocol update (`fleet_file_protocol`) and publishes it through the
robot's `fleet_files` capability; the on-robot receiver applies it and acks.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.db.repositories import fleet_files_repo as repo
from app.db.repositories import robots_repo
from app.ros.manager import ros_manager
from app.services import fleet_file_protocol as proto

logger = get_logger(__name__)

KINDS = ("graph", "map")
MAX_GRAPH_BYTES = 2 * 1024 * 1024
MAX_MAP_BYTES = 25 * 1024 * 1024
IMAGE_SUFFIXES = {".pgm", ".png", ".jpg", ".jpeg", ".bmp"}

_preview_cache: Dict[int, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# pure helpers (unit-tested without Mongo or ROS)
# ---------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_waypoints(raw: bytes) -> List[Dict[str, Any]]:
    """`[{id, name, x, y}]` from the graph JSON. x/y are None when absent.

    Coordinates are read tolerantly (`x`/`y`, `pose.x`, `position.x`) because
    only `id` and `name` are guaranteed by the route_manager graph.
    """
    proto.validate_graph(raw)
    import json

    out: List[Dict[str, Any]] = []
    for wp in json.loads(raw.decode("utf-8"))["waypoints"]:
        source = wp
        for key in ("pose", "position"):
            if isinstance(wp.get(key), dict):
                source = wp[key]
                break
        x = _num(wp.get("x", source.get("x")))
        y = _num(wp.get("y", source.get("y")))
        out.append({"id": wp["id"], "name": str(wp["name"]), "x": x, "y": y})
    return out


def parse_map_meta(yaml_bytes: bytes) -> Dict[str, Any]:
    import yaml

    meta = yaml.safe_load(yaml_bytes.decode("utf-8")) or {}
    origin = meta.get("origin") or [0.0, 0.0, 0.0]
    try:
        return {
            "image": str(meta["image"]),
            "resolution": float(meta["resolution"]),
            "origin_x": float(origin[0]),
            "origin_y": float(origin[1]),
        }
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValidationError(f"map yaml has unusable resolution/origin: {exc}") from exc


def sync_state(active_version: Optional[int], state: Optional[Dict[str, Any]]) -> str:
    """in_sync | out_of_sync | failed | never | no_file"""
    if active_version is None:
        return "no_file"
    if not state:
        return "never"
    if state.get("acked_version") == active_version:
        return "in_sync"
    if (
        state.get("last_attempt_version") == active_version
        and state.get("last_attempt_status") not in (None, "acked")
    ):
        return "failed"
    return "out_of_sync" if state.get("acked_version") else "never"


def _public_version(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "version": doc["version"],
        "active": bool(doc.get("active")),
        "note": doc.get("note", ""),
        "created_by": doc.get("created_by", ""),
        "created_at": doc.get("created_at"),
        "meta": doc.get("meta", {}),
        "files": [
            {k: f[k] for k in ("role", "name", "sha256", "size")} for f in doc.get("files", [])
        ],
    }


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------
async def _store(db, kind: str, files: List[Tuple[str, str, bytes]], user: str, note: str,
                 meta: Dict[str, Any]) -> Dict[str, Any]:
    stored = []
    for role, name, data in files:
        blob_id = await repo.put_blob(db, name, data)
        stored.append({
            "role": role, "name": name, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "blob_id": blob_id,
        })
    doc = await repo.add_version(db, kind=kind, files=stored, created_by=user, note=note, meta=meta)
    logger.info("fleet file stored: kind=%s version=%s by %s", kind, doc["version"], user)
    return _public_version(doc)


async def upload_graph(db, filename: str, content: bytes, user: str, note: str = "") -> Dict[str, Any]:
    if not content:
        raise ValidationError("Empty file")
    if len(content) > MAX_GRAPH_BYTES:
        raise ValidationError("Graph file too large (max 2 MB)")
    try:
        info = proto.validate_graph(content)
        waypoints = parse_waypoints(content)
    except proto.FleetFileError as exc:
        raise ValidationError(str(exc)) from exc
    meta = {"waypoints": info["waypoints"], "has_coordinates": any(w["x"] is not None for w in waypoints)}
    return await _store(db, "graph", [("graph", Path(filename).name or "amr_path.json", content)],
                        user, note, meta)


async def upload_map(db, yaml_name: str, yaml_bytes: bytes, image_name: str, image_bytes: bytes,
                     user: str, note: str = "") -> Dict[str, Any]:
    if not yaml_bytes or not image_bytes:
        raise ValidationError("Both the map .yaml and the map image are required")
    if len(image_bytes) > MAX_MAP_BYTES:
        raise ValidationError("Map image too large (max 25 MB)")
    image_name = Path(image_name).name
    if Path(image_name).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValidationError(f"Unsupported map image format '{Path(image_name).suffix}'")
    try:
        referenced = proto.map_image_name(yaml_bytes)
    except proto.FleetFileError as exc:
        raise ValidationError(str(exc)) from exc
    if Path(referenced).name != image_name:
        raise ValidationError(
            f"The yaml says image '{referenced}' but you uploaded '{image_name}'. "
            "Upload the matching image or fix the yaml."
        )
    meta = parse_map_meta(yaml_bytes)
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except Exception as exc:
        raise ValidationError(f"Could not decode map image: {exc}") from exc
    meta.update(width=image.width, height=image.height)
    return await _store(
        db, "map",
        [("map_yaml", Path(yaml_name).name or "map.yaml", yaml_bytes), ("map_image", image_name, image_bytes)],
        user, note, meta,
    )


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------
async def _doc(db, kind: str, version: Optional[int]) -> Dict[str, Any]:
    if kind not in KINDS:
        raise ValidationError(f"kind must be one of {KINDS}")
    doc = await (repo.get_version(db, kind, version) if version else repo.get_active(db, kind))
    if doc is None:
        raise NotFoundError(f"No {kind} file{f' version {version}' if version else ''} uploaded yet")
    return doc


async def _load_files(db, doc: Dict[str, Any]) -> List[Tuple[str, str, bytes]]:
    return [(f["role"], f["name"], await repo.read_blob(db, f["blob_id"])) for f in doc["files"]]


async def overview(db) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for kind in KINDS:
        versions = [_public_version(d) for d in await repo.list_versions(db, kind)]
        out[kind] = {"active": next((v for v in versions if v["active"]), None), "versions": versions}
    return out


async def download(db, kind: str, version: Optional[int]) -> Tuple[str, str, bytes]:
    """(filename, media_type, bytes). A map downloads as a zip of yaml + image."""
    doc = await _doc(db, kind, version)
    files = await _load_files(db, doc)
    if kind == "graph":
        return files[0][1], "application/json", files[0][2]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for _, name, data in files:
            archive.writestr(name, data)
    return f"fleet_map_v{doc['version']}.zip", "application/zip", buffer.getvalue()


async def activate(db, kind: str, version: int) -> Dict[str, Any]:
    await _doc(db, kind, version)
    await repo.activate(db, kind, version)
    return _public_version(await _doc(db, kind, version))


async def list_waypoints(db) -> Dict[str, Any]:
    doc = await repo.get_active(db, "graph")
    if doc is None:
        return {"version": None, "waypoints": []}
    raw = (await _load_files(db, doc))[0][2]
    return {"version": doc["version"], "waypoints": parse_waypoints(raw)}


async def waypoint_names(db) -> set:
    return {w["name"] for w in (await list_waypoints(db))["waypoints"]}


async def map_preview(db) -> Dict[str, Any]:
    """PNG (base64) + metadata of the active map for the dashboard."""
    doc = await repo.get_active(db, "map")
    if doc is None:
        return {"version": None, "image": "", "metadata": None}
    cached = _preview_cache.get(doc["version"])
    if cached is None:
        from PIL import Image

        files = {role: data for role, _, data in await _load_files(db, doc)}
        image = Image.open(io.BytesIO(files["map_image"]))
        image.load()
        buffer = io.BytesIO()
        image.convert("L").save(buffer, format="PNG")
        cached = {
            "version": doc["version"],
            "image": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "metadata": {k: doc["meta"][k] for k in
                         ("width", "height", "resolution", "origin_x", "origin_y")},
        }
        _preview_cache.clear()
        _preview_cache[doc["version"]] = cached
    return cached


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------
async def _push_one(db, robot_id: str, kind: str, version: int, update: Dict[str, Any]) -> Dict[str, Any]:
    controller = ros_manager.get_controller(robot_id)
    result: Dict[str, Any] = {"robot_id": robot_id, "kind": kind, "version": version}

    async def finish(status: str, error: Optional[str] = None, acked: bool = False) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "last_attempt_version": version, "last_attempt_status": status, "error": error,
        }
        if acked:
            fields["acked_version"] = version
        await repo.upsert_robot_state(db, robot_id, kind, **fields)
        return {**result, "status": status, "error": error}

    if controller is None:
        return await finish("offline", "Robot is not connected")
    if not controller.has_capability("fleet_files") or not controller.push_file_update(update):
        return await finish("unsupported", "This robot type has no file-sync topic")

    deadline = time.monotonic() + settings.fleet_files_ack_timeout_seconds
    while time.monotonic() < deadline:
        ack = controller.file_ack(kind)
        if ack and str(ack.get("version")) == str(version):
            if ack.get("ok"):
                return await finish("acked", acked=True)
            return await finish("failed", str(ack.get("error") or "Robot rejected the update"))
        await asyncio.sleep(0.2)
    return await finish(
        "no_ack",
        "No acknowledgement. Is fleet_file_receiver.py running on the robot? "
        "The update stays latched and applies when it starts.",
    )


async def push(db, kind: str, user: str, robot_ids: Optional[List[str]] = None,
               version: Optional[int] = None) -> Dict[str, Any]:
    doc = await _doc(db, kind, version)
    files = await _load_files(db, doc)
    update = proto.build_update(kind, files, sender=user, version=str(doc["version"]))
    targets = robot_ids or ros_manager.connected_robot_ids()
    if not targets:
        raise ConflictError("No robots are connected")
    results = await asyncio.gather(*[_push_one(db, rid, kind, doc["version"], update) for rid in targets])
    return {"kind": kind, "version": doc["version"], "results": list(results)}


async def status(db) -> Dict[str, Any]:
    active = {k: (await repo.get_active(db, k)) for k in KINDS}
    states = {(s["robot_id"], s["kind"]): s for s in await repo.list_robot_state(db)}
    robots = await robots_repo.list_all(db)
    rows = []
    for robot in robots:
        rid = str(robot.get("robot_id") or "")
        if not rid:
            continue
        controller = ros_manager.get_controller(rid)
        entry: Dict[str, Any] = {"robot_id": rid, "online": controller is not None}
        for kind in KINDS:
            version = active[kind]["version"] if active[kind] else None
            state = dict(states.get((rid, kind)) or {})
            # A late ack (after the push call timed out) still counts.
            ack = controller.file_ack(kind) if controller and controller.has_capability("fleet_files") else None
            if ack and ack.get("ok") and version is not None and str(ack.get("version")) == str(version) \
                    and state.get("acked_version") != version:
                await repo.upsert_robot_state(db, rid, kind, acked_version=version,
                                              last_attempt_version=version, last_attempt_status="acked",
                                              error=None)
                state.update(acked_version=version, last_attempt_version=version, last_attempt_status="acked")
            entry[kind] = {
                "active_version": version,
                "robot_version": state.get("acked_version"),
                "sync": sync_state(version, state),
                "last_status": state.get("last_attempt_status"),
                "error": state.get("error"),
            }
        rows.append(entry)
    return {
        "active": {k: (active[k]["version"] if active[k] else None) for k in KINDS},
        "robots": rows,
    }
