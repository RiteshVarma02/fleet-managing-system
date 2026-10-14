"""Mission (task) and pending-request endpoints.

Execution is owned by `task_service.task_engine`: these routes only validate
input, persist intent and hand off. Progress reads come from the engine's
in-memory state, so polling a running task costs no database round trip.

Route ordering matters: all static paths (`/missions`, `/waypoint`, `/robot/*`,
`/requests/*`) are declared before the `/{task_id}` dynamic routes so they are
never swallowed by the parameterised patterns (Starlette resolves routes in
declaration order).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_operator
from app.core.exceptions import ConflictError, NotFoundError
from app.db.documents import TaskStatus
from app.db.repositories import pending_requests_repo, tasks_repo
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.task import (
    MissionStart,
    TaskCreate,
    TaskHistoryOut,
    TaskOut,
    TaskRequestCreate,
    TaskRequestOut,
    TaskUpdate,
    WaypointSend,
)
from app.services.task_service import (
    send_waypoint,
    start_mission,
    task_engine,
    validate_stops,
)

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
    """Create a mission without starting it."""
    await validate_stops(db, body.stops)
    task = await tasks_repo.create(
        db,
        task_type=body.type,
        robot_id=body.robot_id,
        stops=body.stops,
        repeats=body.repeats,
        mode=body.mode,
        created_by=user.username,
        payload=body.payload,
    )
    return DataResponse(data=TaskOut.from_document(task))


# --------------------------------------------------------------------------
# Static paths MUST come before the /{task_id} dynamic routes.
# --------------------------------------------------------------------------
@router.post("/missions", response_model=DataResponse[dict], status_code=201)
async def start_mission_endpoint(
    body: MissionStart,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_operator),
):
    """Plus-button mission: ordered stops x repeats, continuous or move-on-click."""
    result = await start_mission(
        db, body.robot_id, body.stops, body.repeats, body.mode, user.username
    )
    return DataResponse(
        data={"task": TaskOut.from_document(result["task"]), "progress": result["progress"]}
    )


@router.post("/waypoint", response_model=DataResponse[dict], status_code=201)
async def send_waypoint_endpoint(
    body: WaypointSend,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_operator),
):
    """Text box: send one robot to one waypoint by name."""
    result = await send_waypoint(db, body.robot_id, body.waypoint, user.username)
    return DataResponse(
        data={"task": TaskOut.from_document(result["task"]), "progress": result["progress"]}
    )


@router.post("/robot/{robot_id}/{action}", response_model=DataResponse[Optional[dict]])
async def robot_control(
    robot_id: str,
    action: Literal["pause", "resume", "cancel"],
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    """The ONE set of mission controls, addressed by robot.

    * pause   halt the robot mid-leg, keep the mission
    * resume  continue: after a pause or E-stop, OR "go" for a mission that is
              waiting for approval (move-on-click). Refused while an E-stop is on.
    * cancel  abort the mission
    """
    task_id = task_engine.running_task_id(robot_id)
    if task_id is None:
        raise ConflictError(f"{robot_id} has no active mission", code="task_not_running")
    if action == "cancel":
        await task_engine.cancel_task(db, task_id)
        return DataResponse(data=None)
    if action == "pause":
        return DataResponse(data=await task_engine.pause_task(db, task_id))
    if (task_engine.progress(task_id) or {}).get("status") == TaskStatus.awaiting_approval.value:
        return DataResponse(data=await task_engine.approve_task(db, task_id))
    return DataResponse(data=await task_engine.resume_task(db, task_id))


@router.get("/robot/{robot_id}/progress", response_model=DataResponse[Optional[dict]])
def robot_progress(robot_id: str, _: Principal = Depends(get_current_user)):
    """Live progress of whatever the robot is doing (None when idle)."""
    task_id = task_engine.running_task_id(robot_id)
    return DataResponse(data=task_engine.progress(task_id) if task_id else None)


# --------------------------------------------------------------------------
# Pending requests (unassigned work)
# --------------------------------------------------------------------------
@router.post("/requests", response_model=DataResponse[TaskRequestOut], status_code=201)
async def create_request(
    body: TaskRequestCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(require_operator),
):
    """Queue unassigned work; `scheduled_at` defers it until that instant."""
    await validate_stops(db, body.stops)
    request = await pending_requests_repo.create(
        db,
        task_type=body.type,
        stops=body.stops,
        robot_type=body.robot_type,
        repeats=body.repeats,
        mode=body.mode,
        created_by=user.username,
        scheduled_at=body.scheduled_at,
    )
    return DataResponse(data=TaskRequestOut.from_document(request))


@router.get("/requests/unassigned", response_model=DataResponse[List[TaskRequestOut]])
async def unassigned_requests(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await pending_requests_repo.list_requests(db, status=pending_requests_repo.PENDING)
    return DataResponse(data=[TaskRequestOut.from_document(row) for row in rows])


@router.post("/requests/{request_id}/cancel", response_model=StatusResponse)
async def cancel_request(
    request_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    """Remove a queued (possibly scheduled) request before it is assigned."""
    if not await pending_requests_repo.cancel(db, request_id):
        raise NotFoundError(f"Pending request '{request_id}' not found")
    return StatusResponse(message=f"Request {request_id} cancelled")


# --------------------------------------------------------------------------
# Task detail
# --------------------------------------------------------------------------
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


@router.get("/{task_id}/progress", response_model=DataResponse[Optional[dict]])
def task_progress(task_id: str, _: Principal = Depends(get_current_user)):
    """In-memory read — safe to poll from the operator console."""
    return DataResponse(data=task_engine.progress(task_id))