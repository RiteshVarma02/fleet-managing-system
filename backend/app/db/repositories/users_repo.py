"""`users` collection access."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.documents import Role, serialize, to_object_id, utcnow
from app.db.mongo import Collections


def _col(db):
    return db[Collections.users]


async def get_by_username(db, username: str) -> Optional[Dict[str, Any]]:
    return serialize(await _col(db).find_one({"username": username.strip().lower()}))


async def get(db, user_id: str) -> Optional[Dict[str, Any]]:
    oid = to_object_id(user_id)
    if oid is None:
        return None
    return serialize(await _col(db).find_one({"_id": oid}))


async def list_all(db) -> List[Dict[str, Any]]:
    cursor = _col(db).find({}, {"password_hash": 0}).sort("username", 1)
    return [serialize(doc) for doc in await cursor.to_list(length=500)]  # type: ignore[misc]


async def create(db, username: str, password_hash: str, role: Role) -> Optional[Dict[str, Any]]:
    document = {
        "username": username.strip().lower(),
        "password_hash": password_hash,
        "role": role.value,
        "active": True,
        "created_at": utcnow(),
        "last_login_at": None,
    }
    try:
        result = await _col(db).insert_one(document)
    except DuplicateKeyError:
        return None
    document["_id"] = result.inserted_id
    return serialize(document)


async def update(db, user_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    oid = to_object_id(user_id)
    if oid is None:
        return None
    updates = {k: v for k, v in fields.items() if v is not None}
    if isinstance(updates.get("role"), Role):
        updates["role"] = updates["role"].value
    updates["updated_at"] = utcnow()
    doc = await _col(db).find_one_and_update(
        {"_id": oid},
        {"$set": updates},
        projection={"password_hash": 0},
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)


async def touch_login(db, user_id: str) -> None:
    oid = to_object_id(user_id)
    if oid is not None:
        await _col(db).update_one({"_id": oid}, {"$set": {"last_login_at": utcnow()}})


async def count(db) -> int:
    return await _col(db).count_documents({})
