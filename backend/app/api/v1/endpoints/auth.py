"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db
from app.core.exceptions import AuthError
from app.core.security import create_access_token, verify_password
from app.db.repositories import users_repo as user_repo
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> TokenResponse:
    user = await user_repo.get_by_username(db, payload.username)
    # Verify even when the user is missing to keep timing roughly constant.
    valid = user is not None and verify_password(payload.password, str(user.get("password_hash") or ""))
    if not user or not valid:
        raise AuthError("Invalid username or password")

    token, expires_in = create_access_token(
        str(user["username"]),
        str(user["role"]),
        user_id=str(user.get("id")) if user.get("id") else None,
    )
    if user.get("id"):
        await user_repo.touch_login(db, str(user["id"]))

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut(
            id=str(user.get("id")) if user.get("id") else None,
            username=str(user["username"]),
            role=str(user["role"]),
            active=bool(user.get("active", True)),
            last_login_at=user.get("last_login_at"),
        ),
    )


@router.get("/me", response_model=UserOut)
def me(user: Principal = Depends(get_current_user)) -> UserOut:
    return UserOut(username=user.username, role=user.role)
