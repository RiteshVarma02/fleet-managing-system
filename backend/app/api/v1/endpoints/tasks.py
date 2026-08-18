"""Task, pick-drop and pending-request endpoints.

Execution is owned by `task_service.task_engine`: these routes only validate
input, persist intent and hand off. Progress reads come from the engine's
in-memory state, so polling a running task costs no database round trip.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_operator
from app.core.exceptions import NotFoundError
from app.db.documents import TaskStatus
from app.db.repositories import pending_requests_repo, tasks_repo
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.robot import RobotIdBody
from app.schemas.task import (
    PickDropStart,
    TaskCreate,
    TaskHistoryOut,
    TaskOut,
    TaskRequestCreate,
    TaskRequestOut,
    TaskUpdate,
)
from app.services.task_service import start_pick_drop, task_engine

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _with_progress(task: Dict[str, Any]) -> Dict[str, Any]:
    task_id = str(task.get("id"))
    return {"task": TaskOut.from_document(task), "progress": task_engine.progress(task_id)}


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
    user: Principal = Depends(require_operator),
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
    _: Principal = Depends(require_operator),
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
# Execution lifecycle
# --------------------------------------------------------------------------
@router.post("/{task_id}/start", response_model=DataResponse[dict])
async def start_task(
    task_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    task = await task_engine.start_task(db, task_id)
    return DataResponse(data=_with_progress(task))


@router.post("/{task_id}/cancel", response_model=StatusResponse)
async def cancel_task(
    task_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    await task_engine.cancel_task(db, task_id)
    return StatusResponse(message=f"Task {task_id} cancelled")


@router.get("/{task_id}/progress", response_model=DataResponse[Optional[dict]])
def task_progress(task_id: str, _: Principal = Depends(get_current_user)):
    """In-memory read — safe to poll from the operator console."""
    return DataResponse(data=task_engine.progress(task_id))


# --------------------------------------------------------------------------
# Pick & drop
# --------------------------------------------------------------------------
@router.post("/pickdrop/start", response_model=DataResponse[dict], status_code=201)
async def start_pickdrop(
    body: PickDropStart,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_operator),
):
    task, progress = await start_pick_drop(
        db,
        robot_id=body.robot_id,
        pickup_location_id=body.pickup_location_id,
        drop_location_id=body.drop_location_id,
        repeats=body.repeats,
        created_by=user.username,
    )
    return DataResponse(data={"task": TaskOut.from_document(task), "progress": progress})


@router.post("/pickdrop/stop", response_model=StatusResponse)
async def stop_pickdrop(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    task_id = task_engine.running_task_id(body.robot_id)
    if task_id is None:
        return StatusResponse(message=f"No task running for {body.robot_id}")
    await task_engine.cancel_task(db, task_id)
    return StatusResponse(message=f"Task {task_id} cancelled")


@router.get("/pickdrop/{robot_id}/status", response_model=DataResponse[Optional[dict]])
def pickdrop_status(robot_id: str, _: Principal = Depends(get_current_user)):
    return DataResponse(data=task_engine.robot_progress(robot_id))


# --------------------------------------------------------------------------
# Pending requests (unassigned work)
# --------------------------------------------------------------------------
@router.post("/requests", response_model=DataResponse[TaskRequestOut], status_code=201)
async def create_request(
    body: TaskRequestCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_operator),
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
