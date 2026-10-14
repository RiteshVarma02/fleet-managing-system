"""Map-related schemas."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, field_validator


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-. ]{1,128}$")


def validate_map_name(value: Optional[str]) -> Optional[str]:
    """Reject path traversal and separators — these names hit the filesystem."""
    if value is None:
        return None
    value = value.strip()
    if not SAFE_NAME_RE.match(value) or ".." in value:
        raise ValueError("map name may only contain letters, digits, space, '.', '-' and '_'")
    return value


class MapNameBody(BaseModel):
    map_name: str

    _v = field_validator("map_name")(validate_map_name)


class MapMetadata(BaseModel):
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float


class MapImageResponse(BaseModel):
    status: str = "success"
    image: str = ""
    metadata: MapMetadata


class MapSummary(BaseModel):
    name: str
    modified_at: str
    has_yaml: bool
    has_image: bool
    active: bool = False
