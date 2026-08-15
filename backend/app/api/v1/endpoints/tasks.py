"""Task, pick-drop and pending-request endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db
from app.db.documents import TaskStatus
from app.core.exceptions import NotFoundError
from app.db.repositories import pending_requests_repo, tasks_repo
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.robot import RobotIdBody
from app.schemas.task import (
    PickDropStart,
    TaskCreate,
    TaskHistoryOut,
    TaskRequestCreate,
    TaskRequestOut,
    TaskOut,
    TaskUpdate,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=DataResponse[List[TaskOut]])
async def list_tasks(
    status: Optional[TaskStatus] = None,
    robot_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await tasks_repo.list_tasks(
        db,
        status=status.value if status else None,
        robot_id=robot_id,
        limit=limit,
    )
    return DataResponse(data=[TaskOut.from_document(row) for row in rows])


@router.post("", response_model=DataResponse[TaskOut], status_code=201)
async def create_task(
    body: TaskCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(get_current_user),
):
    task = await tasks_repo.create(
        db,
        task_type=body.type,
        robot_id=body.robot_id,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        repeats=body.repeats,
        created_by=user.username,
        payload=body.payload,
    )
    return DataResponse(data=TaskOut.from_document(task))


@router.get("/{task_id}", response_model=DataResponse[TaskOut])
async def get_task(
    task_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    task = await tasks_repo.get(db, task_id)
    if task is None:
        raise NotFoundError(f"Task '{task_id}' not found")
    return DataResponse(data=TaskOut.from_document(task))


@router.patch("/{task_id}", response_model=DataResponse[TaskOut])
async def update_task(
    task_id: str,
    body: TaskUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    task = await tasks_repo.set_status(db, task_id, body.status, message=body.message)
    if task is None:
        raise NotFoundError(f"Task '{task_id}' not found")
    return DataResponse(data=TaskOut.from_document(task))


@router.get("/{task_id}/history", response_model=DataResponse[List[TaskHistoryOut]])
async def task_history(
    task_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await tasks_repo.history(db, task_id)
    return DataResponse(data=[TaskHistoryOut.model_validate(row) for row in rows])


# --------------------------------------------------------------------------
# Pick & drop execution
# --------------------------------------------------------------------------
@router.post("/pickdrop/start", response_model=DataResponse[dict])
def start_pickdrop(body: PickDropStart, _: Principal = Depends(get_current_user)):
    raise HTTPException(
        status_code=501,
        detail="Pick-drop worker migration to Mongo is in progress. Use /tasks for CRUD.",
    )


@router.post("/pickdrop/stop", response_model=StatusResponse)
def stop_pickdrop(body: RobotIdBody, _: Principal = Depends(get_current_user)):
    raise HTTPException(
        status_code=501,
        detail="Pick-drop worker migration to Mongo is in progress.",
    )


@router.get("/pickdrop/{robot_id}/status", response_model=DataResponse[Optional[dict]])
def pickdrop_status(robot_id: str, _: Principal = Depends(get_current_user)):
    return DataResponse(data=None)


# --------------------------------------------------------------------------
# Pending requests (unassigned work)
# --------------------------------------------------------------------------
@router.post("/requests", response_model=DataResponse[TaskRequestOut], status_code=201)
async def create_request(
    body: TaskRequestCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(get_current_user),
):
    request = await pending_requests_repo.create(
        db,
        task_type=body.type,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        robot_type=body.robot_type,
        repeats=body.repeats,
        created_by=user.username,
    )
    return DataResponse(data=TaskRequestOut.from_document(request))


@router.get("/requests/unassigned", response_model=DataResponse[List[TaskRequestOut]])
async def unassigned_requests(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await pending_requests_repo.list_requests(db, status=pending_requests_repo.PENDING)
    return DataResponse(data=[TaskRequestOut.from_document(row) for row in rows])
