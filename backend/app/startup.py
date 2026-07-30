"""Idempotent bootstrap data (admin user, demo locations)."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.repositories import users as user_repo

logger = get_logger(__name__)


def seed_initial_data(db: Session) -> None:
    """Create the bootstrap admin if no user exists.

    The password comes from `ADMIN_PASSWORD`. In production a missing value is
    fatal rather than silently defaulting to a well-known password.
    """
    username = os.getenv("ADMIN_USERNAME", "admin")
    if user_repo.get_by_username(db, username) is not None:
        return

    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        if settings.is_production:
            raise RuntimeError("ADMIN_PASSWORD must be set in production to seed the admin user")
        password = "admin123"
        logger.warning("Seeding admin user with the development default password")

    user_repo.ensure_user(db, username=username, password=password, role="admin")
    logger.info("Bootstrap admin user '%s' created", username)
