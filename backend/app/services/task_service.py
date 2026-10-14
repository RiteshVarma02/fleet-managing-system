"""Task execution engine and the unassigned-request scheduler.

Design notes (server load):
* One asyncio task per *running* task — no thread per robot, no busy waiting.
  Nav progress is read from the controller's in-memory state, so a running task
  costs zero database reads while it drives.
* Mongo is written only on state transitions (started / leg reached / repeat
  completed / finished), never per poll tick.
* One scheduler loop for the whole fleet assigns pending requests to idle
  robots, so operators can queue work without picking a robot.

A mission is an ordered list of waypoint names repeated N times. In "step"
mode ("move on click") the task blocks in `awaiting_approval` after every
arrival (except the very last stop) until an operator calls `approve_task`.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.db.documents import TaskStatus
from app.db.mongo import get_database
from app.db.repositories import pending_requests_repo, robots_repo, tasks_repo
from app.ros.capabilities.waypoint_nav import (
    NAV_CANCELLED,
    NAV_PAUSED,
    NAV_SUCCEEDED,
    TERMINAL_NAV_STATES,
)
from app.services import fleet_file_service, robot_service

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
        # "Move on click": blocks `_run` after an arrival until approved.
        self._approve_events: Dict[str, asyncio.Event] = {}

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
        controller = robot_service.require_controller(robot_id, "waypoint_nav")
        hold = _safety_hold(controller)
        if hold:
            raise ConflictError(f"Robot '{robot_id}' cannot move: {hold}", code="safety_hold")
        stops = await self._stops_of(db, task)

        task = await tasks_repo.set_status(
            db, task_id, TaskStatus.running, message="Execution started"
        )
        await robots_repo.upsert(db, robot_id, active_task_id=task_id)
        self._progress[task_id] = {
            "task_id": task_id,
            "robot_id": robot_id,
            "leg": None,
            "stops": stops,
            "mode": str(task.get("mode") or "continuous"),
            "cycle": 1,
            "stop_index": 0,
            "next_stop": stops[0],
            "completed_repeats": 0,
            "repeats": int(task.get("repeats") or 1),
            "status": TaskStatus.running.value,
            "message": "Execution started",
        }
        self._pause_flags.pop(task_id, None)
        self._resume_events[task_id] = asyncio.Event()
        self._approve_events[task_id] = asyncio.Event()
        self._running[task_id] = asyncio.create_task(
            self._run(task_id, robot_id), name=f"task-{task_id}"
        )
        return task or {}

    async def cancel_task(self, db, task_id: str) -> None:
        self._pause_flags.pop(task_id, None)
        for events in (self._resume_events, self._approve_events):
            event = events.get(task_id)
            if event is not None:
                event.set()  # unblock a paused/waiting `_run` so cancellation is immediate
        task = self._running.pop(task_id, None)
        progress = self._progress.get(task_id) or {}
        robot_id = str(progress.get("robot_id") or "")
        if robot_id:
            with contextlib.suppress(Exception):
                robot_service.require_controller(robot_id).abort_waypoint("Cancelled by operator")
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._finish(db, task_id, robot_id, TaskStatus.cancelled, "Cancelled by operator")

    async def pause_task(
        self, db, task_id: str, reason: str = "Paused by operator"
    ) -> Dict[str, Any]:
        """Halt the robot mid-leg (empty route = stop in place) but keep the task.

        The engine re-sends the same waypoint on `resume_task`, so no mission
        progress is lost.
        """
        if not self.is_running(task_id):
            raise ConflictError("Task is not running", code="task_not_running")
        if self._pause_flags.get(task_id):
            raise ConflictError("Task is already paused", code="task_already_paused")
        if (self._progress.get(task_id) or {}).get("status") == TaskStatus.awaiting_approval.value:
            raise ConflictError(
                "The robot is standing still, waiting for approval; there is nothing to pause",
                code="awaiting_approval",
            )

        progress = self._progress.get(task_id) or {}
        robot_id = str(progress.get("robot_id") or "")
        # Flag first: the poll loop must see paused before it can observe the
        # transient CANCELLED state that pausing produces.
        self._pause_flags[task_id] = True
        controller = robot_service.require_controller(robot_id, "waypoint_nav")
        ok, detail = controller.pause_waypoint(reason)
        if not ok:
            self._pause_flags.pop(task_id, None)
            raise ValidationError(detail)

        # Reflect the paused state IMMEDIATELY. The poll loop would only reach
        # _wait_while_paused on its next tick (up to 1s later); without this,
        # a resume in that window fails with "no paused task".
        current = self._progress.get(task_id)
        if current is not None:
            current["status"] = TaskStatus.paused.value
            current["message"] = reason
        await tasks_repo.set_status(db, task_id, TaskStatus.paused, message=reason)
        return dict(current or {})

    async def resume_task(self, db, task_id: str) -> Dict[str, Any]:
        """Operator presses Continue: re-send the interrupted leg and go on.

        Refused while an E-stop is still active — after a physical E-stop the
        robot only moves again once it is released AND an operator continues.
        """
        if self._pause_flags.get(task_id):
            progress = self._progress.get(task_id) or {}
            controller = robot_service.require_controller(
                str(progress.get("robot_id") or ""), "waypoint_nav"
            )
            hold = _safety_hold(controller)
            if hold:
                raise ConflictError(f"Cannot continue: {hold}", code="safety_hold")
        was_paused = self._pause_flags.pop(task_id, False)
        if not was_paused:
            if self.is_running(task_id):
                raise ConflictError("Task is not paused", code="task_not_paused")
            raise ConflictError("Task is not running", code="task_not_running")

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

    async def approve_task(self, db, task_id: str) -> Dict[str, Any]:
        """Operator presses "go": release a mission waiting in `step` mode."""
        progress = self._progress.get(task_id)
        if progress is None or not self.is_running(task_id):
            raise ConflictError("Task is not running", code="task_not_running")
        if progress.get("status") != TaskStatus.awaiting_approval.value:
            raise ConflictError("Task is not waiting for approval", code="task_not_awaiting")
        controller = robot_service.require_controller(str(progress.get("robot_id") or ""), "waypoint_nav")
        hold = _safety_hold(controller)
        if hold:
            raise ConflictError(f"Cannot move: {hold}", code="safety_hold")
        event = self._approve_events.get(task_id)
        if event is not None:
            event.set()
        return dict(progress)

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    async def _stops_of(self, db, task: Dict[str, Any]) -> List[str]:
        """The mission's waypoint names, checked against the active graph."""
        stops = [str(s).strip() for s in (task.get("stops") or []) if str(s).strip()]
        if not stops:
            raise ValidationError("Mission has no stops")
        await validate_stops(db, stops)
        return stops

    async def _run(self, task_id: str, robot_id: str) -> None:
        db = get_database()
        status = TaskStatus.completed
        message = "Task completed"
        try:
            async with self._semaphore:
                task = await tasks_repo.get(db, task_id)
                if task is None:
                    return
                stops = await self._stops_of(db, task)
                mode = str(task.get("mode") or "continuous")
                repeats = max(1, int(task.get("repeats") or 1))
                repeats = min(repeats, settings.max_task_repeats)

                for cycle in range(repeats):
                    index = 0
                    while index < len(stops):
                        try:
                            await self._drive_to(db, task_id, robot_id, stops[index])
                        except _TaskPaused as paused:
                            # Robot is halted. Block here until resume/cancel;
                            # then retry the same stop.
                            await self._wait_while_paused(db, task_id, str(paused))
                            continue
                        await tasks_repo.set_cursor(db, task_id, cycle + 1, index)
                        last = cycle == repeats - 1 and index == len(stops) - 1
                        upcoming = stops[(index + 1) % len(stops)]
                        index += 1
                        progress = self._progress.setdefault(task_id, {})
                        progress.update(
                            cycle=cycle + 1 if index < len(stops) else min(cycle + 2, repeats),
                            stop_index=index % len(stops),
                            next_stop=None if last else upcoming,
                        )
                        if mode == "step" and not last:
                            await self._wait_for_approval(db, task_id, upcoming)
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

    async def _wait_while_paused(self, db, task_id: str, reason: str = "") -> None:
        """Persist the paused state and block until `resume_task` fires."""
        reason = reason or "Paused by operator"
        await tasks_repo.set_status(db, task_id, TaskStatus.paused, message=reason)
        progress = self._progress.get(task_id)
        if progress is not None:
            progress["status"] = TaskStatus.paused.value
            progress["message"] = reason
        event = self._resume_events.get(task_id)
        if event is not None:
            # Cancel during pause raises CancelledError here, which `_run`
            # already maps to a cancelled finish.
            await event.wait()

    async def _wait_for_approval(self, db, task_id: str, next_stop: str) -> None:
        """Move on click: stand still at the stop until `approve_task`."""
        event = self._approve_events.setdefault(task_id, asyncio.Event())
        event.clear()
        message = f"Waiting for approval to go to {next_stop}"
        progress = self._progress.get(task_id)
        if progress is not None:
            progress["status"] = TaskStatus.awaiting_approval.value
            progress["message"] = message
        await tasks_repo.set_status(db, task_id, TaskStatus.awaiting_approval, message=message)
        await event.wait()  # cancel_task sets the event and cancels `_run`
        if progress is not None:
            progress["status"] = TaskStatus.running.value
        await tasks_repo.set_status(db, task_id, TaskStatus.running, message=f"Approved: {next_stop}")

    async def _drive_to(self, db, task_id: str, robot_id: str, waypoint: str) -> None:
        """Drive one leg: publish the waypoint NAME, wait for a true arrival."""
        controller = robot_service.require_controller(robot_id, "waypoint_nav")
        # Entry check closes the between-legs race: a pause (or an E-stop)
        # landing just after the previous leg returned must stop the next goal.
        if self._pause_flags.get(task_id):
            raise _TaskPaused("Paused by operator")
        hold = _safety_hold(controller)
        if hold:
            self._pause_flags[task_id] = True
            raise _TaskPaused(hold)

        ok, detail = controller.send_waypoint(waypoint)
        if not ok:
            raise ValidationError(detail)
        # Only terminal states stamped with THIS goal's epoch may end the wait.
        epoch = int(controller.get_nav_status().get("epoch") or 0)

        progress = self._progress.setdefault(task_id, {})
        progress.update(leg=waypoint, status=TaskStatus.running.value, message=f"Going to {waypoint}")
        await tasks_repo.append_history(db, task_id, TaskStatus.running, f"Going to {waypoint}")

        poll = max(0.1, settings.nav_poll_interval_seconds)
        waited = 0.0
        while waited < settings.nav_goal_timeout_seconds:
            await asyncio.sleep(poll)
            waited += poll
            if self._pause_flags.get(task_id):
                raise _TaskPaused("Paused by operator")
            hold = _safety_hold(controller)
            nav = controller.get_nav_status()
            if hold or (nav.get("epoch") == epoch and nav.get("status") == NAV_PAUSED):
                # E-stop halted the robot: pause the mission, never fail it.
                self._pause_flags[task_id] = True
                raise _TaskPaused(hold or nav.get("message") or "Paused")
            if nav.get("epoch") != epoch:
                continue  # stale update from a previous leg — ignore
            state = nav.get("status")
            if state in TERMINAL_NAV_STATES:
                if state == NAV_SUCCEEDED:
                    return
                if state == NAV_CANCELLED:
                    raise _CancelledByOperator()
                raise ValidationError(f"Leg to {waypoint} {state}: {nav.get('message')}")
        controller.abort_waypoint(f"No arrival at {waypoint} within timeout")
        raise ValidationError(
            f"No arrival at {waypoint} after {int(settings.nav_goal_timeout_seconds)}s "
            "(is traffic_manager_node running on the fleet PC?)"
        )

    async def _finish(
        self, db, task_id: str, robot_id: str, status: TaskStatus, message: str
    ) -> None:
        self._progress.pop(task_id, None)
        self._pause_flags.pop(task_id, None)
        self._resume_events.pop(task_id, None)
        self._approve_events.pop(task_id, None)
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
            task_type=str(request.get("task_type") or "route"),
            robot_id=robot_id,
            stops=list(request.get("stops") or []),
            mode=str(request.get("mode") or "continuous"),
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


