"""Data-access layer for named map locations."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Location


def create_location(
    db: Session,
    *,
    name: str,
    x: float,
    y: float,
    theta: float = 0.0,
    map_name: Optional[str] = None,
) -> Location:
    location = Location(name=name, x=x, y=y, theta=theta, map_name=map_name)
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def get_location(db: Session, location_id: str) -> Optional[Location]:
    return db.get(Location, location_id)


def get_location_by_name(db: Session, name: str, map_name: Optional[str] = None) -> Optional[Location]:
    stmt = select(Location).where(Location.name == name, Location.map_name == map_name)
    return db.execute(stmt).scalar_one_or_none()


def list_locations(db: Session, map_name: Optional[str] = None) -> List[Location]:
    stmt = select(Location).order_by(Location.name)
    if map_name:
        stmt = stmt.where(Location.map_name == map_name)
    return list(db.execute(stmt).scalars())


def delete_location(db: Session, location_id: str) -> bool:
    location = db.get(Location, location_id)
    if location is None:
        return False
    db.delete(location)
    db.commit()
    return True
