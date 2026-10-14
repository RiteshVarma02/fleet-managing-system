"""E-stop is absolute: neither teleop nor any other command may move the robot."""

from __future__ import annotations

import pytest

from app.api.v1.endpoints import robots, tasks
from app.core.exceptions import ConflictError
from app.ros.capabilities.movement import MovementCapability


class Pub:
    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append((msg.linear.x, msg.angular.z))


class Twist:
    class _V:
        x = 0.0
        z = 0.0

    def __init__(self):
        self.linear = type("L", (), {"x": 0.0})()
        self.angular = type("A", (), {"z": 0.0})()


class Robot(MovementCapability):
    def __init__(self, hold=None):
        import threading

        self._cmd_vel_pub = Pub()
        self._state_lock = threading.RLock()
        self.current_velocity = {}
        self._hold = hold

    def msg(self, logical):
        return Twist()

    def safety_hold(self):
        return self._hold


def test_teleop_moves_when_no_estop():
    r = Robot()
    assert r.move(0.4, 0.1) is True
    assert r._cmd_vel_pub.sent == [(0.4, 0.1)]


@pytest.mark.parametrize("hold", ["Physical E-stop pressed", "Software E-stop engaged"])
def test_teleop_is_replaced_by_a_stop_during_estop(hold):
    r = Robot(hold=hold)
    assert r.move(0.4, 0.1) is False
    assert r._cmd_vel_pub.sent == [(0.0, 0.0)]  # never the requested velocity


def test_stop_is_always_allowed_during_estop():
    r = Robot(hold="Physical E-stop pressed")
    assert r.move(0.0, 0.0) is True
    r.stop()
    assert all(v == (0.0, 0.0) for v in r._cmd_vel_pub.sent)


def test_endpoint_helper_returns_409_style_error():
    with pytest.raises(ConflictError, match="E-stop"):
        robots._refuse_during_estop(Robot(hold="Physical E-stop pressed"))
    robots._refuse_during_estop(Robot())  # no error


def test_only_one_set_of_mission_controls_exists():
    paths = {(m, r.path) for r in tasks.router.routes for m in (r.methods or [])}
    for old in ("pause", "resume", "cancel", "approve"):
        assert ("POST", f"/tasks/{{task_id}}/{old}") not in paths
    assert ("POST", "/tasks/robot/{robot_id}/{action}") in paths
