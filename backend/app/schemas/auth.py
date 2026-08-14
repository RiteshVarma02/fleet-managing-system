"""Auth request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.db.documents import Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    id: Optional[str] = None
    username: str
    role: str
    active: bool = True
    last_login_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    status: str = "success"
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.operator

    @field_validator("username")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=256)
    role: Optional[Role] = None
    active: Optional[bool] = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)
