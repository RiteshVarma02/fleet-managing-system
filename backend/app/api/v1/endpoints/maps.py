"""Map upload, activation, listing, SLAM and map-saving endpoints."""

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
    PromoteRobotMapCommand,
    SaveFromRobotCommand,
    SaveMapCommand,
    SavedMapResponse,
    SlamCommand,
)
from app.services.map_service import map_service

router = APIRouter(prefix="/maps", tags=["maps"])


@router.post("/from-robot", response_model=MapImageResponse)
async def promote_from_robot(
    body: PromoteRobotMapCommand,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    result = await map_service.promote_robot_map(db, body.robot_id, body.map_name)
    return MapImageResponse(image=result["image"], metadata=MapMetadata(**result["metadata"]))


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
    data = map_service.current_map()
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


@router.post("/slam/start", response_model=DataResponse[dict])
def start_slam(body: SlamCommand, _: Principal = Depends(require_operator)):
    return DataResponse(data=map_service.start_slam(body.robot_id, body.map_name))


@router.post("/slam/stop", response_model=StatusResponse)
def stop_slam(_: Principal = Depends(require_operator)):
    stopped = map_service.stop_slam()
    return StatusResponse(message="SLAM stopped" if stopped else "SLAM was not running")


@router.get("/slam/status", response_model=DataResponse[dict])
def slam_status(_: Principal = Depends(get_current_user)):
    return DataResponse(data={"running": map_service.slam_running()})


@router.post("/save-from-robot", response_model=SavedMapResponse)
async def save_from_robot(
    body: SaveFromRobotCommand,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    result = await map_service.save_from_robot(db, body.robot_id, body.filename)
    return SavedMapResponse(
        image=result["image"], metadata=MapMetadata(**result["metadata"]), name=result["name"]
    )


@router.post("/save", response_model=DataResponse[dict])
def save_map(body: SaveMapCommand, _: Principal = Depends(require_operator)):
    return DataResponse(data=map_service.save_map(body.filename))
