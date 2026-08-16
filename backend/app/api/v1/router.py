"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    locations,
    maps,
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
api_router.include_router(locations.router)
api_router.include_router(tasks.router)
api_router.include_router(maps.router)
api_router.include_router(telemetry.router)
