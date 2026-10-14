"""Versioned fleet files (graph JSON, map) and per-robot sync state.

* `fleet_files`       one document per (kind, version); file bytes live in
                      GridFS (`fleet_blobs`) so a large map never hits the
                      16 MB document limit.
* `robot_file_state`  last push result per (robot_id, kind).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId

from app.db.documents import serialize, utcnow
from app.db.mongo import Collections


def _files(db):
    return db[Collections.fleet_files]


def _state(db):
    return db[Collections.robot_file_state]


def _bucket(db) -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(db, bucket_name="fleet_blobs")


async def put_blob(db, name: str, data: bytes) -> ObjectId:
    return await _bucket(db).upload_from_stream(name, data)


async def read_blob(db, blob_id: ObjectId) -> bytes:
    stream = await _bucket(db).open_download_stream(blob_id)
    return await stream.read()


async def add_version(
    db, *, kind: str, files: List[Dict[str, Any]], created_by: str, note: str, meta: Dict[str, Any]
) -> Dict[str, Any]:
    """Insert a new version and make it the active one for `kind`."""
    last = await _files(db).find_one({"kind": kind}, sort=[("version", -1)])
    version = (last["version"] if last else 0) + 1
    await _files(db).update_many({"kind": kind, "active": True}, {"$set": {"active": False}})
    document = {
        "kind": kind,
        "version": version,
        "active": True,
        "files": files,  # [{role, name, sha256, size, blob_id}]
        "meta": meta,
        "note": note,
        "created_by": created_by,
        "created_at": utcnow(),
    }
    result = await _files(db).insert_one(document)
    document["_id"] = result.inserted_id
    return serialize(document)  # type: ignore[return-value]


async def list_versions(db, kind: str, limit: int = 50) -> List[Dict[str, Any]]:
    cursor = _files(db).find({"kind": kind}).sort("version", -1)
    return [serialize(d) for d in await cursor.to_list(length=limit)]  # type: ignore[misc]


async def get_version(db, kind: str, version: int) -> Optional[Dict[str, Any]]:
    return serialize(await _files(db).find_one({"kind": kind, "version": version}))


async def get_active(db, kind: str) -> Optional[Dict[str, Any]]:
    return serialize(await _files(db).find_one({"kind": kind, "active": True}))


async def activate(db, kind: str, version: int) -> bool:
    if await _files(db).find_one({"kind": kind, "version": version}) is None:
        return False
    await _files(db).update_many({"kind": kind, "active": True}, {"$set": {"active": False}})
    await _files(db).update_one({"kind": kind, "version": version}, {"$set": {"active": True}})
    return True


async def upsert_robot_state(
    db, robot_id: str, kind: str, **fields: Any
) -> None:
    await _state(db).update_one(
        {"robot_id": robot_id, "kind": kind},
        {"$set": {**fields, "updated_at": utcnow()}},
        upsert=True,
    )


async def list_robot_state(db) -> List[Dict[str, Any]]:
    cursor = _state(db).find({})
    return [serialize(d) for d in await cursor.to_list(length=5000)]  # type: ignore[misc]
