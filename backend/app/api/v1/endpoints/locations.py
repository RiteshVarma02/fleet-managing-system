"""Location (waypoint) CRUD."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.db.repositories import locations_repo as location_repo
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.task import LocationCreate, LocationOut

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=DataResponse[List[LocationOut]])
async def list_locations(
    map_name: str | None = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await location_repo.list_all(db, map_name=map_name)
    return DataResponse(data=[LocationOut.from_document(row) for row in rows])


@router.post("", response_model=DataResponse[LocationOut], status_code=201)
async def create_location(
    body: LocationCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    existing = await location_repo.list_all(db, map_name=body.map_name)
    if any(str(item.get("name")).strip().lower() == body.name.strip().lower() for item in existing):
        raise ConflictError(f"Location '{body.name}' already exists on this map")
    location = await location_repo.create(
        db, name=body.name, x=body.x, y=body.y, theta=body.theta, map_name=body.map_name
    )
    if location is None:
        raise ConflictError(f"Location '{body.name}' already exists on this map")
    return DataResponse(data=LocationOut.from_document(location))


@router.delete("/{location_id}", response_model=StatusResponse)
async def delete_location(
    location_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    if not await location_repo.delete(db, location_id):
        raise NotFoundError(f"Location '{location_id}' not found")
    return StatusResponse(message="Location deleted")
