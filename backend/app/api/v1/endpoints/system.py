"""Health, readiness and runtime introspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import Principal, get_current_user
from app.core.config import settings
from app.db.session import engine
from app.ros.manager import ros_manager
from app.ros.runtime import ros_error
from app.schemas.common import DataResponse
from app.services.map_service import map_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness probe — must stay dependency-free and always cheap."""
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/ready")
def ready() -> dict:
    """Readiness probe — verifies the database is reachable."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "ros": ros_manager.available}


@router.get("/system/info", response_model=DataResponse[dict])
def system_info(_: Principal = Depends(get_current_user)):
    return DataResponse(
        data={
            "environment": settings.environment,
            "ros_enabled": settings.ros_enabled,
            "ros_available": ros_manager.available,
            "ros_error": ros_error(),
            "connected_robots": ros_manager.connected_robot_ids(),
            "slam_running": map_service.slam_running(),
        }
    )
