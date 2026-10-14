"""One status rule table for the whole system (first match wins)."""

from __future__ import annotations

import pytest

from app.db.documents import RobotStatus
from app.services.robot_status import derive_status

LIVE = dict(connected=True, seconds_since_seen=1.0, stale_after_seconds=15.0)


@pytest.mark.parametrize(
    "overrides,expected",
    [
        (dict(connected=False), RobotStatus.offline),
        (dict(seconds_since_seen=None), RobotStatus.offline),
        (dict(seconds_since_seen=30.0), RobotStatus.offline),
        (dict(stop_active=True, task_status="running", nav_status="active"), RobotStatus.stop_active),
        (dict(emergency_active=True), RobotStatus.e_stopped),
        (dict(stop_active=True, emergency_active=True), RobotStatus.stop_active),
        (dict(task_status="awaiting_approval"), RobotStatus.awaiting_approval),
        (dict(task_status="paused"), RobotStatus.paused),
        (dict(nav_status="paused"), RobotStatus.paused),
        (dict(nav_status="failed"), RobotStatus.error),
        (dict(nav_status="active"), RobotStatus.moving),
        (dict(task_status="running", nav_status="succeeded"), RobotStatus.moving),
        (dict(), RobotStatus.idle),
        (dict(nav_status="succeeded"), RobotStatus.idle),
    ],
)
def test_status_rules(overrides, expected):
    assert derive_status(**{**LIVE, **overrides}) == expected


def test_offline_beats_stop_active():
    # A robot we cannot hear from is offline, whatever its last flags were.
    assert derive_status(**{**LIVE, "connected": False, "stop_active": True}) == RobotStatus.offline
