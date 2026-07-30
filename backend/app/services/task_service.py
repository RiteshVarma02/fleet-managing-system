"""Pick-and-drop task execution.

A task runs on a dedicated worker thread (navigation is a long, blocking,
event-driven wait, so it must never occupy the event loop). Each robot may
have at most one running task; the registry is guarded by a lock and the
thread is always removed in `finally`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging_config import get_logger
from app.db.models import TaskStatusEnum
from app.db.repositories import locations as location_repo
from app.db.repositories import robots as robot_repo
from app.db.repositories import tasks as task_repo
from app.db.session import session_scope
from app.ros.robot_controller import NAV_SUCCEEDED
from app.services import robot_service

logger = get_logger(__name__)


@dataclass
class Waypoint:
    id: str
    name: str
    x: float
    y: float
    theta: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "x": self.x, "y": self.y, "theta": self.theta}


@dataclass
class RunningTask:
    task_id: str
    robot_id: str
    pickup: Waypoint
    drop: Waypoint
    repeats: int
    stop_event: threading.Event
    thread: Optional[threading.Thread] = None
    state: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "robot_id": self.robot_id,
            "pickup": self.pickup.as_dict(),
            "drop": self.drop.as_dict(),
            "repeats": self.repeats,
            "alive": bool(self.thread and self.thread.is_alive()),
            **self.state,
        }


class TaskRunner:
    """Registry + executor of the per-robot pick/drop threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, RunningTask] = {}

    # ---------------- public API ----------------
    def start_pickdrop(self, db: Session, robot_id: str, pickup_id: str, drop_id: str, repeats: int) -> Dict[str, Any]:
        if repeats < 1 or repeats > settings.max_task_repeats:
            raise ConflictError(f"repeats must be between 1 and {settings.max_task_repeats}")

        pickup = self._load_waypoint(db, pickup_id, "pickup")
        drop = self._load_waypoint(db, drop_id, "drop")

        if robot_repo.get_robot(db, robot_id) is None:
            raise NotFoundError(f"Robot '{robot_id}' not found")
        robot_service.require_controller(robot_id)

        with self._lock:
            existing = self._tasks.get(robot_id)
            if existing and existing.thread and existing.thread.is_alive():
                raise ConflictError(f"Robot '{robot_id}' already has a running task")

            task = task_repo.create_task(
                db,
                from_location_id=pickup_id,
                to_location_id=drop_id,
                robot_id=robot_id,
                task_type="pick_drop",
                repeats=repeats,
            )
            task_repo.update_task_status(db, task.id, TaskStatusEnum.running, robot_id=robot_id)

            running = RunningTask(
                task_id=task.id,
                robot_id=robot_id,
                pickup=pickup,
                drop=drop,
                repeats=repeats,
                stop_event=threading.Event(),
                state={"state": "starting", "updated_at": time.time()},
            )
            running.thread = threading.Thread(
                target=self._run, args=(running,), name=f"task-{robot_id}", daemon=True
            )
            self._tasks[robot_id] = running
            running.thread.start()

        return running.snapshot()

    def stop(self, db: Session, robot_id: str) -> bool:
        with self._lock:
            running = self._tasks.get(robot_id)
        if running is None:
            return False

        running.stop_event.set()
        controller = robot_service.ros_manager.get_controller(robot_id)
        if controller is not None:
            controller.cancel_navigation()

        for task in task_repo.list_running_tasks(db, robot_id):
            task_repo.update_task_status(
                db, task.id, TaskStatusEnum.cancelled, message="Stopped by operator"
            )

        thread = running.thread
        if thread and thread.is_alive():
            thread.join(timeout=5.0)
        self._discard(robot_id)
        return True

    def status(self, robot_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            running = self._tasks.get(robot_id)
        return running.snapshot() if running else None

    def stop_all(self) -> None:
        for robot_id in list(self._tasks):
            with self._lock:
                running = self._tasks.get(robot_id)
            if running:
                running.stop_event.set()

    # ---------------- internals ----------------
    def _load_waypoint(self, db: Session, location_id: str, label: str) -> Waypoint:
        location = location_repo.get_location(db, location_id)
        if location is None:
            raise NotFoundError(f"{label.capitalize()} location '{location_id}' not found")
        return Waypoint(
            id=location.id, name=location.name, x=location.x, y=location.y, theta=location.theta
        )

    def _discard(self, robot_id: str) -> None:
        with self._lock:
            self._tasks.pop(robot_id, None)

    def _set_state(self, running: RunningTask, state: str, **extra) -> None:
        with self._lock:
            running.state = {"state": state, "updated_at": time.time(), **extra}

    @staticmethod
    def _finish_in_db(task_id: str, status: TaskStatusEnum, message: Optional[str]) -> None:
        try:
            with session_scope() as db:
                task_repo.update_task_status(db, task_id, status, message=message)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Could not update task %s to %s: %s", task_id, status, exc)

    def _navigate(self, running: RunningTask, controller: Any, waypoint: Waypoint, phase: str,
                  cycle: int) -> Optional[str]:
        """Send a goal and block until it resolves. Returns an error message or None."""
        ok, message = controller.send_goal(waypoint.x, waypoint.y, waypoint.theta)
        if not ok:
            return f"{phase} goal rejected: {message}"

        deadline = time.monotonic() + settings.nav_goal_timeout_seconds
        while not controller.wait_for_nav_done(timeout=settings.nav_poll_interval_seconds):
            if running.stop_event.is_set():
                return None  # caller handles the stop
            if time.monotonic() > deadline:
                nav = controller.get_nav_status()
                return f"{phase} navigation timed out (status={nav.get('status')})"

        nav = controller.get_nav_status()
        if nav.get("status") != NAV_SUCCEEDED:
            return f"{phase} navigation failed (status={nav.get('status')})"
        return None

    def _run(self, running: RunningTask) -> None:
        robot_id = running.robot_id
        try:
            controller = robot_service.ros_manager.get_controller(robot_id)
            if controller is None:
                self._set_state(running, "error", message="Robot not connected")
                self._finish_in_db(running.task_id, TaskStatusEnum.failed, "Robot not connected")
                return

            for cycle in range(1, running.repeats + 1):
                for phase, waypoint in (("pickup", running.pickup), ("drop", running.drop)):
                    if running.stop_event.is_set():
                        self._set_state(running, "stopped", cycle=cycle, message="Stopped by operator")
                        self._finish_in_db(running.task_id, TaskStatusEnum.cancelled, "Stopped by operator")
                        return

                    self._set_state(running, "running", step=f"going_to_{phase}", cycle=cycle)
                    error = self._navigate(running, controller, waypoint, phase, cycle)

                    if running.stop_event.is_set():
                        self._set_state(running, "stopped", cycle=cycle, message="Stopped by operator")
                        self._finish_in_db(running.task_id, TaskStatusEnum.cancelled, "Stopped by operator")
                        return
                    if error:
                        logger.warning("[%s] %s", robot_id, error)
                        self._set_state(running, "error", cycle=cycle, message=error)
                        self._finish_in_db(running.task_id, TaskStatusEnum.failed, error)
                        return

                    logger.info("[%s] cycle %d/%d %s reached", robot_id, cycle, running.repeats, phase)

            self._set_state(running, "completed", cycle=running.repeats, message="Task completed")
            self._finish_in_db(running.task_id, TaskStatusEnum.done, "Task completed successfully")

        except Exception as exc:  # pragma: no cover - defensive
            message = f"Unexpected task error: {exc}"
            logger.exception("[%s] %s", robot_id, message)
            self._set_state(running, "error", message=message)
            self._finish_in_db(running.task_id, TaskStatusEnum.failed, message)
        finally:
            self._discard(robot_id)
            logger.info("[%s] task worker finished", robot_id)


task_runner = TaskRunner()
