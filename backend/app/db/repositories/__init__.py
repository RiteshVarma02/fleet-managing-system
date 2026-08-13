"""MongoDB repositories — the only layer that talks to the database."""

from app.db.repositories import (  # noqa: F401
    locations_repo,
    maps_repo,
    pending_requests_repo,
    robot_registrations_repo,
    robots_repo,
    tasks_repo,
    users_repo,
)

__all__ = [
    "locations_repo",
    "maps_repo",
    "pending_requests_repo",
    "robot_registrations_repo",
    "robots_repo",
    "tasks_repo",
    "users_repo",
]
