"""Mission engine: every stop of every cycle, move-on-click approvals, E-stop pause.

Regression kept from V0: `append_history` must accept the status enum or str
(it once crashed right after the first goal, so the second leg never ran).
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


class Harness:
    """Patches the DB layer with an in-memory task and returns the pieces."""

    def __init__(self, monkeypatch, nav, stops, repeats, mode="continuous"):
        self.state: Dict[str, Any] = {"status": "running", "completed_repeats": 0}
        self.history: List[tuple] = []
        self.cleared: List[str] = []
        self.cursors: List[tuple] = []
        doc = {"stops": stops, "repeats": repeats, "mode": mode}
        h = self

        async def get(db, tid):
            return {**h.state, **doc}

        async def append_history(db, tid, status, msg=None):
            h.history.append((tasks_repo._status_value(status), msg))

        async def set_status(db, tid, status, message=None):
            h.state["status"] = TaskStatus(status).value

        async def inc(db, tid):
            h.state["completed_repeats"] += 1

        async def set_cursor(db, tid, cycle, index):
            h.cursors.append((cycle, index))

        async def clear(db, rid):
            h.cleared.append(rid)

        async def no_validation(db, names):
            return None

        monkeypatch.setattr(ts, "get_database", lambda: None)
        monkeypatch.setattr(ts.tasks_repo, "get", get)
        monkeypatch.setattr(ts.tasks_repo, "append_history", append_history)
        monkeypatch.setattr(ts.tasks_repo, "set_status", set_status)
        monkeypatch.setattr(ts.tasks_repo, "increment_repeats", inc)
        monkeypatch.setattr(ts.tasks_repo, "set_cursor", set_cursor)
        monkeypatch.setattr(ts.robots_repo, "clear_active_task", clear)
        monkeypatch.setattr(ts, "validate_stops", no_validation)
        monkeypatch.setattr(ts.robot_service, "require_controller", lambda *a, **k: nav)
        monkeypatch.setattr(ts.settings, "nav_poll_interval_seconds", 0.01, raising=False)
        self.engine = ts.TaskEngine()
        self.engine._resume_events["t1"] = asyncio.Event()
        self.engine._approve_events["t1"] = asyncio.Event()
        self.engine._progress["t1"] = {"robot_id": "robot_1", "status": "running"}


def test_continuous_mission_visits_every_stop_every_cycle(monkeypatch):
    nav = FakeNav()
    h = Harness(monkeypatch, nav, ["WP_1", "WP_2", "WP_5", "WP_7", "WP_8"], repeats=2)
    asyncio.run(h.engine._run("t1", "robot_1"))

    assert nav.goals == ["WP_1", "WP_2", "WP_5", "WP_7", "WP_8"] * 2
    assert h.state["status"] == "completed"
    assert h.state["completed_repeats"] == 2
    assert h.cleared == ["robot_1"]
    assert ("running", "Going to WP_2") in h.history
    assert h.cursors[0] == (1, 0) and h.cursors[-1] == (2, 4)


def test_single_waypoint_mission(monkeypatch):
    nav = FakeNav()
    h = Harness(monkeypatch, nav, ["Dock_A"], repeats=1)
    asyncio.run(h.engine._run("t1", "robot_1"))
    assert nav.goals == ["Dock_A"] and h.state["status"] == "completed"


def test_step_mode_waits_for_approval_before_every_move(monkeypatch):
    nav = FakeNav()
    h = Harness(monkeypatch, nav, ["A", "B", "C"], repeats=2, mode="step")
    engine = h.engine
    seen: List[List[str]] = []

    async def scenario():
        runner = asyncio.create_task(engine._run("t1", "robot_1"))
        engine._running["t1"] = runner  # is_running() needs the live task
        approvals = 0
        while not runner.done():
            await asyncio.sleep(0.03)
            progress = engine._progress.get("t1") or {}
            if progress.get("status") == "awaiting_approval":
                seen.append(list(nav.goals))
                # Standing still: no new goal is sent until we approve.
                await asyncio.sleep(0.05)
                assert nav.goals == seen[-1]
                await engine.approve_task(None, "t1")
                approvals += 1
        return approvals

    approvals = asyncio.run(scenario())
    assert nav.goals == ["A", "B", "C", "A", "B", "C"]
    # 6 arrivals, no approval needed after the very last one.
    assert approvals == 5
    assert seen[0] == ["A"] and seen[-1] == ["A", "B", "C", "A", "B"]
    assert h.state["status"] == "completed"


def test_approve_is_rejected_when_not_waiting(monkeypatch):
    nav = FakeNav()
    h = Harness(monkeypatch, nav, ["A"], repeats=1)
    h.engine._running["t1"] = asyncio.new_event_loop().create_future()  # not done
    with pytest.raises(ts.ConflictError, match="not waiting"):
        asyncio.run(h.engine.approve_task(None, "t1"))


def test_approve_is_refused_during_estop(monkeypatch):
    nav = FakeNav()
    nav.hold = "Physical E-stop pressed"
    h = Harness(monkeypatch, nav, ["A", "B"], repeats=1, mode="step")
    h.engine._progress["t1"]["status"] = "awaiting_approval"
    h.engine._running["t1"] = asyncio.new_event_loop().create_future()
    with pytest.raises(ts.ConflictError, match="E-stop"):
        asyncio.run(h.engine.approve_task(None, "t1"))
    assert not h.engine._approve_events["t1"].is_set()


def test_pause_is_refused_while_waiting_for_approval(monkeypatch):
    nav = FakeNav()
    h = Harness(monkeypatch, nav, ["A", "B"], repeats=1, mode="step")
    h.engine._progress["t1"]["status"] = "awaiting_approval"
    h.engine._running["t1"] = asyncio.new_event_loop().create_future()
    with pytest.raises(ts.ConflictError, match="waiting for approval"):
        asyncio.run(h.engine.pause_task(None, "t1"))


def test_validate_stops_rejects_names_missing_from_graph(monkeypatch):
    async def names(db):
        return {"A", "B"}

    monkeypatch.setattr(ts.fleet_file_service, "waypoint_names", names)
    asyncio.run(ts.validate_stops(None, ["A", "B", "A"]))
    with pytest.raises(ts.ValidationError, match="C"):
        asyncio.run(ts.validate_stops(None, ["A", "C"]))


def test_validate_stops_accepts_anything_before_a_graph_exists(monkeypatch):
    async def names(db):
        return set()

    monkeypatch.setattr(ts.fleet_file_service, "waypoint_names", names)
    asyncio.run(ts.validate_stops(None, ["whatever"]))


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
        asyncio.run(engine._drive_to(None, "t1", "robot_1", "WP_1"))
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
