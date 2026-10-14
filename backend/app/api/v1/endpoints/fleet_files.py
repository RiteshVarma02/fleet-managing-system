"""Fleet graph JSON + map: upload, download, history, push, sync status.

One graph and one map for the whole fleet; every robot receives a copy.
Reading is open to any signed-in user; changing/pushing needs an admin.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.api.deps import Principal, get_current_user, get_db, require_admin
from app.schemas.common import DataResponse
from app.services import fleet_file_service as svc

router = APIRouter(prefix="/fleet-files", tags=["fleet-files"])
waypoints_router = APIRouter(prefix="/waypoints", tags=["waypoints"])

Kind = Literal["graph", "map"]


class PushBody(BaseModel):
    robot_ids: Optional[List[str]] = Field(default=None, description="Default: every connected robot")
    version: Optional[int] = Field(default=None, ge=1, description="Default: the active version")


# --- static routes first (before any /{param} route) -----------------------
@router.get("", response_model=DataResponse[Dict[str, Any]])
async def overview(db: AsyncIOMotorDatabase = Depends(get_db), _: Principal = Depends(get_current_user)):
    return DataResponse(data=await svc.overview(db))


@router.get("/status", response_model=DataResponse[Dict[str, Any]])
async def sync_status(db: AsyncIOMotorDatabase = Depends(get_db), _: Principal = Depends(get_current_user)):
    return DataResponse(data=await svc.status(db))


@router.get("/map/preview", response_model=DataResponse[Dict[str, Any]])
async def map_preview(db: AsyncIOMotorDatabase = Depends(get_db), _: Principal = Depends(get_current_user)):
    """Active fleet map as PNG (base64) + resolution/origin, for the dashboard."""
    return DataResponse(data=await svc.map_preview(db))


@router.post("/graph", response_model=DataResponse[Dict[str, Any]], status_code=201)
async def upload_graph(
    file: UploadFile = File(...),
    note: str = Form(default="", max_length=300),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_admin),
):
    data = await svc.upload_graph(db, file.filename or "amr_path.json", await file.read(), user.username, note)
    return DataResponse(data=data)


@router.post("/map", response_model=DataResponse[Dict[str, Any]], status_code=201)
async def upload_map(
    yaml_file: UploadFile = File(...),
    image_file: UploadFile = File(...),
    note: str = Form(default="", max_length=300),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_admin),
):
    data = await svc.upload_map(
        db, yaml_file.filename or "map.yaml", await yaml_file.read(),
        image_file.filename or "map.pgm", await image_file.read(), user.username, note,
    )
    return DataResponse(data=data)


# --- per-kind routes --------------------------------------------------------
@router.get("/{kind}/download")
async def download(
    kind: Kind,
    version: Optional[int] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    name, media_type, content = await svc.download(db, kind, version)
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/{kind}/versions/{version}/activate", response_model=DataResponse[Dict[str, Any]])
async def activate_version(
    kind: Kind, version: int,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    """Make an older version active again (rollback). Does not push by itself."""
    return DataResponse(data=await svc.activate(db, kind, version))


@router.post("/{kind}/push", response_model=DataResponse[Dict[str, Any]])
async def push(
    kind: Kind, body: PushBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_admin),
):
    """Send the file to the chosen (default: all connected) robots and wait for acks."""
    return DataResponse(data=await svc.push(db, kind, user.username, body.robot_ids, body.version))


@waypoints_router.get("", response_model=DataResponse[Dict[str, Any]])
async def list_waypoints(db: AsyncIOMotorDatabase = Depends(get_db), _: Principal = Depends(get_current_user)):
    """Waypoints of the active graph (names the robots can be sent to)."""
    return DataResponse(data=await svc.list_waypoints(db))
