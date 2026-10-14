"""Route-ordering regression tests.

Starlette resolves routes in declaration order, so static paths declared after
a matching `/{param}` pattern are silently shadowed and their handlers never
run. The tasks router must declare all static paths (`/missions`,
`/waypoint`, `/robot/*`, `/requests/*`) before the `/{task_id}` dynamic routes. These tests pin the
declared order by resolving request paths against the router's compiled
patterns and asserting the handler that wins.
"""

from __future__ import annotations

import re

import pytest

from app.api.v1.endpoints import tasks


def _resolve(router, method: str, path: str):
    for route in router.routes:
        if not hasattr(route, "path_regex"):
            continue
        if method not in (route.methods or []):
            continue
        if re.match(route.path_regex, path):
            return route.endpoint.__name__
    return None


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("POST", "/tasks/missions", "start_mission_endpoint"),
        ("POST", "/tasks/waypoint", "send_waypoint_endpoint"),
        ("GET", "/tasks/robot/robot_1/progress", "robot_progress"),
        ("POST", "/tasks/robot/robot_1/pause", "robot_control"),
        ("POST", "/tasks/requests", "create_request"),
        ("GET", "/tasks/requests/unassigned", "unassigned_requests"),
    ],
)
def test_static_task_routes_are_not_shadowed_by_dynamic(method, path, expected):
    assert _resolve(tasks.router, method, path) == expected


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("POST", "/tasks/abc123/start", "start_task"),
        ("GET", "/tasks/abc123/progress", "task_progress"),
        ("GET", "/tasks/abc123/history", "task_history"),
        ("GET", "/tasks/abc123", "get_task"),
        ("PATCH", "/tasks/abc123", "update_task"),
    ],
)
def test_dynamic_task_routes_still_resolve(method, path, expected):
    assert _resolve(tasks.router, method, path) == expected