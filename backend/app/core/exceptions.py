"""Domain exceptions mapped to HTTP responses by the API layer.

Services never import FastAPI; they raise these instead.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, user-facing failures."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationError(AppError):
    status_code = 400
    code = "invalid_request"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class RobotNotConnectedError(NotFoundError):
    code = "robot_not_connected"

    def __init__(self, robot_id: str) -> None:
        super().__init__(f"Robot '{robot_id}' is not connected")


class RosUnavailableError(AppError):
    status_code = 503
    code = "ros_unavailable"

    def __init__(self, message: str = "ROS 2 runtime is not available on this host") -> None:
        super().__init__(message)
