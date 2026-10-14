"""Async MongoDB client factory and index bootstrap.

MongoDB is the single source of truth. Local (Docker/on-prem) and Atlas are
selected purely by configuration — the code path is identical.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_client: Optional[AsyncIOMotorClient] = None


class Collections:
    users = "users"
    robots = "robots"
    robot_registrations = "pending_robot_registrations"
    tasks = "tasks"
    task_history = "task_history"
    locations = "locations"
    pending_requests = "pending_requests"
    fleet_files = "fleet_files"
    robot_file_state = "robot_file_state"


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.mongo_uri,
            maxPoolSize=settings.mongo_max_pool_size,
            minPoolSize=settings.mongo_min_pool_size,
            serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
            tz_aware=True,
            appname=settings.app_name,
        )
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency — one shared pooled client per process."""
    return get_client()[settings.mongo_db_name]


async def connect_and_verify() -> AsyncIOMotorDatabase:
    """Fail fast with a clear error instead of degrading silently."""
    db = get_database()
    await db.command("ping")
    logger.info("MongoDB connected (mode=%s, db=%s)", settings.mongo_mode, settings.mongo_db_name)
    return db


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ensure_indexes() -> None:
    db = get_database()
    await db[Collections.users].create_index([("username", ASCENDING)], unique=True)
    await db[Collections.robots].create_index([("robot_id", ASCENDING)], unique=True)
    await db[Collections.robots].create_index(
        [("mac_address", ASCENDING)], unique=True, sparse=True
    )
    await db[Collections.robots].create_index([("is_deleted", ASCENDING), ("status", ASCENDING)])
    await db[Collections.robot_registrations].create_index(
        [("mac_address", ASCENDING)], unique=True
    )
    await db[Collections.robot_registrations].create_index([("status", ASCENDING)])
    await db[Collections.tasks].create_index([("robot_id", ASCENDING), ("status", ASCENDING)])
    await db[Collections.tasks].create_index([("created_at", DESCENDING)])
    await db[Collections.task_history].create_index([("task_id", ASCENDING), ("at", ASCENDING)])
    await db[Collections.locations].create_index([("name", ASCENDING)], unique=True)
    await db[Collections.fleet_files].create_index(
        [("kind", ASCENDING), ("version", DESCENDING)], unique=True
    )
    await db[Collections.robot_file_state].create_index(
        [("robot_id", ASCENDING), ("kind", ASCENDING)], unique=True
    )
    await db[Collections.pending_requests].create_index(
        [("status", ASCENDING), ("created_at", ASCENDING)]
    )
    # Serves the scheduler's due-request claim: status + scheduled_at filter
    # with created_at as the sort key.
    await db[Collections.pending_requests].create_index(
        [("status", ASCENDING), ("scheduled_at", ASCENDING), ("created_at", ASCENDING)]
    )
    logger.info("MongoDB indexes ensured")
