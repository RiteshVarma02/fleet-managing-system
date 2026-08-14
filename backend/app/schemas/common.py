"""Shared response envelopes and primitives."""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class StatusResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None


class DataResponse(BaseModel, Generic[T]):
    status: str = "success"
    data: T


class Position(BaseModel):
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0


class Velocity(BaseModel):
    linear: float = 0.0
    angular: float = 0.0
