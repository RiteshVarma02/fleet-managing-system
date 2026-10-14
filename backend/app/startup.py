"""Idempotent bootstrap data: the three role accounts and retired-role cleanup."""

from __future__ import annotations

from typing import List, Tuple

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.security import hash_password
from app.db.documents import Role
from app.db.repositories import users_repo as user_repo

logger = get_logger(__name__)

_DEV_DEFAULTS = {
    Role.developer: "developer123",
    Role.admin: "admin123",
    Role.operator: "operator123",
}


def bootstrap_accounts() -> List[Tuple[Role, str, str]]:
    """(role, username, password) to seed, honouring the production rules.

    * production: the developer password MUST be set; admin/operator are
      seeded only when their password is set (no built-in defaults).
    * development: a missing password falls back to a throwaway default.
    """
    wanted = [
        (Role.developer, settings.bootstrap_developer_username, settings.bootstrap_developer_password),
        (Role.admin, settings.bootstrap_admin_username, settings.bootstrap_admin_password),
        (Role.operator, settings.bootstrap_operator_username, settings.bootstrap_operator_password),
    ]
    out: List[Tuple[Role, str, str]] = []
    for role, username, password in wanted:
        username = username.strip().lower()
        if not password:
            if settings.is_production:
                if role is Role.developer:
                    raise RuntimeError(
                        "BOOTSTRAP_DEVELOPER_PASSWORD must be set in production "
                        "to seed the developer account"
                    )
                continue
            password = _DEV_DEFAULTS[role]
            logger.warning("Seeding %s '%s' with the development default password", role.value, username)
        out.append((role, username, password))
    return out


async def seed_initial_data(db) -> None:
    for role, username, password in bootstrap_accounts():
        if await user_repo.get_by_username(db, username) is not None:
            continue
        created = await user_repo.create(db, username, hash_password(password), role)
        if created is not None:
            logger.info("Bootstrap %s '%s' created", role.value, username)

    # The read-only `viewer` role is gone. Do NOT promote those accounts to
    # operator (that would grant command rights nobody asked for): disable them
    # and let an administrator re-create them with an explicit role.
    disabled = await user_repo.deactivate_role(db, "viewer")
    if disabled:
        logger.warning("Disabled %d legacy 'viewer' account(s); recreate them as operators", disabled)
