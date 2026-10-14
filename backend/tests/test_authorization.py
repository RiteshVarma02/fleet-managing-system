"""Endpoint authorization tests (M1/M2).

Fleet-file writes need admin, mission commands need operator; read
endpoints may stay open to any authenticated user. `require_operator` is
asserted to be in each write route's dependency chain and to actually reject
the read-only `viewer` role.
"""

from __future__ import annotations

import pytest

from app.api.deps import Principal, get_current_user, require_admin, require_operator
from app.api.v1.endpoints import fleet_files, tasks
from app.core.exceptions import ForbiddenError

VIEWER = Principal(username="viewer", role="viewer")
OPERATOR = Principal(username="op", role="operator")


def _dependency_callables(route):
    seen = set()
    out = []

    def walk(dep):
        if dep.call is not None and dep.call not in seen:
            seen.add(dep.call)
            out.append(dep.call)
        for sub in dep.dependencies:
            walk(sub)

    walk(route.dependant)
    return out


def _routes(router):
    return [r for r in router.routes if getattr(r, "methods", None)]


FILE_WRITE_PATHS = {
    ("POST", "/fleet-files/graph"),
    ("POST", "/fleet-files/map"),
    ("POST", "/fleet-files/{kind}/versions/{version}/activate"),
    ("POST", "/fleet-files/{kind}/push"),
}

FILE_READ_PATHS = {
    ("GET", "/fleet-files"),
    ("GET", "/fleet-files/status"),
    ("GET", "/fleet-files/map/preview"),
    ("GET", "/fleet-files/{kind}/download"),
}


@pytest.mark.parametrize("method,path", sorted(FILE_WRITE_PATHS))
def test_fleet_file_writes_require_admin(method, path):
    route = next(r for r in _routes(fleet_files.router) if path == r.path and method in (r.methods or []))
    assert require_admin in _dependency_callables(route), f"{method} {path} must require admin"


@pytest.mark.parametrize("method,path", sorted(FILE_READ_PATHS))
def test_fleet_file_reads_allow_any_authenticated_user(method, path):
    route = next(r for r in _routes(fleet_files.router) if path == r.path and method in (r.methods or []))
    deps = _dependency_callables(route)
    assert get_current_user in deps
    assert require_admin not in deps and require_operator not in deps


def test_waypoints_readable_by_any_authenticated_user():
    route = _routes(fleet_files.waypoints_router)[0]
    assert get_current_user in _dependency_callables(route)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/tasks"),
        ("POST", "/tasks/missions"),
        ("POST", "/tasks/waypoint"),
        ("POST", "/tasks/{task_id}/approve"),
        ("POST", "/tasks/{task_id}/pause"),
        ("POST", "/tasks/{task_id}/resume"),
        ("POST", "/tasks/{task_id}/cancel"),
    ],
)
def test_mission_commands_require_operator(method, path):
    route = next(r for r in _routes(tasks.router) if path == r.path and method in (r.methods or []))
    assert require_operator in _dependency_callables(route)


def test_mission_progress_readable_by_any_authenticated_user():
    route = next(r for r in _routes(tasks.router) if r.path == "/tasks/robot/{robot_id}/progress")
    deps = _dependency_callables(route)
    assert get_current_user in deps and require_operator not in deps


def test_require_operator_rejects_viewer():
    with pytest.raises(ForbiddenError):
        require_operator(VIEWER)


def test_require_operator_allows_operator_and_admin():
    assert require_operator(OPERATOR) is OPERATOR
    assert require_operator(Principal(username="admin", role="admin")).is_admin