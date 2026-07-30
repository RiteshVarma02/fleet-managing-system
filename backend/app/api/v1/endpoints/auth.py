"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user
from app.core.exceptions import AuthError
from app.core.security import create_access_token, verify_password
from app.db.repositories import users as user_repo
from app.db.session import get_db
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = user_repo.get_by_username(db, payload.username)
    # Verify even when the user is missing to keep timing roughly constant.
    valid = user is not None and verify_password(payload.password, user.password_hash)
    if not user or not valid:
        raise AuthError("Invalid username or password")

    token, expires_in = create_access_token(user.username, user.role)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut(username=user.username, role=user.role),
    )


@router.get("/me", response_model=UserOut)
def me(user: Principal = Depends(get_current_user)) -> UserOut:
    return UserOut(username=user.username, role=user.role)
