"""`pending_requests` collection — the task request queue (auto-assignment)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument

from app.db.documents import serialize, to_object_id, utcnow
from app.db.mongo import Collections

PENDING = "pending"
ASSIGNED = "assigned"
CANCELLED = "cancelled"


def _col(db):
    return db[Collections.pending_requests]


async def create(
    db,
    *,
    task_type: str,
    from_location_id: Optional[str],
    to_location_id: Optional[str],
    repeats: int,
    robot_type: Optional[str],
    created_by: Optional[str],
) -> Dict[str, Any]:
    document = {
        "task_type": task_type,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "repeats": int(repeats),
        "robot_type": robot_type,
        "status": PENDING,
        "assigned_task_id": None,
        "assigned_robot_id": None,
        "created_by": created_by,
        "created_at": utcnow(),
    }
    result = await _col(db).insert_one(document)
    document["_id"] = result.inserted_id
    return serialize(document)  # type: ignore[return-value]


async def list_requests(db, *, status: Optional[str] = PENDING) -> List[Dict[str, Any]]:
    query = {"status": status} if status else {}
    cursor = _col(db).find(query).sort("created_at", 1)
    return [serialize(doc) for doc in await cursor.to_list(length=500)]  # type: ignore[misc]


async def claim_oldest(db, *, robot_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Atomically take the oldest pending request (safe with many workers)."""
    query: Dict[str, Any] = {"status": PENDING}
    if robot_type:
        query["$or"] = [{"robot_type": None}, {"robot_type": robot_type}]
    doc = await _col(db).find_one_and_update(
        query,
        {"$set": {"status": ASSIGNED, "claimed_at": utcnow()}},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)


async def mark_assigned(db, request_id: str, task_id: str, robot_id: str) -> None:
    oid = to_object_id(request_id)
    if oid is not None:
        await _col(db).update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": ASSIGNED,
                    "assigned_task_id": task_id,
                    "assigned_robot_id": robot_id,
                    "assigned_at": utcnow(),
                }
            },
        )


async def release(db, request_id: str) -> None:
    oid = to_object_id(request_id)
    if oid is not None:
        await _col(db).update_one({"_id": oid}, {"$set": {"status": PENDING}})


async def cancel(db, request_id: str) -> bool:
    oid = to_object_id(request_id)
    if oid is None:
        return False
    result = await _col(db).update_one(
        {"_id": oid, "status": PENDING},
        {"$set": {"status": CANCELLED, "cancelled_at": utcnow()}},
    )
    return result.modified_count > 0
