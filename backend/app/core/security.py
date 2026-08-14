"""Password hashing and JWT issuing/verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Tuple

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import AuthError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A constant hash used to keep login timing roughly equal for unknown users.
DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.k2Q0dK3o1u7pI3vJVc0eZbJb1YlOaJ2"


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed or DUMMY_HASH)
    except ValueError:
        return False


def create_access_token(subject: str, role: str, *, user_id: str | None = None) -> Tuple[str, int]:
    """Return `(token, expires_in_seconds)`."""
    ttl = timedelta(minutes=settings.jwt_expiry_minutes)
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "uid": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid authentication token") from exc
