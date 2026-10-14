"""Idempotent bootstrap data (admin user)."""

from __future__ import annotations

from app.core.config import settings
from app.core.logging_config import get_logger
from app.core.security import hash_password
from app.db.documents import Role
from app.db.repositories import users_repo as user_repo

logger = get_logger(__name__)


async def seed_initial_data(db) -> None:
    """Create the bootstrap admin if no user exists.

    Uses `BOOTSTRAP_ADMIN_*` settings from config.
    """
    username = settings.bootstrap_admin_username.strip().lower()
    if await user_repo.get_by_username(db, username) is not None:
        return

    password = settings.bootstrap_admin_password
    if not password:
        if settings.is_production:
            raise RuntimeError(
                "BOOTSTRAP_ADMIN_PASSWORD must be set in production to seed the admin user"
            )
        password = "admin123"
        logger.warning("Seeding admin user with the development default password")

    created = await user_repo.create(
        db,
        username=username,
        password_hash=hash_password(password),
        role=Role.admin,
    )
    if created is None:
        logger.info("Bootstrap admin user '%s' already exists", username)
        return

    logger.info("Bootstrap admin user '%s' created", username)
