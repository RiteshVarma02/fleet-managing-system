"""`pending_robot_registrations` collection — MAC-based zero-touch onboarding."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument

from app.db.documents import RegistrationStatus, normalize_mac, serialize, utcnow
from app.db.mongo import Collections


def _col(db):
    return db[Collections.robot_registrations]


async def check_in(
    db, mac_address: str, hostname: Optional[str], ip_address: Optional[str]
) -> Dict[str, Any]:
    """Upsert a check-in. A previously rejected MAC returns to `pending`."""
    mac = normalize_mac(mac_address)
    doc = await _col(db).find_one_and_update(
        {"mac_address": mac},
        {
            "$set": {
                "hostname": hostname,
                "ip_address": ip_address,
                "status": RegistrationStatus.pending.value,
                "last_seen_at": utcnow(),
            },
            "$setOnInsert": {"mac_address": mac, "first_seen_at": utcnow()},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)  # type: ignore[return-value]


async def get(db, mac_address: str) -> Optional[Dict[str, Any]]:
    return serialize(await _col(db).find_one({"mac_address": normalize_mac(mac_address)}))


async def list_pending(db) -> List[Dict[str, Any]]:
    cursor = (
        _col(db)
        .find({"status": RegistrationStatus.pending.value})
        .sort("first_seen_at", 1)
    )
    return [serialize(doc) for doc in await cursor.to_list(length=500)]  # type: ignore[misc]


async def set_status(db, mac_address: str, status: RegistrationStatus) -> Optional[Dict[str, Any]]:
    doc = await _col(db).find_one_and_update(
        {"mac_address": normalize_mac(mac_address)},
        {"$set": {"status": status.value, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)
