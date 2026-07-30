"""Data-access layer for tasks, task history and pending requests."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import PendingRequest, Task, TaskHistory, TaskStatusEnum

_TERMINAL = {TaskStatusEnum.done, TaskStatusEnum.failed, TaskStatusEnum.cancelled}


def create_task(
    db: Session,
    *,
    from_location_id: Optional[str] = None,
    to_location_id: Optional[str] = None,
    robot_id: Optional[str] = None,
    task_type: str = "pick_drop",
    repeats: int = 1,
) -> Task:
    task = Task(
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        robot_id=robot_id,
        type=task_type,
        repeats=repeats,
        status=TaskStatusEnum.pending,
    )
    db.add(task)
    db.flush()
    db.add(TaskHistory(task_id=task.id, robot_id=robot_id, event_type="created", message="Task created"))
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: str) -> Optional[Task]:
    return db.get(Task, task_id)


def list_tasks(
    db: Session,
    *,
    robot_id: Optional[str] = None,
    status: Optional[TaskStatusEnum] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Task]:
    stmt = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
    if robot_id:
        stmt = stmt.where(Task.robot_id == robot_id)
    if status:
        stmt = stmt.where(Task.status == status)
    return list(db.execute(stmt).scalars())


def list_running_tasks(db: Session, robot_id: str) -> List[Task]:
    stmt = select(Task).where(Task.robot_id == robot_id, Task.status == TaskStatusEnum.running)
    return list(db.execute(stmt).scalars())


def count_active_tasks(db: Session, robot_id: str) -> int:
    stmt = select(Task).where(
        Task.robot_id == robot_id,
        Task.status.in_([TaskStatusEnum.pending, TaskStatusEnum.running]),
    )
    return len(list(db.execute(stmt).scalars()))


def update_task_status(
    db: Session,
    task_id: str,
    status: TaskStatusEnum,
    *,
    message: Optional[str] = None,
    robot_id: Optional[str] = None,
) -> Optional[Task]:
    task = db.get(Task, task_id)
    if task is None:
        return None

    task.status = status
    if message:
        task.message = message
    if robot_id:
        task.robot_id = robot_id
    if status == TaskStatusEnum.running and task.started_at is None:
        task.started_at = utcnow()
    if status in _TERMINAL and task.finished_at is None:
        task.finished_at = utcnow()

    db.add(
        TaskHistory(
            task_id=task.id,
            robot_id=task.robot_id,
            event_type=f"status:{status.value}",
            message=message,
        )
    )
    db.commit()
    db.refresh(task)
    return task


def add_history(db: Session, task_id: str, event_type: str, message: Optional[str] = None,
                robot_id: Optional[str] = None) -> TaskHistory:
    entry = TaskHistory(task_id=task_id, robot_id=robot_id, event_type=event_type, message=message)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_task_history(db: Session, task_id: str) -> List[TaskHistory]:
    stmt = select(TaskHistory).where(TaskHistory.task_id == task_id).order_by(TaskHistory.timestamp)
    return list(db.execute(stmt).scalars())


# --------------------------------------------------------------------------
# Pending requests
# --------------------------------------------------------------------------
def create_pending_request(
    db: Session,
    *,
    from_location_id: Optional[str],
    to_location_id: Optional[str],
    robot_type: Optional[str],
    priority: int = 0,
    scheduled_for: Optional[datetime] = None,
) -> PendingRequest:
    request = PendingRequest(
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        robot_type=robot_type,
        priority=priority,
        scheduled_for=scheduled_for,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def list_unassigned_requests(db: Session) -> List[PendingRequest]:
    stmt = (
        select(PendingRequest)
        .where(PendingRequest.assigned_task_id.is_(None))
        .order_by(PendingRequest.priority.desc(), PendingRequest.created_at)
    )
    return list(db.execute(stmt).scalars())


def get_pending_request(db: Session, request_id: str) -> Optional[PendingRequest]:
    return db.get(PendingRequest, request_id)


def assign_request(db: Session, request: PendingRequest, task_id: str) -> PendingRequest:
    request.assigned_task_id = task_id
    db.commit()
    db.refresh(request)
    return request
