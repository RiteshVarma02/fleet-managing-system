"""`robots` collection access. No business logic lives here."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument, UpdateOne

from app.db.documents import RobotStatus, normalize_mac, serialize, utcnow
from app.db.mongo import Collections

_ID_RE = re.compile(r"robot_(\d+)$")


def _col(db: AsyncIOMotorDatabase):
    return db[Collections.robots]


DEFAULTS: Dict[str, Any] = {
    "display_name": "",
    "robot_type": None,  # None -> default_robot_type from fleet_topics.yaml
    "status": RobotStatus.offline.value,
    "battery_percentage": None,
    "last_position": {"x": 0.0, "y": 0.0, "theta": 0.0},
    "mac_address": None,
    "hostname": None,
    "ip_address": None,
    "approved": False,
    "active_map_id": None,
    "is_deleted": False,
}


async def get(db, robot_id: str, *, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
    query: Dict[str, Any] = {"robot_id": robot_id}
    if not include_deleted:
        query["is_deleted"] = False
    return serialize(await _col(db).find_one(query))


async def get_by_mac(db, mac_address: str) -> Optional[Dict[str, Any]]:
    return serialize(await _col(db).find_one({"mac_address": normalize_mac(mac_address)}))


async def list_all(
    db, *, include_deleted: bool = False, approved_only: bool = False
) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if not include_deleted:
        query["is_deleted"] = False
    if approved_only:
        query["approved"] = True
    cursor = _col(db).find(query).sort("robot_id", 1)
    return [serialize(doc) for doc in await cursor.to_list(length=1000)]  # type: ignore[misc]


async def upsert(db, robot_id: str, **fields: Any) -> Dict[str, Any]:
    """Create-or-update a robot. Only provided fields are written."""
    updates = {k: v for k, v in fields.items() if v is not None}
    if "mac_address" in updates:
        updates["mac_address"] = normalize_mac(updates["mac_address"])
    if isinstance(updates.get("status"), RobotStatus):
        updates["status"] = updates["status"].value
    touch_last_seen = updates.pop("touch_last_seen", True)
    updates["updated_at"] = utcnow()
    if touch_last_seen:
        updates["last_seen_at"] = utcnow()

    on_insert = {k: v for k, v in DEFAULTS.items() if k not in updates}
    on_insert["created_at"] = utcnow()
    if "display_name" not in updates:
        on_insert["display_name"] = robot_id

    doc = await _col(db).find_one_and_update(
        {"robot_id": robot_id},
        {"$set": updates, "$setOnInsert": on_insert},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)  # type: ignore[return-value]


async def bulk_apply_telemetry(db, snapshots: Iterable[Dict[str, Any]]) -> int:
    """One round-trip for every robot's latest telemetry (write-behind path)."""
    operations: List[UpdateOne] = []
    for snap in snapshots:
        robot_id = snap.get("robot_id")
        if not robot_id:
            continue
        update: Dict[str, Any] = {
            "last_seen_at": snap.get("at") or utcnow(),
            "updated_at": utcnow(),
        }
        if snap.get("position") is not None:
            update["last_position"] = snap["position"]
        if snap.get("battery") is not None:
            update["battery_percentage"] = snap["battery"]
        if snap.get("status") is not None:
            update["status"] = snap["status"]
        operations.append(UpdateOne({"robot_id": robot_id}, {"$set": update}))
    if not operations:
        return 0
    result = await _col(db).bulk_write(operations, ordered=False)
    return result.modified_count


async def set_status(db, robot_id: str, status: RobotStatus) -> None:
    await _col(db).update_one(
        {"robot_id": robot_id},
        {"$set": {"status": status.value, "updated_at": utcnow()}},
    )


async def clear_active_task(db, robot_id: str) -> None:
    """Explicit unset: `upsert` ignores None values, so it can't clear this."""
    await _col(db).update_one(
        {"robot_id": robot_id},
        {"$set": {"active_task_id": None, "updated_at": utcnow()}},
    )


async def mark_all_offline(db) -> int:
    result = await _col(db).update_many(
        {"is_deleted": False},
        {"$set": {"status": RobotStatus.offline.value, "updated_at": utcnow()}},
    )
    return result.modified_count


async def soft_delete(db, robot_id: str) -> bool:
    result = await _col(db).update_one(
        {"robot_id": robot_id, "is_deleted": False},
        {
            "$set": {
                "is_deleted": True,
                "status": RobotStatus.offline.value,
                "deleted_at": utcnow(),
                "updated_at": utcnow(),
            }
        },
    )
    return result.modified_count > 0


async def next_robot_id(db) -> str:
    """Sequential `robot_N` id, preserving the legacy naming scheme."""
    highest = 0
    cursor = _col(db).find({}, {"robot_id": 1})
    for doc in await cursor.to_list(length=5000):
        match = _ID_RE.match(str(doc.get("robot_id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"robot_{highest + 1}"
