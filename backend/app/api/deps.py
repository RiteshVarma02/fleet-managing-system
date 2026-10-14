"""Shared FastAPI dependencies: database handle and authenticated principal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_access_token
from app.db.documents import Role, role_rank
from app.db.mongo import get_database

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> AsyncIOMotorDatabase:
    """One pooled Motor client per process — nothing to open or close per call."""
    return get_database()


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    user_id: Optional[str] = None

    @property
    def rank(self) -> int:
        return role_rank(self.role)

    @property
    def is_developer(self) -> bool:
        return self.rank >= role_rank(Role.developer.value)

    @property
    def is_admin(self) -> bool:
        """Admins and developers."""
        return self.rank >= role_rank(Role.admin.value)

    @property
    def can_command(self) -> bool:
        """Operators, admins and developers. Unknown roles get nothing."""
        return self.rank >= role_rank(Role.operator.value)


def _principal_from_token(token: str) -> Principal:
    payload = decode_access_token(token)
    username = payload.get("sub")
    if not username:
        raise AuthError("Invalid token payload")
    return Principal(
        username=username,
        role=str(payload.get("role") or Role.operator.value),
        user_id=payload.get("uid"),
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthError("Missing bearer token")
    return _principal_from_token(credentials.credentials)


def require_developer(user: Principal = Depends(get_current_user)) -> Principal:
    if not user.is_developer:
        raise ForbiddenError("Developer privileges required")
    return user


def require_admin(user: Principal = Depends(get_current_user)) -> Principal:
    if not user.is_admin:
        raise ForbiddenError("Administrator privileges required")
    return user


def require_operator(user: Principal = Depends(get_current_user)) -> Principal:
    """Operators, admins and developers may command robots."""
    if not user.can_command:
        raise ForbiddenError("Operator privileges required")
    return user


def principal_from_websocket(websocket: WebSocket) -> Optional[Principal]:
    """Browsers cannot set headers on a WebSocket — accept `?token=` too."""
    header = websocket.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    token = token or (websocket.query_params.get("token") or "")
    if not token:
        return None
    try:
        return _principal_from_token(token)
    except AuthError:
        return None


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