def _safety_hold(controller: Any) -> Optional[str]:
    """E-stop reason for a controller, or None (robots without the capability)."""
    hold = getattr(controller, "safety_hold", None)
    return hold() if callable(hold) else None


task_engine = TaskEngine()


async def validate_stops(db, stops: List[str]) -> None:
    """Reject waypoint names that are not in the active graph.

    With no graph uploaded yet there is nothing to check against, so names are
    accepted as typed (first bring-up); once a graph exists typos fail fast
    instead of timing out on the robot.
    """
    known = await fleet_file_service.waypoint_names(db)
    if not known:
        return
    unknown = [name for name in dict.fromkeys(stops) if name not in known]
    if unknown:
        raise ValidationError(
            "Unknown waypoint(s) not in the active graph: "
            + ", ".join(unknown)
            + ". Check the spelling or upload the current graph."
        )


async def start_mission(
    db, robot_id: str, stops: List[str], repeats: int, mode: str, created_by: str,
    task_type: str = "route",
) -> Dict[str, Any]:
    """Create a mission and immediately begin executing it."""
    await validate_stops(db, stops)
    task = await tasks_repo.create(
        db, task_type=task_type, robot_id=robot_id, stops=stops, repeats=repeats,
        mode=mode, created_by=created_by,
    )
    task_id = str(task["id"])
    try:
        started = await task_engine.start_task(db, task_id)
    except Exception:
        # Do not leave an orphan "pending" mission behind a rejected click.
        await tasks_repo.set_status(db, task_id, TaskStatus.cancelled, message="Could not start")
        raise
    return {"task": started or task, "progress": task_engine.progress(task_id) or {}}


async def send_waypoint(db, robot_id: str, waypoint: str, created_by: str) -> Dict[str, Any]:
    """The text box: a one-stop mission."""
    return await start_mission(db, robot_id, [waypoint], 1, "continuous", created_by,
                               task_type="waypoint")
