"""Robot lifecycle, teleop and registration endpoints."""

from __future__ import annotations

import re
from typing import List

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_admin
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.documents import RegistrationStatus, RobotStatus
from app.db.repositories import robot_registrations_repo, robots_repo
from app.ros.manager import ros_manager
from app.schemas.common import DataResponse, StatusResponse
from app.schemas.robot import (
    MacAddressBody,
    MoveCommand,
    PendingRegistrationOut,
    RobotApproveRequest,
    RobotIdBody,
    RobotOut,
    RobotRegisterRequest,
)

router = APIRouter(prefix="/robots", tags=["robots"])
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify_robot_id(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "robot"


@router.get("", response_model=DataResponse[List[RobotOut]])
async def list_robots(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await robots_repo.list_all(db)
    robots = []
    for row in rows:
        robot_id = str(row.get("robot_id") or "")
        controller = ros_manager.get_controller(robot_id)
        live = controller.snapshot() if controller is not None else None
        robots.append(
            RobotOut.from_document(
                row,
                connected=controller is not None,
                live=live,
            )
        )
    return DataResponse(data=robots)


@router.post("/connect", response_model=DataResponse[RobotOut])
async def connect(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    ok, message = ros_manager.start_controller(body.robot_id)
    status = RobotStatus.online if ok else RobotStatus.error
    robot = await robots_repo.upsert(
        db,
        body.robot_id,
        display_name=body.robot_id,
        approved=True,
        status=status,
    )
    if not ok:
        raise ConflictError(message, code="controller_start_failed")
    return DataResponse(data=RobotOut.from_document(robot, connected=True))


@router.post("/disconnect", response_model=DataResponse[RobotOut])
async def disconnect(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    ros_manager.stop_controller(body.robot_id)
    robot = await robots_repo.upsert(db, body.robot_id, status=RobotStatus.offline)
    return DataResponse(data=RobotOut.from_document(robot, connected=False))


@router.post("/move", response_model=StatusResponse)
def move(body: MoveCommand, _: Principal = Depends(get_current_user)):
    controller = ros_manager.get_controller(body.robot_id)
    if controller is None:
        raise NotFoundError(f"Robot '{body.robot_id}' is not connected")
    controller.move(body.linear, body.angular)
    return StatusResponse(message="Command sent")


@router.post("/stop", response_model=StatusResponse)
def stop(body: RobotIdBody, _: Principal = Depends(get_current_user)):
    controller = ros_manager.get_controller(body.robot_id)
    if controller is None:
        raise NotFoundError(f"Robot '{body.robot_id}' is not connected")
    controller.move(0.0, 0.0)
    return StatusResponse(message="Robot stopped")


@router.post("/emergency-stop", response_model=StatusResponse)
def emergency_stop(body: RobotIdBody, _: Principal = Depends(get_current_user)):
    ros_manager.publish_emergency(body.robot_id, True)
    return StatusResponse(message=f"Emergency stop sent to {body.robot_id}")


@router.post("/emergency-stop-all", response_model=StatusResponse)
def emergency_stop_all(_: Principal = Depends(get_current_user)):
    count = 0
    for robot_id in ros_manager.connected_robot_ids():
        ros_manager.publish_emergency(robot_id, True)
        count += 1
    return StatusResponse(message=f"Emergency stop sent to {count} robot(s)")


@router.get("/{robot_id}/status", response_model=DataResponse[dict])
async def status(
    robot_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    controller = ros_manager.get_controller(robot_id)
    if controller is not None:
        snapshot = controller.snapshot()
        await robots_repo.upsert(
            db,
            robot_id,
            status=RobotStatus.online,
            last_position=snapshot["position"],
            battery_percentage=snapshot["battery"],
        )
        return DataResponse(
            data={
                "connected": True,
                "position": snapshot["position"],
                "velocity": snapshot["velocity"],
                "battery": snapshot["battery"],
                "nav": snapshot["nav"],
            }
        )

    robot = await robots_repo.get(db, robot_id)
    if robot is None:
        raise NotFoundError(f"Robot '{robot_id}' not found")
    position = robot.get("last_position") or {}
    return DataResponse(
        data={
            "connected": False,
            "position": {
                "x": float(position.get("x", 0.0)),
                "y": float(position.get("y", 0.0)),
                "theta": float(position.get("theta", 0.0)),
            },
            "velocity": {"linear": 0.0, "angular": 0.0},
            "battery": float(robot.get("battery_percentage", 0.0)),
            "nav": None,
        }
    )


@router.delete("/{robot_id}", response_model=StatusResponse)
async def delete_robot(
    robot_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    ros_manager.stop_controller(robot_id)
    if not await robots_repo.soft_delete(db, robot_id):
        raise NotFoundError(f"Robot '{robot_id}' not found")
    return StatusResponse(message=f"Robot {robot_id} removed")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
@router.post("/register", response_model=DataResponse[dict])
async def register(body: RobotRegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Called by the robot itself over HTTP; intentionally unauthenticated.

    A registration only creates a *pending* row — an operator must approve it
    before the robot gets an identity or a controller.
    """
    robot = await robots_repo.get_by_mac(db, body.mac_address)
    if robot and bool(robot.get("approved")) and not bool(robot.get("is_deleted")):
        robot_id = str(robot["robot_id"])
        await robots_repo.upsert(
            db,
            robot_id,
            hostname=body.hostname,
            ip_address=body.ip_address,
            status=RobotStatus.online,
        )
        return DataResponse(
            data={
                "status": "approved",
                "robot_id": robot_id,
                "namespace": f"/{robot_id}",
                "message": f"Welcome back! Registered as {robot_id}",
            }
        )

    await robot_registrations_repo.check_in(db, body.mac_address, body.hostname, body.ip_address)
    return DataResponse(
        data={
            "status": "pending",
            "message": f"Registration submitted for MAC {body.mac_address}. Awaiting operator approval.",
        }
    )


@router.get("/registrations/pending", response_model=DataResponse[List[PendingRegistrationOut]])
async def pending(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    rows = await robot_registrations_repo.list_pending(db)
    return DataResponse(data=[PendingRegistrationOut.model_validate(row) for row in rows])


@router.post("/registrations/approve", response_model=DataResponse[dict])
async def approve(
    body: RobotApproveRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    custom_name = body.custom_name.strip()
    if not custom_name:
        raise ValidationError("custom_name is required")

    resolved_id = (body.robot_id or _slugify_robot_id(custom_name)).strip()
    existing = await robots_repo.get(db, resolved_id, include_deleted=True)
    if existing and existing.get("mac_address") and existing.get("mac_address") != body.mac_address:
        raise ConflictError(f"Robot id '{resolved_id}' is already used by another robot")

    domain_id = body.ros_domain_id
    if domain_id is None:
        domain_id = await robots_repo.next_domain_id(
            db,
            start=settings.domain_bridge_default_robot_domain,
        )

    await robots_repo.upsert(
        db,
        resolved_id,
        display_name=custom_name,
        approved=True,
        status=RobotStatus.offline,
        mac_address=body.mac_address,
        robot_type=body.robot_type,
        ros_domain_id=domain_id,
    )
    await robot_registrations_repo.set_status(db, body.mac_address, RegistrationStatus.approved)

    started, _message = ros_manager.start_controller(resolved_id)
    if started:
        await robots_repo.set_status(db, resolved_id, RobotStatus.online)

    return DataResponse(
        data={
            "robot_id": resolved_id,
            "name": custom_name,
            "namespace": f"/{resolved_id}",
            "controller_started": started,
            "message": f"Robot approved as {custom_name} ({resolved_id})",
        }
    )


@router.post("/registrations/reject", response_model=StatusResponse)
async def reject(
    body: MacAddressBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    row = await robot_registrations_repo.set_status(db, body.mac_address, RegistrationStatus.rejected)
    if row is None:
        raise NotFoundError("Pending registration not found")
    return StatusResponse(message=f"Registration {body.mac_address} rejected")
