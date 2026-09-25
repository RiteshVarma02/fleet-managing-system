"""Task execution engine and the unassigned-request scheduler.

Design notes (server load):
* One asyncio task per *running* task — no thread per robot, no busy waiting.
  Nav progress is read from the controller's in-memory state, so a running task
  costs zero database reads while it drives.
* Mongo is written only on state transitions (started / leg reached / repeat
  completed / finished), never per poll tick.
* One scheduler loop for the whole fleet assigns pending requests to idle
  robots, so operators can queue work without picking a robot.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.db.documents import TaskStatus
from app.db.mongo import get_database
from app.db.repositories import locations_repo, pending_requests_repo, robots_repo, tasks_repo
from app.ros.capabilities.navigation import (
    NAV_SUCCEEDED,
    TERMINAL_NAV_STATES,
)
from app.services import robot_service

logger = get_logger(__name__)

SCHEDULER_INTERVAL_SECONDS = 2.0


class _CancelledByOperator(Exception):
    pass


class _TaskPaused(Exception):
    """Raised inside a leg when the operator pauses the task mid-navigation."""


class TaskEngine:
    def __init__(self) -> None:
        self._running: Dict[str, asyncio.Task] = {}
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._scheduler: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(settings.task_max_concurrent)
        # Pause support: the flag is checked inside the nav poll loop, the
        # event blocks `_run` until the operator resumes (or cancels).
        self._pause_flags: Dict[str, bool] = {}
        self._resume_events: Dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._scheduler = asyncio.create_task(self._scheduler_loop(), name="task-scheduler")
        # Any task left "running" by a crash is stale: this process owns none.
        db = get_database()
        for task in await tasks_repo.list_active(db):
            task_id = str(task.get("id"))
            await tasks_repo.set_status(
                db, task_id, TaskStatus.pending, message="Requeued after server restart"
            )
        logger.info("Task engine started")

    async def stop(self) -> None:
        for task in (self._scheduler, *self._running.values()):
            if task is not None:
                task.cancel()
        for task in list(self._running.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._scheduler is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler
        self._running.clear()
        self._scheduler = None
        logger.info("Task engine stopped")

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def is_running(self, task_id: str) -> bool:
        task = self._running.get(task_id)
        return task is not None and not task.done()

    def running_task_id(self, robot_id: str) -> Optional[str]:
        for task_id, progress in self._progress.items():
            if progress.get("robot_id") == robot_id and self.is_running(task_id):
                return task_id
        return None

    def paused_task_id(self, robot_id: str) -> Optional[str]:
        for task_id, progress in self._progress.items():
            if (
                progress.get("robot_id") == robot_id
                and progress.get("status") == TaskStatus.paused.value
            ):
                return task_id
        return None

    def progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        return dict(self._progress[task_id]) if task_id in self._progress else None

    def robot_progress(self, robot_id: str) -> Optional[Dict[str, Any]]:
        task_id = self.running_task_id(robot_id)
        return self.progress(task_id) if task_id else None

    async def start_task(self, db, task_id: str) -> Dict[str, Any]:
        """Validate everything up front so failures are HTTP errors, not silent."""
        task = await tasks_repo.get(db, task_id)
        if task is None:
            raise NotFoundError(f"Task '{task_id}' not found")
        if self.is_running(task_id):
            raise ConflictError("Task is already running", code="task_already_running")

        robot_id = str(task.get("robot_id") or "")
        if not robot_id:
            raise ValidationError("Task has no robot assigned")
        if self.running_task_id(robot_id):
            raise ConflictError(
                f"Robot '{robot_id}' is already executing a task", code="robot_busy"
            )
        robot_service.require_controller(robot_id, "navigation")
        await self._resolve_legs(db, task)

        task = await tasks_repo.set_status(
            db, task_id, TaskStatus.running, message="Execution started"
        )
        await robots_repo.upsert(db, robot_id, active_task_id=task_id)
        self._progress[task_id] = {
            "task_id": task_id,
            "robot_id": robot_id,
            "leg": None,
            "completed_repeats": 0,
            "repeats": int(task.get("repeats") or 1),
            "status": TaskStatus.running.value,
            "message": "Execution started",
        }
        self._pause_flags.pop(task_id, None)
        self._resume_events[task_id] = asyncio.Event()
        self._running[task_id] = asyncio.create_task(
            self._run(task_id, robot_id), name=f"task-{task_id}"
        )
        return task or {}

    async def cancel_task(self, db, task_id: str) -> None:
        self._pause_flags.pop(task_id, None)
        event = self._resume_events.get(task_id)
        if event is not None:
            event.set()  # unblock a paused `_run` so cancellation is immediate
        task = self._running.pop(task_id, None)
        progress = self._progress.get(task_id) or {}
        robot_id = str(progress.get("robot_id") or "")
        if robot_id:
            with contextlib.suppress(Exception):
                robot_service.require_controller(robot_id).cancel_nav_goal()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._finish(db, task_id, robot_id, TaskStatus.cancelled, "Cancelled by operator")

    async def pause_task(self, db, task_id: str) -> Dict[str, Any]:
        """Stop the robot mid-leg (Nav2 action cancelled) but keep the task.

        The engine re-issues the same goal on `resume_task`, so no mission
        progress is lost — Nav2 has no native pause for NavigateToPose.
        """
        if not self.is_running(task_id):
            raise ConflictError("Task is not running", code="task_not_running")
        if self._pause_flags.get(task_id):
            raise ConflictError("Task is already paused", code="task_already_paused")

        progress = self._progress.get(task_id) or {}
        robot_id = str(progress.get("robot_id") or "")
        # Flag first: the poll loop must see paused before it can observe the
        # transient CANCELLED state that pausing produces.
        self._pause_flags[task_id] = True
        controller = robot_service.require_controller(robot_id, "navigation")
        ok, detail = controller.pause_nav_goal()
        if not ok:
            self._pause_flags.pop(task_id, None)
            raise ValidationError(detail)

        # Reflect the paused state IMMEDIATELY. The poll loop would only reach
        # _wait_while_paused on its next tick (up to 1s later); without this,
        # a resume in that window fails with "no paused task".
        current = self._progress.get(task_id)
        if current is not None:
            current["status"] = TaskStatus.paused.value
            current["message"] = "Paused by operator"
        await tasks_repo.set_status(db, task_id, TaskStatus.paused, message="Paused by operator")
        return dict(current or {})

    async def resume_task(self, db, task_id: str) -> Dict[str, Any]:
        """Re-issue the interrupted goal and continue the remaining legs."""
        was_paused = self._pause_flags.pop(task_id, False)
        if not was_paused:
            if self.is_running(task_id):
                raise ConflictError("Task is not paused", code="task_not_paused")
            raise ConflictError("Task is not running", code="task_not_running")

        progress = self._progress.get(task_id) or {}
        robot_id = str(progress.get("robot_id") or "")

        await tasks_repo.set_status(db, task_id, TaskStatus.running, message="Resumed")
        current = self._progress.get(task_id)
        if current is not None:
            current["status"] = TaskStatus.running.value
            current["message"] = f"Resuming {current.get('leg') or 'current leg'}"

        # Unblocks `_wait_while_paused`; `_run` then retries the same leg,
        # which publishes a fresh goal_request to the robot.
        event = self._resume_events.get(task_id)
        if event is not None:
            event.set()
        return dict(self._progress.get(task_id) or {})

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    async def _resolve_legs(self, db, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        legs: List[Dict[str, Any]] = []
        for field in ("from_location_id", "to_location_id"):
            location_id = task.get(field)
            if not location_id:
                continue
            location = await locations_repo.get(db, str(location_id))
            if location is None:
                raise ValidationError(f"Location '{location_id}' referenced by the task is missing")
            legs.append(location)
        if not legs:
            raise ValidationError("Task must reference at least one location")
        return legs

    async def _run(self, task_id: str, robot_id: str) -> None:
        db = get_database()
        status = TaskStatus.completed
        message = "Task completed"
        try:
            async with self._semaphore:
                task = await tasks_repo.get(db, task_id)
                if task is None:
                    return
                legs = await self._resolve_legs(db, task)
                repeats = max(1, int(task.get("repeats") or 1))
                repeats = min(repeats, settings.max_task_repeats)

                for cycle in range(repeats):
                    leg_index = 0
                    while leg_index < len(legs):
                        try:
                            await self._drive_to(db, task_id, robot_id, legs[leg_index])
                        except _TaskPaused:
                            # Robot is stopped (Nav2 goal cancelled). Block here
                            # until resume/cancel; then retry the same leg.
                            await self._wait_while_paused(db, task_id)
                            continue
                        leg_index += 1
                    await tasks_repo.increment_repeats(db, task_id)
                    self._progress.setdefault(task_id, {})["completed_repeats"] = cycle + 1
                    self._progress.setdefault(task_id, {})["message"] = (
                        f"Cycle {cycle + 1}/{repeats} done"
                    )
                    await tasks_repo.append_history(
                        db, task_id, TaskStatus.running, f"Cycle {cycle + 1}/{repeats} done"
                    )
        except asyncio.CancelledError:
            status, message = TaskStatus.cancelled, "Cancelled"
            raise
        except _CancelledByOperator:
            status, message = TaskStatus.cancelled, "Cancelled by operator"
        except (ValidationError, NotFoundError) as exc:
            status, message = TaskStatus.failed, str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Task %s failed", task_id)
            status, message = TaskStatus.failed, f"Unexpected error: {type(exc).__name__}: {exc}"
        finally:
            self._running.pop(task_id, None)
            with contextlib.suppress(Exception):
                await self._finish(db, task_id, robot_id, status, message)

    async def _wait_while_paused(self, db, task_id: str) -> None:
        """Persist the paused state and block until `resume_task` fires."""
        await tasks_repo.set_status(db, task_id, TaskStatus.paused, message="Paused by operator")
        progress = self._progress.get(task_id)
        if progress is not None:
            progress["status"] = TaskStatus.paused.value
            progress["message"] = "Paused by operator"
        event = self._resume_events.get(task_id)
        if event is not None:
            # Cancel during pause raises CancelledError here, which `_run`
            # already maps to a cancelled finish.
            await event.wait()

    async def _drive_to(self, db, task_id: str, robot_id: str, location: Dict[str, Any]) -> None:
        controller = robot_service.require_controller(robot_id, "navigation")
        # Entry check closes the between-legs race: without it a pause landing
        # just after the previous leg returned would still let the next goal
        # publish before the first poll tick noticed the flag.
        if self._pause_flags.get(task_id):
            raise _TaskPaused()
        ok, detail = controller.send_nav2_goal(
            float(location.get("x", 0.0)),
            float(location.get("y", 0.0)),
            float(location.get("theta", 0.0)),
        )
        if not ok:
            raise ValidationError(detail)
        # Only terminal states stamped with THIS goal's epoch may end the wait;
        # anything older is a delayed message from the previous leg.
        # Read epoch from controller's internal state after goal is sent.
        nav_status = controller.get_nav_status()
        epoch = int(nav_status.get("epoch") or 0)
        # Defensive: if epoch is 0 (not set yet), wait one poll cycle for it to be set
        poll = max(0.2, settings.nav_poll_interval_seconds)
        if epoch == 0:
            await asyncio.sleep(poll)
            nav_status = controller.get_nav_status()
            epoch = int(nav_status.get("epoch") or 0)

        self._progress.setdefault(task_id, {})["leg"] = location.get("name")
        self._progress.setdefault(task_id, {})["status"] = TaskStatus.running.value
        self._progress.setdefault(task_id, {})["message"] = (
            f"Navigating to {location.get('name')}"
        )
        await tasks_repo.append_history(
            db, task_id, TaskStatus.running, f"Navigating to {location.get('name')}"
        )

        waited = 0.0
        while waited < settings.nav_goal_timeout_seconds:
            await asyncio.sleep(poll)
            waited += poll
            if self._pause_flags.get(task_id):
                raise _TaskPaused()
            nav = controller.get_nav_status()
            if nav.get("epoch") != epoch:
                continue  # stale update from a previous leg — ignore
            if ros_state := nav.get("status"):
                if ros_state in TERMINAL_NAV_STATES:
                    if ros_state == NAV_SUCCEEDED:
                        return
                    if ros_state == "cancelled":
                        raise _CancelledByOperator()
                    raise ValidationError(f"Navigation to {location.get('name')} {ros_state}")
        controller.cancel_nav_goal()
        raise ValidationError(f"Navigation to {location.get('name')} timed out")

    async def _finish(
        self, db, task_id: str, robot_id: str, status: TaskStatus, message: str
    ) -> None:
        self._progress.pop(task_id, None)
        self._pause_flags.pop(task_id, None)
        self._resume_events.pop(task_id, None)
        current = await tasks_repo.get(db, task_id)
        if current is not None and str(current.get("status")) not in {
            TaskStatus.completed.value,
            TaskStatus.failed.value,
            TaskStatus.cancelled.value,
        }:
            await tasks_repo.set_status(db, task_id, status, message=message)
        if robot_id:
            await robots_repo.clear_active_task(db, robot_id)

    # ------------------------------------------------------------------
    # scheduler
    # ------------------------------------------------------------------
    async def _scheduler_loop(self) -> None:
        while True:
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
            try:
                await self._assign_once()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Scheduler pass failed: %s", exc)

    async def _assign_once(self) -> None:
        db = get_database()
        request = await pending_requests_repo.claim_oldest(db)
        if request is None:
            return

        robot_type = request.get("robot_type")
        candidates = await robot_service.idle_robot_ids(db, robot_type=robot_type)
        if not candidates:
            await pending_requests_repo.release(db, str(request["id"]))
            return

        robot_id = candidates[0]
        task = await tasks_repo.create(
            db,
            task_type=str(request.get("task_type") or "pick_drop"),
            robot_id=robot_id,
            from_location_id=request.get("from_location_id"),
            to_location_id=request.get("to_location_id"),
            repeats=int(request.get("repeats") or 1),
            created_by=str(request.get("created_by") or "scheduler"),
        )
        task_id = str(task["id"])
        await pending_requests_repo.mark_assigned(db, str(request["id"]), task_id, robot_id)
        try:
            await self.start_task(db, task_id)
            logger.info("Request %s assigned to %s as task %s", request["id"], robot_id, task_id)
        except Exception as exc:
            logger.warning("Auto-start of task %s failed: %s", task_id, exc)
            await tasks_repo.set_status(db, task_id, TaskStatus.pending, message=str(exc))


task_engine = TaskEngine()


async def start_pick_drop(
    db, robot_id: str, pickup_location_id: str, drop_location_id: str, repeats: int, created_by: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a pick-and-drop task and immediately begin executing it."""
    task = await tasks_repo.create(
        db,
        task_type="pick_drop",
        robot_id=robot_id,
        from_location_id=pickup_location_id,
        to_location_id=drop_location_id,
        repeats=repeats,
        created_by=created_by,
    )
    task_id = str(task["id"])
    started = await task_engine.start_task(db, task_id)
    return started or task, task_engine.progress(task_id) or {}
