"""`map_state` collection — the single active-map pointer.

Mirrors the industry-standard map-server model: raster files stay on disk
(`settings.maps_dir`) and Mongo only remembers which map is active, plus the
metadata needed to rebuild the ROS OccupancyGrid on the next startup.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from app.db.documents import serialize, utcnow
from app.db.mongo import Collections

# One fixed document id — there is exactly one active map at any time.
ACTIVE_KEY = "active"


def _col(db):
    return db[Collections.map_state]


async def get(db) -> Optional[Dict[str, Any]]:
    """Return the active-map pointer, or None when nothing has been activated."""
    return serialize(await _col(db).find_one({"_id": ACTIVE_KEY}))


async def set(
    db,
    *,
    name: str,
    metadata: Dict[str, Any],
    source: str,
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically point the active map at `name` (single upserted doc)."""
    updates: Dict[str, Any] = {
        "name": name,
        "metadata": metadata,
        "source": source,
        "robot_id": robot_id,
        "updated_at": utcnow(),
    }
    doc = await _col(db).find_one_and_update(
        {"_id": ACTIVE_KEY},
        {"$set": updates, "$setOnInsert": {"created_at": utcnow()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return serialize(doc)  # type: ignore[return-value]


async def clear(db) -> bool:
    """Drop the active pointer (used by map deletion)."""
    result = await _col(db).delete_one({"_id": ACTIVE_KEY})
    return result.deleted_count > 0