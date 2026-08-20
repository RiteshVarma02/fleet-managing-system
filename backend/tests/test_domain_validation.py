"""ROS domain id validation tests.

Every robot runs on its own ROS_DOMAIN_ID; the server owns `ros_domain_id`
(domain 0 by default) and hands each new robot the next free domain at or above
`domain_bridge_default_robot_domain`. These tests cover the two DB helpers that
implement the "next free domain" rule and the Pydantic constraints on the
schemas that carry a domain id.
"""

from __future__ import annotations

import asyncio

from pydantic import ValidationError
import pytest

from app.db.repositories import robots_repo
from app.schemas.robot import MapShareCommand, RobotApproveRequest, validate_robot_id


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length):
        return self._docs


class _FakeDb:
    """AsyncMotor-style fake: `db[collection].find(...)` -> cursor with to_list."""

    def __init__(self, docs):
        self._docs = docs

    def __getitem__(self, name):
        return self

    def find(self, query, projection=None):
        live = [d for d in self._docs if d.get("ros_domain_id") is not None and not d.get("is_deleted")]
        return _FakeCursor(live)


async def _next_domain(docs, *, start=2, reserved=None):
    return await robots_repo.next_domain_id(_FakeDb(docs), start=start, reserved=reserved)


def _run(coro):
    return asyncio.run(coro)


def test_next_domain_returns_start_when_free():
    assert _run(_next_domain([])) == 2


def test_next_domain_skips_used_and_reserved():
    docs = [
        {"robot_id": "robot_1", "ros_domain_id": 2},
        {"robot_id": "robot_2", "ros_domain_id": 3},
        {"robot_id": "robot_3", "ros_domain_id": 5},
    ]
    assert _run(_next_domain(docs, start=2, reserved=[0])) == 4


def test_next_domain_reserves_server_domain():
    # Server sits on domain 0 and asks from the default start — the server's
    # own domain is never handed out.
    assert _run(_next_domain([], start=0, reserved=[0])) == 1


def test_next_domain_ignores_soft_deleted_robots():
    docs = [
        {"robot_id": "robot_1", "ros_domain_id": 2, "is_deleted": True},
        {"robot_id": "robot_2", "ros_domain_id": 2, "is_deleted": False},
    ]
    assert _run(_next_domain(docs, start=2)) == 3


def test_used_domains_sorted_and_shaped():
    docs = [
        {"robot_id": "robot_b", "ros_domain_id": 3},
        {"robot_id": "robot_a", "ros_domain_id": 2},
        {"robot_id": "ghost", "ros_domain_id": None, "is_deleted": False},
        {"robot_id": "deleted", "ros_domain_id": 4, "is_deleted": True},
    ]
    used = _run(robots_repo.used_domains(_FakeDb(docs)))
    assert used == [
        {"domain": 2, "robot_id": "robot_a"},
        {"domain": 3, "robot_id": "robot_b"},
    ]


def test_approve_request_rejects_domain_out_of_range():
    base = {"mac_address": "AA:BB:CC:DD:EE:FF", "custom_name": "robo"}
    with pytest.raises(ValidationError):
        RobotApproveRequest(**base, ros_domain_id=-1)
    with pytest.raises(ValidationError):
        RobotApproveRequest(**base, ros_domain_id=233)


def test_approve_request_allows_serialisable_domain():
    request = RobotApproveRequest(mac_address="AA:BB:CC:DD:EE:FF", custom_name="robo", ros_domain_id=2)
    assert request.ros_domain_id == 2


def test_map_share_command_defaults_to_disabled():
    command = MapShareCommand()
    assert command.enabled is False
    assert MapShareCommand(enabled=True).enabled is True
    # robot_id is not part of the body — it lives in the URL path.
    assert "robot_id" not in MapShareCommand.model_fields


def test_validate_robot_id_rejects_traversal_and_whitespace():
    for bad in ("../etc", "a b", "robot@1", ""):
        with pytest.raises(ValueError):
            validate_robot_id(bad)
    assert validate_robot_id(" robot_1 ") == "robot_1"