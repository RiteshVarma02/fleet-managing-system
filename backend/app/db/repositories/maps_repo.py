"""`maps` collection — metadata plus a filesystem/GridFS-style raster reference.

The PNG/PGM raster stays on disk (`settings.maps_dir`); Mongo stores the
metadata and, for locally authored maps, the base64 raster so a map can be
edited without a live SLAM session.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.documents import serialize, to_object_id, utcnow
from app.db.mongo import Collections

_META_ONLY = {"image_base64": 0}


def _col(db):
    return db[Collections.maps]


async def list_all(db) -> List[Dict[str, Any]]:
    cursor = _col(db).find({}, _META_ONLY).sort("updated_at", -1)
    return [serialize(doc) for doc in await cursor.to_list(length=500)]  # type: ignore[misc]


async def get_by_name(db, name: str, *, with_image: bool = True) -> Optional[Dict[str, Any]]:
    projection = None if with_image else _META_ONLY
    return serialize(await _col(db).find_one({"name": name}, projection))


async def get(db, map_id: str, *, with_image: bool = True) -> Optional[Dict[str, Any]]:
    oid = to_object_id(map_id)
    if oid is None:
        return None
    projection = None if with_image else _META_ONLY
    return serialize(await _col(db).find_one({"_id": oid}, projection))


async def upsert(
    db,
    *,
    name: str,
    metadata: Dict[str, Any],
    image_base64: Optional[str] = None,
    source: str = "slam",
    file_path: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    updates: Dict[str, Any] = {
        "metadata": metadata,
        "source": source,
        "file_path": file_path,
        "updated_at": utcnow(),
    }
    if image_base64 is not None:
        updates["image_base64"] = image_base64
    doc = await _col(db).find_one_and_update(
        {"name": name},
        {
            "$set": updates,
            "$setOnInsert": {"name": name, "created_at": utcnow(), "created_by": created_by},
        },
        upsert=True,
        projection=_META_ONLY,
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)  # type: ignore[return-value]


async def create(db, **fields: Any) -> Optional[Dict[str, Any]]:
    document = {"created_at": utcnow(), "updated_at": utcnow(), **fields}
    try:
        result = await _col(db).insert_one(document)
    except DuplicateKeyError:
        return None
    document["_id"] = result.inserted_id
    document.pop("image_base64", None)
    return serialize(document)


async def delete(db, name: str) -> bool:
    result = await _col(db).delete_one({"name": name})
    return result.deleted_count > 0
