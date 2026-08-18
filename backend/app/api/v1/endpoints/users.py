"""User administration (admin only) and self-service password change."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_admin
from app.core.exceptions import AuthError, ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password, verify_password
from app.db.repositories import users_repo
from app.schemas.auth import PasswordChange, UserCreate, UserOut, UserUpdate
from app.schemas.common import DataResponse, StatusResponse

router = APIRouter(prefix="/users", tags=["users"])


def _out(doc: dict) -> UserOut:
    return UserOut(
        id=str(doc.get("id")) if doc.get("id") else None,
        username=str(doc.get("username")),
        role=str(doc.get("role")),
        active=bool(doc.get("active", True)),
        last_login_at=doc.get("last_login_at"),
    )


@router.get("", response_model=DataResponse[List[UserOut]])
async def list_users(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    rows = await users_repo.list_all(db)
    return DataResponse(data=[_out(row) for row in rows])


@router.post("", response_model=DataResponse[UserOut], status_code=201)
async def create_user(
    body: UserCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    created = await users_repo.create(
        db, body.username, hash_password(body.password), body.role
    )
    if created is None:
        raise ConflictError(f"User '{body.username}' already exists", code="user_exists")
    return DataResponse(data=_out(created))


@router.patch("/{user_id}", response_model=DataResponse[UserOut])
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    fields: dict = {}
    if body.password:
        fields["password_hash"] = hash_password(body.password)
    if body.role is not None:
        fields["role"] = body.role.value
    if body.active is not None:
        fields["active"] = body.active
    if not fields:
        raise ValidationError("No changes supplied")

    updated = await users_repo.update(db, user_id, **fields)
    if updated is None:
        raise NotFoundError(f"User '{user_id}' not found")
    return DataResponse(data=_out(updated))


@router.post("/me/password", response_model=StatusResponse)
async def change_password(
    body: PasswordChange,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: Principal = Depends(get_current_user),
):
    doc = await users_repo.get_by_username(db, user.username)
    if doc is None:
        raise NotFoundError("User not found")
    if not verify_password(body.current_password, str(doc.get("password_hash") or "")):
        raise AuthError("Current password is incorrect")
    await users_repo.update(db, str(doc["id"]), password_hash=hash_password(body.new_password))
    return StatusResponse(message="Password updated")
