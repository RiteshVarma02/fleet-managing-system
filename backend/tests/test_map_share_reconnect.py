"""Map-share survives reconnects (H3 regression).

`ros_manager.start_controller` must forward the robot's stored
`map_share_enabled` flag into the domain bridge, and the connect /
registration entry points must pass it through. Otherwise the DOWN `/map`
topic is silently dropped every time a robot reconnects (connect endpoint,
registration approval, app-restart autostart).
"""

from __future__ import annotations

import asyncio

from app.ros import manager as ros_manager_module
from app.services import registration_service, robot_service


def _robot(**overrides):
    doc = {
        "robot_id": "robot_1",
        "robot_type": "differential_drive",
        "ros_domain_id": 2,
        "approved": True,
        "is_deleted": False,
        "map_share_enabled": False,
    }
    doc.update(overrides)
    return doc


def _run(coro):
    return asyncio.run(coro)


def _capture_start_controller(calls):
    def fake_start_controller(robot_id, robot_type, ros_domain_id, *, share_map=False):
        calls["share_map"] = share_map
        return True, "ok"

    return fake_start_controller


def _async_return(value):
    async def fake(*args, **kwargs):
        return value

    return fake


def test_connect_forwards_stored_map_share_flag(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        robot_service.ros_manager, "start_controller", _capture_start_controller(calls)
    )
    monkeypatch.setattr(
        robot_service.robots_repo, "get", _async_return(_robot(map_share_enabled=True))
    )
    monkeypatch.setattr(
        robot_service.robots_repo,
        "upsert",
        _async_return(_robot(map_share_enabled=True)),
    )

    _run(robot_service.connect(object(), "robot_1"))
    assert calls["share_map"] is True


def test_connect_defaults_to_no_map_share(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        robot_service.ros_manager, "start_controller", _capture_start_controller(calls)
    )
    monkeypatch.setattr(robot_service.robots_repo, "get", _async_return(_robot()))
    monkeypatch.setattr(robot_service.robots_repo, "upsert", _async_return(_robot()))

    _run(robot_service.connect(object(), "robot_1"))
    assert calls["share_map"] is False


def test_registration_forwards_stored_map_share_flag(monkeypatch):
    calls = {}
    monkeypatch.setattr(
        registration_service.ros_manager, "start_controller", _capture_start_controller(calls)
    )
    monkeypatch.setattr(
        registration_service.robots_repo,
        "get_by_mac",
        _async_return(_robot(map_share_enabled=True)),
    )
    monkeypatch.setattr(
        registration_service.robots_repo,
        "upsert",
        _async_return(_robot(map_share_enabled=True)),
    )

    result = _run(
        registration_service.handle_registration(object(), "AA:BB:CC:DD:EE:FF", None, None)
    )
    assert result["status"] == "approved"
    assert calls["share_map"] is True


def test_start_controller_forwards_share_map_to_ensure(monkeypatch):
    recorded = {}

    class _DummyRunner:
        def __init__(self, ros, node, name):
            self.node = node

        def shutdown(self):
            pass

    class _FakeRos:
        def __init__(self):
            self.rclpy = None

    class _DummyController:
        def __init__(self, *args, **kwargs):
            pass

        def shutdown(self):
            pass

    mgr = ros_manager_module.ros_manager
    monkeypatch.setattr(mgr, "_controllers", {})
    monkeypatch.setattr(mgr, "_runners", {})
    monkeypatch.setattr(mgr, "_ros", _FakeRos())
    monkeypatch.setattr(ros_manager_module, "_NodeRunner", _DummyRunner)
    monkeypatch.setattr(ros_manager_module.robot_factory, "create", lambda rid, rtype: _DummyController())

    def fake_ensure(robot_id, robot_type, ros_domain_id, share_map=False):
        recorded["share_map"] = share_map
        return {"running": False, "reason": "test"}

    monkeypatch.setattr(
        ros_manager_module.domain_bridge_manager, "ensure", fake_ensure
    )

    mgr.start_controller("robot_1", "differential_drive", 2, share_map=True)
    assert recorded["share_map"] is True
    assert "robot_1" in mgr._controllers