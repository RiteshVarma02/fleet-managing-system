"""`tasks` + `task_history` collections."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pymongo import ReturnDocument

from app.db.documents import TaskStatus, serialize, to_object_id, utcnow
from app.db.mongo import Collections


def _col(db):
    return db[Collections.tasks]


def _status_value(status: Union[TaskStatus, str]) -> str:
    """Accept enum or raw string; reject unknown values."""
    return TaskStatus(status).value


def _history(db):
    return db[Collections.task_history]


async def create(
    db,
    *,
    task_type: str,
    robot_id: Optional[str],
    stops: List[str],
    repeats: int,
    mode: str,
    created_by: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    document = {
        "task_type": task_type,
        "robot_id": robot_id,
        "stops": list(stops),
        "mode": mode,
        "repeats": int(repeats),
        "completed_repeats": 0,
        "cursor": {"cycle": 0, "stop_index": -1},  # last reached stop (audit/UI)
        "status": TaskStatus.pending.value,
        "message": None,
        "payload": payload or {},
        "created_by": created_by,
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "started_at": None,
        "finished_at": None,
    }
    result = await _col(db).insert_one(document)
    document["_id"] = result.inserted_id
    await append_history(db, str(result.inserted_id), TaskStatus.pending, "Task created")
    return serialize(document)  # type: ignore[return-value]


async def get(db, task_id: str) -> Optional[Dict[str, Any]]:
    oid = to_object_id(task_id)
    if oid is None:
        return None
    return serialize(await _col(db).find_one({"_id": oid}))


async def list_tasks(
    db,
    *,
    robot_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if robot_id:
        query["robot_id"] = robot_id
    if status:
        query["status"] = status
    cursor = _col(db).find(query).sort("created_at", -1).limit(max(1, min(limit, 200)))
    return [serialize(doc) for doc in await cursor.to_list(length=limit)]  # type: ignore[misc]


async def list_active(db) -> List[Dict[str, Any]]:
    cursor = _col(db).find(
        {"status": {"$in": [TaskStatus.running.value, TaskStatus.paused.value,
                            TaskStatus.awaiting_approval.value]}}
    )
    return [serialize(doc) for doc in await cursor.to_list(length=500)]  # type: ignore[misc]


async def update(db, task_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    oid = to_object_id(task_id)
    if oid is None:
        return None
    updates = {k: v for k, v in fields.items() if v is not None}
    if isinstance(updates.get("status"), TaskStatus):
        updates["status"] = updates["status"].value
    updates["updated_at"] = utcnow()
    return serialize(
        await _col(db).find_one_and_update(
            {"_id": oid}, {"$set": updates}, return_document=ReturnDocument.AFTER
        )
    )


async def set_status(
    db, task_id: str, status: Union[TaskStatus, str], message: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    status = TaskStatus(status)
    updates: Dict[str, Any] = {"status": status.value, "updated_at": utcnow()}
    if message is not None:
        updates["message"] = message
    if status is TaskStatus.running:
        updates["started_at"] = utcnow()
    if status in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}:
        updates["finished_at"] = utcnow()

    oid = to_object_id(task_id)
    if oid is None:
        return None
    doc = await _col(db).find_one_and_update(
        {"_id": oid}, {"$set": updates}, return_document=ReturnDocument.AFTER
    )
    if doc is not None:
        await append_history(db, task_id, status, message)
    return serialize(doc)


async def increment_repeats(db, task_id: str) -> None:
    oid = to_object_id(task_id)
    if oid is not None:
        await _col(db).update_one({"_id": oid}, {"$inc": {"completed_repeats": 1}})


async def set_cursor(db, task_id: str, cycle: int, stop_index: int) -> None:
    """Persist the last reached stop. Called on arrivals only, never per tick."""
    oid = to_object_id(task_id)
    if oid is not None:
        await _col(db).update_one(
            {"_id": oid},
            {"$set": {"cursor": {"cycle": cycle, "stop_index": stop_index}, "updated_at": utcnow()}},
        )


async def delete(db, task_id: str) -> bool:
    oid = to_object_id(task_id)
    if oid is None:
        return False
    result = await _col(db).delete_one({"_id": oid})
    await _history(db).delete_many({"task_id": task_id})
    return result.deleted_count > 0


async def append_history(
    db, task_id: str, status: Union[TaskStatus, str], message: Optional[str] = None
) -> None:
    await _history(db).insert_one(
        {"task_id": task_id, "status": _status_value(status), "message": message, "at": utcnow()}
    )


async def history(db, task_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    cursor = _history(db).find({"task_id": task_id}).sort("at", 1).limit(limit)
    return [serialize(doc) for doc in await cursor.to_list(length=limit)]  # type: ignore[misc]
