"""MongoDB repositories - the only layer that talks to the database."""

from app.db.repositories import (
    locations_repo,
    fleet_files_repo,
    pending_requests_repo,
    robot_registrations_repo,
    robots_repo,
    tasks_repo,
    users_repo,
)

# Backward-compatible aliases used across endpoints/services
locations = locations_repo
fleet_files = fleet_files_repo
pending_requests = pending_requests_repo
robot_registrations = robot_registrations_repo
robots = robots_repo
tasks = tasks_repo
users = users_repo

__all__ = [
    "locations_repo",
    "fleet_files_repo",
    "pending_requests_repo",
    "robot_registrations_repo",
    "robots_repo",
    "tasks_repo",
    "users_repo",
    "locations",
    "fleet_files",
    "pending_requests",
    "robot_registrations",
    "robots",
    "tasks",
    "users",
]