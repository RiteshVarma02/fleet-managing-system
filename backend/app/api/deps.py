"""Shared FastAPI dependencies: DB session and authenticated principal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_access_token
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Depends(get_db)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthError("Missing bearer token")
    payload = decode_access_token(credentials.credentials)
    username = payload.get("sub")
    if not username:
        raise AuthError("Invalid token payload")
    return Principal(username=username, role=payload.get("role", "operator"))


def require_admin(user: Principal = Depends(get_current_user)) -> Principal:
    if not user.is_admin:
        raise ForbiddenError("Administrator privileges required")
    return user


def get_db_session(db: Session = Depends(get_db)) -> Session:
    return db


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
