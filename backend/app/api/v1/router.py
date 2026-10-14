"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    fleet_files,
    robots,
    system,
    tasks,
    telemetry,
    users,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(robots.router)
api_router.include_router(tasks.router)
api_router.include_router(fleet_files.router)
api_router.include_router(fleet_files.waypoints_router)
api_router.include_router(telemetry.router)
