"""Regression: a pick-drop task must drive every leg of every cycle.

Previously `append_history` received `TaskStatus.running.value` (a str) and
crashed with "'str' object has no attribute 'value'" right after the PICKUP
goal was published, so the DROP leg never ran.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.db.documents import TaskStatus
from app.db.repositories import tasks_repo
from app.services import task_service as ts


class FakeNav:
    """Stands in for a waypoint_nav controller that arrives instantly."""

    def __init__(self) -> None:
        self.goals: List[str] = []
        self.epoch = 0
        self.hold = None

    def send_waypoint(self, name):
        self.epoch += 1
        self.goals.append(name)
        return True, "ok"

    def get_nav_status(self) -> Dict[str, Any]:
        return {"epoch": self.epoch, "status": "succeeded"}

    def abort_waypoint(self, message="") -> None:
        pass

    def safety_hold(self):
        return self.hold


def test_status_value_accepts_enum_and_str():
    assert tasks_repo._status_value(TaskStatus.running) == "running"
    assert tasks_repo._status_value("running") == "running"
    with pytest.raises(ValueError):
        tasks_repo._status_value("bogus")


def test_pickdrop_runs_all_legs(monkeypatch):
    nav = FakeNav()
    state: Dict[str, Any] = {"status": "running", "completed_repeats": 0}
    history: List[tuple] = []
    cleared: List[str] = []
    locs = {"p": {"name": "PICKUP", "x": 1.0, "y": 1.0}, "d": {"name": "DROP", "x": 2.0, "y": 2.0}}

    async def get(db, tid):
        return {**state, "from_location_id": "p", "to_location_id": "d", "repeats": 2}

    async def append_history(db, tid, status, msg=None):
        history.append((tasks_repo._status_value(status), msg))

    async def set_status(db, tid, status, message=None):
        state["status"] = TaskStatus(status).value

    async def inc(db, tid):
        state["completed_repeats"] += 1

    async def loc_get(db, lid):
        return locs[lid]

    async def clear(db, rid):
        cleared.append(rid)

    monkeypatch.setattr(ts, "get_database", lambda: None)
    monkeypatch.setattr(ts.tasks_repo, "get", get)
    monkeypatch.setattr(ts.tasks_repo, "append_history", append_history)
    monkeypatch.setattr(ts.tasks_repo, "set_status", set_status)
    monkeypatch.setattr(ts.tasks_repo, "increment_repeats", inc)
    monkeypatch.setattr(ts.locations_repo, "get", loc_get)
    monkeypatch.setattr(ts.robots_repo, "clear_active_task", clear)
    monkeypatch.setattr(ts.robot_service, "require_controller", lambda *a, **k: nav)
    monkeypatch.setattr(ts.settings, "nav_poll_interval_seconds", 0.01, raising=False)

    engine = ts.TaskEngine()
    asyncio.run(engine._run("t1", "robot_1"))

    assert nav.goals == ["PICKUP", "DROP", "PICKUP", "DROP"]
    assert state["status"] == "completed"
    assert state["completed_repeats"] == 2
    assert cleared == ["robot_1"]
    assert ("running", "Going to DROP") in history


def test_estop_pauses_the_leg_instead_of_failing(monkeypatch):
    nav = FakeNav()
    nav.hold = "Physical E-stop pressed"
    history: List[tuple] = []

    async def append_history(db, tid, status, msg=None):
        history.append(msg)

    monkeypatch.setattr(ts.tasks_repo, "append_history", append_history)
    monkeypatch.setattr(ts.robot_service, "require_controller", lambda *a, **k: nav)

    engine = ts.TaskEngine()
    with pytest.raises(ts._TaskPaused, match="Physical E-stop pressed"):
        asyncio.run(engine._drive_to(None, "t1", "robot_1", {"name": "WP_1"}))
    assert nav.goals == []  # nothing dispatched while the button is pressed
    assert engine._pause_flags["t1"] is True


def test_resume_is_refused_while_estop_is_held(monkeypatch):
    nav = FakeNav()
    nav.hold = "Physical E-stop pressed"
    monkeypatch.setattr(ts.robot_service, "require_controller", lambda *a, **k: nav)

    engine = ts.TaskEngine()
    engine._pause_flags["t1"] = True
    engine._progress["t1"] = {"robot_id": "robot_1"}
    with pytest.raises(ts.ConflictError, match="E-stop"):
        asyncio.run(engine.resume_task(None, "t1"))
    assert engine._pause_flags["t1"] is True  # still paused
