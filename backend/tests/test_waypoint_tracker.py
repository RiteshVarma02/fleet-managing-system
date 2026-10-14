"""`final_goal_reached` has no goal id: the tracker must not let a late TRUE
from the previous leg complete the current one."""

from __future__ import annotations

from app.ros.capabilities.waypoint_nav import (
    NAV_ACTIVE,
    NAV_CANCELLED,
    NAV_PAUSED,
    NAV_SUCCEEDED,
    WaypointTracker,
)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_arrival_inside_debounce_window_is_ignored():
    clock = Clock()
    tracker = WaypointTracker(1.5, clock=clock)
    tracker.start("WP_2")
    clock.now += 0.2
    assert tracker.on_reached(True) is False  # stale TRUE from the last leg
    assert tracker.status()["status"] == NAV_ACTIVE
    clock.now += 2.0
    assert tracker.on_reached(True) is True
    assert tracker.status()["status"] == NAV_SUCCEEDED
    assert tracker.done.is_set()


def test_false_and_idle_samples_never_complete_a_leg():
    clock = Clock()
    tracker = WaypointTracker(0.0, clock=clock)
    assert tracker.on_reached(True) is False  # nothing dispatched yet
    tracker.start("WP_1")
    assert tracker.on_reached(False) is False
    assert tracker.status()["status"] == NAV_ACTIVE


def test_each_goal_gets_a_new_epoch():
    tracker = WaypointTracker(0.0, clock=Clock())
    first = tracker.start("A")
    second = tracker.start("B")
    assert second == first + 1
    assert tracker.status()["goal"] == "B"


def test_pause_remembers_goal_and_ignores_arrivals():
    clock = Clock()
    tracker = WaypointTracker(0.0, clock=clock)
    tracker.start("WP_5")
    assert tracker.pause("Physical E-stop pressed") == "WP_5"
    assert tracker.status()["status"] == NAV_PAUSED
    assert tracker.on_reached(True) is False
    assert tracker.paused_goal() == "WP_5"


def test_cancel_is_terminal():
    tracker = WaypointTracker(0.0, clock=Clock())
    tracker.start("WP_1")
    tracker.cancel("Aborted")
    assert tracker.status()["status"] == NAV_CANCELLED
    assert tracker.done.is_set()
