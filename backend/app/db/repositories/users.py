"""Data-access layer for application users."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.models import User


def get_by_username(db: Session, username: str) -> Optional[User]:
    stmt = select(User).where(User.username == username)
    return db.execute(stmt).scalar_one_or_none()


def create_user(db: Session, *, username: str, password: str, role: str = "operator") -> User:
    user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_user(db: Session, *, username: str, password: str, role: str) -> User:
    existing = get_by_username(db, username)
    if existing:
        return existing
    return create_user(db, username=username, password=password, role=role)
