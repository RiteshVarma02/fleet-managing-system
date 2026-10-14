"""Roles: developer > admin > operator, portal login, account management, seeding."""

from __future__ import annotations

import asyncio

import pytest

from app import startup
from app.api import deps
from app.api.deps import Principal, require_admin, require_developer, require_operator
from app.api.v1.endpoints import auth, system, users
from app.core.exceptions import AuthError, ForbiddenError
from app.db.documents import Role, role_rank
from app.schemas.auth import LoginRequest

DEV = Principal(username="dev", role="developer")
ADMIN = Principal(username="boss", role="admin")
OP = Principal(username="op", role="operator")
VIEWER = Principal(username="old", role="viewer")


def test_rank_order():
    assert role_rank("developer") > role_rank("admin") > role_rank("operator") > 0
    assert role_rank("viewer") == 0 and role_rank("nonsense") == 0


@pytest.mark.parametrize("dep,allowed", [
    (require_operator, {"developer", "admin", "operator"}),
    (require_admin, {"developer", "admin"}),
    (require_developer, {"developer"}),
])
def test_each_role_inherits_the_ones_below(dep, allowed):
    for principal in (DEV, ADMIN, OP, VIEWER):
        if principal.role in allowed:
            assert dep(principal) is principal
        else:
            with pytest.raises(ForbiddenError):
                dep(principal)


def test_topics_endpoints_are_developer_only():
    for route in system.router.routes:
        if route.path.startswith("/system/topics"):
            names = {d.call for d in route.dependant.dependencies}
            assert require_developer in names, route.path


def test_admin_cannot_manage_admin_or_developer_accounts():
    users.assert_can_assign(ADMIN, "operator")
    for role in ("admin", "developer"):
        with pytest.raises(ForbiddenError):
            users.assert_can_assign(ADMIN, role)


def test_developer_can_manage_everyone():
    for role in ("developer", "admin", "operator"):
        users.assert_can_assign(DEV, role)


# ---- portal login -----------------------------------------------------------
class FakeUsers:
    def __init__(self, doc):
        self.doc = doc

    async def get_by_username(self, db, name):
        return self.doc

    async def touch_login(self, db, uid):
        return None


def _login(monkeypatch, role, portal, active=True):
    from app.core.security import hash_password

    doc = {"id": "1", "username": "u", "role": role, "active": active,
           "password_hash": hash_password("pw-pw-pw-pw")}
    monkeypatch.setattr(auth, "user_repo", FakeUsers(doc))
    return asyncio.run(auth.login(LoginRequest(username="u", password="pw-pw-pw-pw", portal=portal), None))


def test_operator_cannot_use_admin_portal(monkeypatch):
    with pytest.raises(ForbiddenError):
        _login(monkeypatch, "operator", Role.admin)
    with pytest.raises(ForbiddenError):
        _login(monkeypatch, "admin", Role.developer)


def test_higher_role_may_use_lower_portal_and_gets_its_real_role(monkeypatch):
    out = _login(monkeypatch, "developer", Role.operator)
    assert out.user.role == "developer"


def test_login_without_portal_still_works(monkeypatch):
    assert _login(monkeypatch, "operator", None).user.role == "operator"


def test_disabled_and_retired_accounts_cannot_log_in(monkeypatch):
    with pytest.raises(AuthError):
        _login(monkeypatch, "operator", None, active=False)
    with pytest.raises(ForbiddenError):
        _login(monkeypatch, "viewer", None)


# ---- seeding ----------------------------------------------------------------
def test_production_requires_developer_password(monkeypatch):
    monkeypatch.setattr(startup.settings, "environment", "production")
    monkeypatch.setattr(startup.settings, "bootstrap_developer_password", "")
    with pytest.raises(RuntimeError, match="DEVELOPER"):
        startup.bootstrap_accounts()


def test_production_seeds_only_accounts_with_a_password(monkeypatch):
    monkeypatch.setattr(startup.settings, "environment", "production")
    monkeypatch.setattr(startup.settings, "bootstrap_developer_password", "dev-pass-1")
    monkeypatch.setattr(startup.settings, "bootstrap_admin_password", "")
    monkeypatch.setattr(startup.settings, "bootstrap_operator_password", "op-pass-1")
    got = {role.value for role, _, _ in startup.bootstrap_accounts()}
    assert got == {"developer", "operator"}


def test_development_falls_back_to_throwaway_defaults(monkeypatch):
    monkeypatch.setattr(startup.settings, "environment", "development")
    for field in ("developer", "admin", "operator"):
        monkeypatch.setattr(startup.settings, f"bootstrap_{field}_password", "")
    assert {r.value for r, _, _ in startup.bootstrap_accounts()} == {"developer", "admin", "operator"}


def test_seed_is_idempotent_and_disables_viewers(monkeypatch):
    created, disabled = [], []

    class Repo:
        existing = {"admin"}

        async def get_by_username(self, db, name):
            return {"username": name} if name in self.existing else None

        async def create(self, db, username, password_hash, role):
            created.append((username, role.value))
            return {"username": username}

        async def deactivate_role(self, db, role):
            disabled.append(role)
            return 2

    monkeypatch.setattr(startup, "user_repo", Repo())
    monkeypatch.setattr(startup.settings, "environment", "development")
    asyncio.run(startup.seed_initial_data(None))
    assert ("developer", "developer") in created and ("operator", "operator") in created
    assert all(name != "admin" for name, _ in created)
    assert disabled == ["viewer"]


def test_deps_module_exports():
    assert deps.require_developer is require_developer
