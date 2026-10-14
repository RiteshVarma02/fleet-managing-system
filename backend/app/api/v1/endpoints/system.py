"""Health, readiness and runtime introspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import Principal, get_current_user, require_developer
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.db.mongo import connect_and_verify
from app.ros.manager import ros_manager
from app.ros.runtime import ros_error
from app.ros.topics_registry import TopicConfigError, robot_types, topic_registry
from app.schemas.common import DataResponse

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness probe — must stay dependency-free and always cheap."""
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/ready")
async def ready() -> dict:
    """Readiness probe — verifies the database is reachable."""
    try:
        await connect_and_verify()
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
            "ros_domain_id": settings.ros_domain_id,
            "connected_robots": ros_manager.connected_robot_ids(),
            "robot_types": robot_types(),
            "topics_file": str(topic_registry.path),
            "telemetry_ws_interval_seconds": settings.telemetry_ws_interval_seconds,
            "telemetry_stale_after_seconds": settings.telemetry_stale_after_seconds,
        }
    )


@router.get("/system/topics", response_model=DataResponse[dict])
def topics(_: Principal = Depends(require_developer)):
    """The parsed fleet_topics.yaml: every topic name and type, per robot type."""
    return DataResponse(data=topic_registry.describe())


@router.post("/system/topics/reload", response_model=DataResponse[dict])
def reload_topics(_: Principal = Depends(require_developer)):
    """Re-read fleet_topics.yaml. Robots listed in `reconnect_required` keep
    their old topics until they are disconnected and connected again."""
    try:
        return DataResponse(data=ros_manager.reload_topics())
    except TopicConfigError as exc:
        raise ValidationError(f"fleet_topics.yaml not applied: {exc}") from exc
