"""Task, pick-drop and pending-request endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user
from app.core.exceptions import NotFoundError
from app.db.models import TaskStatusEnum
from app.db.repositories import tasks as task_repo
from app.db.session import get_db
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.robot import RobotIdBody
from app.schemas.task import (
    PendingRequestCreate,
    PendingRequestOut,
    PickDropStart,
    TaskCreate,
    TaskHistoryOut,
    TaskOut,
    TaskUpdate,
)
from app.services.task_service import task_runner

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=DataResponse[List[TaskOut]])
def list_tasks(
    status: Optional[TaskStatusEnum] = None,
    robot_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = task_repo.list_tasks(db, status=status, robot_id=robot_id, limit=limit, offset=offset)
    return DataResponse(data=[TaskOut.model_validate(row) for row in rows])


@router.post("", response_model=DataResponse[TaskOut], status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    task = task_repo.create_task(
        db,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        robot_id=body.robot_id,
        task_type=body.type,
        repeats=body.repeats,
    )
    return DataResponse(data=TaskOut.model_validate(task))


@router.get("/{task_id}", response_model=DataResponse[TaskOut])
def get_task(task_id: str, db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    task = task_repo.get_task(db, task_id)
    if task is None:
        raise NotFoundError(f"Task '{task_id}' not found")
    return DataResponse(data=TaskOut.model_validate(task))


@router.patch("/{task_id}", response_model=DataResponse[TaskOut])
def update_task(task_id: str, body: TaskUpdate, db: Session = Depends(get_db),
                _: Principal = Depends(get_current_user)):
    task = task_repo.update_task_status(db, task_id, body.status, message=body.message)
    if task is None:
        raise NotFoundError(f"Task '{task_id}' not found")
    return DataResponse(data=TaskOut.model_validate(task))


@router.get("/{task_id}/history", response_model=DataResponse[List[TaskHistoryOut]])
def task_history(task_id: str, db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    rows = task_repo.list_task_history(db, task_id)
    return DataResponse(data=[TaskHistoryOut.model_validate(row) for row in rows])


# --------------------------------------------------------------------------
# Pick & drop execution
# --------------------------------------------------------------------------
@router.post("/pickdrop/start", response_model=DataResponse[dict])
def start_pickdrop(body: PickDropStart, db: Session = Depends(get_db),
                   _: Principal = Depends(get_current_user)):
    data = task_runner.start_pickdrop(
        db, body.robot_id, body.pickup_location_id, body.drop_location_id, body.repeats
    )
    return DataResponse(data=data)


@router.post("/pickdrop/stop", response_model=StatusResponse)
def stop_pickdrop(body: RobotIdBody, db: Session = Depends(get_db),
                  _: Principal = Depends(get_current_user)):
    stopped = task_runner.stop(db, body.robot_id)
    return StatusResponse(message="Task stopped" if stopped else "No running task for this robot")


@router.get("/pickdrop/{robot_id}/status", response_model=DataResponse[Optional[dict]])
def pickdrop_status(robot_id: str, _: Principal = Depends(get_current_user)):
    return DataResponse(data=task_runner.status(robot_id))


# --------------------------------------------------------------------------
# Pending requests (unassigned work)
# --------------------------------------------------------------------------
@router.post("/requests", response_model=DataResponse[PendingRequestOut], status_code=201)
def create_request(body: PendingRequestCreate, db: Session = Depends(get_db),
                   _: Principal = Depends(get_current_user)):
    request = task_repo.create_pending_request(
        db,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        robot_type=body.robot_type,
        priority=body.priority,
        scheduled_for=body.scheduled_for,
    )
    return DataResponse(data=PendingRequestOut.model_validate(request))


@router.get("/requests/unassigned", response_model=DataResponse[List[PendingRequestOut]])
def unassigned_requests(db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    rows = task_repo.list_unassigned_requests(db)
    return DataResponse(data=[PendingRequestOut.model_validate(row) for row in rows])
