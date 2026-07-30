"""Map upload, listing, SLAM and map-saving endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import Principal, get_current_user
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.map import MapImageResponse, MapMetadata, MapSummary, SaveMapCommand, SlamCommand
from app.services.map_service import map_service

router = APIRouter(prefix="/maps", tags=["maps"])


@router.post("/load", response_model=MapImageResponse)
async def load_map(
    file: UploadFile = File(...),
    resolution: float = Form(default=0.05, gt=0.0, le=10.0),
    origin_x: float = Form(default=0.0),
    origin_y: float = Form(default=0.0),
    _: Principal = Depends(get_current_user),
):
    content = await file.read()
    result = map_service.load_map(file.filename or "map.pgm", content, resolution, origin_x, origin_y)
    return MapImageResponse(image=result["image"], metadata=MapMetadata(**result["metadata"]))


@router.get("/current", response_model=MapImageResponse)
def current_map(_: Principal = Depends(get_current_user)):
    data = map_service.current_map()
    return MapImageResponse(image=data["image"], metadata=MapMetadata(**data["metadata"]))


@router.get("", response_model=DataResponse[List[MapSummary]])
def list_maps(_: Principal = Depends(get_current_user)):
    return DataResponse(data=[MapSummary(**item) for item in map_service.list_maps()])


@router.delete("/{name}", response_model=StatusResponse)
def delete_map(name: str, _: Principal = Depends(get_current_user)):
    map_service.delete_map(name)
    return StatusResponse(message=f"Map '{name}' deleted")


@router.post("/slam/start", response_model=DataResponse[dict])
def start_slam(body: SlamCommand, _: Principal = Depends(get_current_user)):
    return DataResponse(data=map_service.start_slam(body.robot_id, body.map_name))


@router.post("/slam/stop", response_model=StatusResponse)
def stop_slam(_: Principal = Depends(get_current_user)):
    stopped = map_service.stop_slam()
    return StatusResponse(message="SLAM stopped" if stopped else "SLAM was not running")


@router.get("/slam/status", response_model=DataResponse[dict])
def slam_status(_: Principal = Depends(get_current_user)):
    return DataResponse(data={"running": map_service.slam_running()})


@router.post("/save", response_model=DataResponse[dict])
def save_map(body: SaveMapCommand, _: Principal = Depends(get_current_user)):
    return DataResponse(data=map_service.save_map(body.filename))
