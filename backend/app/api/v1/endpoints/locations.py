"""Location (waypoint) CRUD."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user
from app.core.exceptions import ConflictError, NotFoundError
from app.db.repositories import locations as location_repo
from app.db.session import get_db
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.task import LocationCreate, LocationOut

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=DataResponse[List[LocationOut]])
def list_locations(map_name: str | None = None, db: Session = Depends(get_db),
                   _: Principal = Depends(get_current_user)):
    rows = location_repo.list_locations(db, map_name)
    return DataResponse(data=[LocationOut.model_validate(row) for row in rows])


@router.post("", response_model=DataResponse[LocationOut], status_code=201)
def create_location(body: LocationCreate, db: Session = Depends(get_db),
                    _: Principal = Depends(get_current_user)):
    if location_repo.get_location_by_name(db, body.name, body.map_name):
        raise ConflictError(f"Location '{body.name}' already exists on this map")
    location = location_repo.create_location(
        db, name=body.name, x=body.x, y=body.y, theta=body.theta, map_name=body.map_name
    )
    return DataResponse(data=LocationOut.model_validate(location))


@router.delete("/{location_id}", response_model=StatusResponse)
def delete_location(location_id: str, db: Session = Depends(get_db),
                    _: Principal = Depends(get_current_user)):
    if not location_repo.delete_location(db, location_id):
        raise NotFoundError(f"Location '{location_id}' not found")
    return StatusResponse(message="Location deleted")
