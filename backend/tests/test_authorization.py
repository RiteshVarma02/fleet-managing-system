"""Endpoint authorization tests (M1/M2).

Map and location *write* endpoints must require operator privileges; read
endpoints may stay open to any authenticated user. `require_operator` is
asserted to be in each write route's dependency chain and to actually reject
the read-only `viewer` role.
"""

from __future__ import annotations

import pytest

from app.api.deps import Principal, get_current_user, require_operator
from app.api.v1.endpoints import locations, maps
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


MAP_WRITE_PATHS = {
    ("POST", "/maps/load"),
    ("POST", "/maps/activate"),
    ("DELETE", "/maps/{name}"),
}

MAP_READ_PATHS = {
    ("GET", "/maps/current"),
    ("GET", "/maps"),
}


@pytest.mark.parametrize("method,path", sorted(MAP_WRITE_PATHS))
def test_map_write_endpoints_require_operator(method, path):
    route = next(
        r for r in _routes(maps.router) if path == r.path and method in (r.methods or [])
    )
    deps = _dependency_callables(route)
    assert require_operator in deps, f"{method} {path} must require operator"


@pytest.mark.parametrize("method,path", sorted(MAP_READ_PATHS))
def test_map_read_endpoints_allow_any_authenticated_user(method, path):
    route = next(
        r for r in _routes(maps.router) if path == r.path and method in (r.methods or [])
    )
    deps = _dependency_callables(route)
    assert get_current_user in deps
    assert require_operator not in deps, f"{method} {path} should not require operator"


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/locations"),
        ("DELETE", "/locations/{location_id}"),
    ],
)
def test_location_write_endpoints_require_operator(method, path):
    route = next(
        r for r in _routes(locations.router) if path == r.path and method in (r.methods or [])
    )
    assert require_operator in _dependency_callables(route)


def test_location_read_endpoint_allows_any_authenticated_user():
    route = next(
        r for r in _routes(locations.router) if r.path == "/locations" and "GET" in r.methods
    )
    deps = _dependency_callables(route)
    assert get_current_user in deps
    assert require_operator not in deps


def test_require_operator_rejects_viewer():
    with pytest.raises(ForbiddenError):
        require_operator(VIEWER)


def test_require_operator_allows_operator_and_admin():
    assert require_operator(OPERATOR) is OPERATOR
    assert require_operator(Principal(username="admin", role="admin")).is_admin