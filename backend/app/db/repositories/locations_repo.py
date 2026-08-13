"""`locations` collection — named waypoints used by tasks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.documents import serialize, to_object_id, utcnow
from app.db.mongo import Collections


def _col(db):
    return db[Collections.locations]


async def list_all(db, *, map_name: Optional[str] = None) -> List[Dict[str, Any]]:
    query = {"map_name": map_name} if map_name else {}
    cursor = _col(db).find(query).sort("name", 1)
    return [serialize(doc) for doc in await cursor.to_list(length=1000)]  # type: ignore[misc]


async def get(db, location_id: str) -> Optional[Dict[str, Any]]:
    oid = to_object_id(location_id)
    if oid is None:
        return None
    return serialize(await _col(db).find_one({"_id": oid}))


async def create(
    db,
    *,
    name: str,
    x: float,
    y: float,
    theta: float = 0.0,
    map_name: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    document = {
        "name": name.strip(),
        "x": float(x),
        "y": float(y),
        "theta": float(theta),
        "map_name": map_name,
        "created_by": created_by,
        "created_at": utcnow(),
    }
    try:
        result = await _col(db).insert_one(document)
    except DuplicateKeyError:
        return None
    document["_id"] = result.inserted_id
    return serialize(document)


async def update(db, location_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    oid = to_object_id(location_id)
    if oid is None:
        return None
    updates = {k: v for k, v in fields.items() if v is not None}
    updates["updated_at"] = utcnow()
    return serialize(
        await _col(db).find_one_and_update(
            {"_id": oid}, {"$set": updates}, return_document=ReturnDocument.AFTER
        )
    )


async def delete(db, location_id: str) -> bool:
    oid = to_object_id(location_id)
    if oid is None:
        return False
    result = await _col(db).delete_one({"_id": oid})
    return result.deleted_count > 0
