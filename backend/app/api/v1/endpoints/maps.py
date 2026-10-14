"""Fleet map: upload, activation, listing (one map shared by every robot)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_operator
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.map import (
    MapImageResponse,
    MapMetadata,
    MapNameBody,
    MapSummary,
)
from app.services.map_service import map_service

router = APIRouter(prefix="/maps", tags=["maps"])


@router.post("/load", response_model=MapImageResponse)
async def load_map(
    file: UploadFile = File(...),
    resolution: float = Form(default=0.05, gt=0.0, le=10.0),
    origin_x: float = Form(default=0.0),
    origin_y: float = Form(default=0.0),
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    content = await file.read()
    result = await map_service.load_map(
        db, file.filename or "map.pgm", content, resolution, origin_x, origin_y
    )
    return MapImageResponse(image=result["image"], metadata=MapMetadata(**result["metadata"]))


@router.post("/activate", response_model=MapImageResponse)
async def activate_map(
    body: MapNameBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    result = await map_service.activate_map(db, body.map_name)
    return MapImageResponse(image=result["image"], metadata=MapMetadata(**result["metadata"]))


@router.get("/current", response_model=MapImageResponse)
def current_map(_: Principal = Depends(get_current_user)):
    try:
        data = map_service.current_map()
    except Exception:
        return MapImageResponse(image="", metadata=MapMetadata(
            width=0, height=0, resolution=0.05, origin_x=0.0, origin_y=0.0
        ))
    return MapImageResponse(image=data["image"], metadata=MapMetadata(**data["metadata"]))


@router.get("", response_model=DataResponse[List[MapSummary]])
def list_maps(_: Principal = Depends(get_current_user)):
    return DataResponse(data=[MapSummary(**item) for item in map_service.list_maps()])


@router.delete("/{name}", response_model=StatusResponse)
async def delete_map(
    name: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    await map_service.delete_map(db, name)
    return StatusResponse(message=f"Map '{name}' deleted")
