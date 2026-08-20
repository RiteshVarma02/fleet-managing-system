"""Robot lifecycle, teleop, capability commands and registration endpoints.

Reads never hit MongoDB for live values: `robot_service` merges the stored
document with the in-memory controller/telemetry-bus snapshot, so the fleet
list and the operator console cost one query and zero per-robot I/O.
"""

from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_admin, require_operator
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.documents import RegistrationStatus, RobotStatus
from app.db.repositories import robot_registrations_repo, robots_repo
from app.ros.manager import ros_manager
from app.ros.topics_registry import (
    DEFAULT_ROBOT_TYPE,
    ROBOT_TYPE_REGISTRY,
    capabilities_for,
    is_known_type,
)
from app.schemas.common import DataResponse, Position, StatusResponse, Velocity
from app.schemas.robot import (
    BridgeStatusOut,
    DockCommand,
    ForkCommand,
    GripperCommand,
    MacAddressBody,
    MoveCommand,
    PendingRegistrationOut,
    PoseCommand,
    RobotApproveRequest,
    RobotIdBody,
    RobotOut,
    RobotRegisterRequest,
    RobotTelemetryOut,
    RobotTypeOut,
)
from app.services import robot_service

router = APIRouter(prefix="/robots", tags=["robots"])
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify_robot_id(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return slug or "robot"


def _robot_out(view: dict) -> RobotOut:
    return RobotOut.from_document(
        view["document"],
        connected=view["connected"],
        capabilities=view["capabilities"],
        live=view["live"],
    )


# --------------------------------------------------------------------------
# Catalogue / introspection
# --------------------------------------------------------------------------
@router.get("/types", response_model=DataResponse[List[RobotTypeOut]])
def robot_types(_: Principal = Depends(get_current_user)):
    """Static registry — drives the robot-type picker during approval."""
    return DataResponse(
        data=[
            RobotTypeOut(
                name=name,
                description=str(spec.get("description") or ""),
                capabilities=list(spec.get("capabilities") or []),
            )
            for name, spec in sorted(ROBOT_TYPE_REGISTRY.items())
        ]
    )


@router.get("/bridges", response_model=DataResponse[List[BridgeStatusOut]])
def bridges(_: Principal = Depends(get_current_user)):
    return DataResponse(
        data=[BridgeStatusOut.model_validate(row) for row in ros_manager.bridge_status()]
    )


# --------------------------------------------------------------------------
# Fleet
# --------------------------------------------------------------------------
@router.get("", response_model=DataResponse[List[RobotOut]])
async def list_robots(
    approved_only: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    views = await robot_service.fleet_view(db, approved_only=approved_only)
    return DataResponse(data=[_robot_out(view) for view in views])


@router.post("/connect", response_model=DataResponse[RobotOut])
async def connect(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    """Uses the robot's stored `robot_type` and `ros_domain_id` for the bridge."""
    ok, message, robot = await robot_service.connect(db, body.robot_id)
    if not ok:
        raise ConflictError(message, code="controller_start_failed")
    return DataResponse(data=_robot_out(robot_service.view(robot)))


@router.post("/disconnect", response_model=DataResponse[RobotOut])
async def disconnect(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    robot = await robot_service.disconnect(db, body.robot_id)
    return DataResponse(data=_robot_out(robot_service.view(robot)))


@router.get("/{robot_id}/status", response_model=DataResponse[RobotTelemetryOut])
async def status(
    robot_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(get_current_user),
):
    robot = await robot_service.get_robot(db, robot_id)
    view = robot_service.view(robot)
    live = view["live"] or {}
    position = live.get("position") or robot.get("last_position") or {}
    velocity = live.get("velocity") or {}
    battery = live.get("battery")
    return DataResponse(
        data=RobotTelemetryOut(
            robot_id=robot_id,
            connected=view["connected"],
            position=Position(**{k: float(position.get(k, 0.0)) for k in ("x", "y", "theta")}),
            velocity=Velocity(
                linear=float(velocity.get("linear", 0.0)),
                angular=float(velocity.get("angular", 0.0)),
            ),
            battery=float(
                battery if battery is not None else robot.get("battery_percentage") or 0.0
            ),
            nav=live.get("nav"),
            dock_state=live.get("dock_state"),
            fork_height=live.get("fork_height"),
            arm_state=live.get("arm_state"),
            emergency_active=bool(live.get("emergency_active")),
            capabilities=view["capabilities"],
        )
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
# Teleoperation and emergency stop
# --------------------------------------------------------------------------
@router.post("/move", response_model=StatusResponse)
def move(body: MoveCommand, _: Principal = Depends(require_operator)):
    robot_service.require_controller(body.robot_id, "movement").move(body.linear, body.angular)
    return StatusResponse(message="Command sent")


@router.post("/stop", response_model=StatusResponse)
def stop(body: RobotIdBody, _: Principal = Depends(require_operator)):
    robot_service.require_controller(body.robot_id, "movement").stop()
    return StatusResponse(message="Robot stopped")


@router.post("/emergency-stop", response_model=StatusResponse)
def emergency_stop(body: RobotIdBody, _: Principal = Depends(require_operator)):
    ros_manager.publish_emergency(body.robot_id, True)
    return StatusResponse(message=f"Emergency stop sent to {body.robot_id}")


@router.post("/emergency-stop-all", response_model=StatusResponse)
def emergency_stop_all(_: Principal = Depends(require_operator)):
    count = 0
    for robot_id in ros_manager.connected_robot_ids():
        ros_manager.publish_emergency(robot_id, True)
        count += 1
    return StatusResponse(message=f"Emergency stop sent to {count} robot(s)")


# --------------------------------------------------------------------------
# Capability commands
# --------------------------------------------------------------------------
@router.post("/goal", response_model=DataResponse[dict])
def send_goal(body: PoseCommand, _: Principal = Depends(require_operator)):
    """Nav2 goal, published as a pose the robot-side action forwarder consumes."""
    controller = robot_service.require_controller(body.robot_id, "navigation")
    ok, detail = controller.send_nav2_goal(body.x, body.y, body.theta)
    if not ok:
        raise ValidationError(detail)
    return DataResponse(data={"message": detail, "nav": controller.get_nav_status()})


@router.post("/goal/cancel", response_model=StatusResponse)
def cancel_goal(body: RobotIdBody, _: Principal = Depends(require_operator)):
    robot_service.require_controller(body.robot_id, "navigation").cancel_nav_goal()
    return StatusResponse(message="Goal cancelled")


@router.post("/initial-pose", response_model=StatusResponse)
def initial_pose(body: PoseCommand, _: Principal = Depends(require_operator)):
    robot_service.require_controller(body.robot_id, "navigation").set_initial_pose(
        body.x, body.y, body.theta
    )
    return StatusResponse(message="Initial pose published")


@router.post("/dock", response_model=StatusResponse)
def dock(body: DockCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "docking")
    ok = controller.dock() if body.command == "dock" else controller.undock()
    if not ok:
        raise ConflictError("Dock command could not be published")
    return StatusResponse(message=f"{body.command} command sent")


@router.post("/fork", response_model=DataResponse[dict])
def fork(body: ForkCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "fork_control")
    commanded = controller.set_fork_height(body.height)
    return DataResponse(data={"commanded_height": commanded})


@router.post("/gripper", response_model=StatusResponse)
def gripper(body: GripperCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "arm_control")
    if not controller.send_gripper_command(body.command):
        raise ConflictError("Gripper command could not be published")
    return StatusResponse(message=f"Gripper {body.command} sent")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
@router.post("/register", response_model=DataResponse[dict])
async def register(body: RobotRegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Called by the robot itself over HTTP; intentionally unauthenticated.

    An unknown MAC only creates a *pending* row — an operator must approve it
    before the robot gets an identity, a domain bridge or a controller.
    """
    from app.services.registration_service import handle_registration

    result = await handle_registration(db, body.mac_address, body.hostname, body.ip_address)
    return DataResponse(data=result)


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

    robot_type: str = body.robot_type or DEFAULT_ROBOT_TYPE
    if not is_known_type(robot_type):
        raise ValidationError(f"Unknown robot_type '{robot_type}'")

    resolved_id = (body.robot_id or _slugify_robot_id(custom_name)).strip()
    existing = await robots_repo.get(db, resolved_id, include_deleted=True)
    if existing and existing.get("mac_address") and existing.get("mac_address") != body.mac_address:
        raise ConflictError(f"Robot id '{resolved_id}' is already used by another robot")

    # Re-approving a robot whose MAC is already known: a soft-deleted robot is
    # resurrected under its stable id/domain instead of tripping the MAC unique
    # index; a live one is rejected as already registered.
    existing_by_mac = await robots_repo.get_by_mac(db, body.mac_address)
    if existing_by_mac:
        if not bool(existing_by_mac.get("is_deleted")):
            raise ConflictError(
                f"MAC {body.mac_address} is already registered as robot '{existing_by_mac.get('robot_id')}'"
            )
        resolved_id = str(existing_by_mac["robot_id"])

    domain_id: Optional[int] = body.ros_domain_id
    if existing_by_mac is None and domain_id is None:
        domain_id = await robots_repo.next_domain_id(
            db, start=settings.domain_bridge_default_robot_domain
        )

    await robots_repo.upsert(
        db,
        resolved_id,
        display_name=custom_name,
        approved=True,
        status=RobotStatus.offline,
        mac_address=body.mac_address,
        robot_type=robot_type,
        ros_domain_id=domain_id,
        is_deleted=False,
    )
    await robot_registrations_repo.set_status(db, body.mac_address, RegistrationStatus.approved)

    # Uses the just-stored type/domain, so the bridge starts on the right domain.
    started, message, _robot = await robot_service.connect(db, resolved_id)

    return DataResponse(
        data={
            "robot_id": resolved_id,
            "name": custom_name,
            "robot_type": robot_type,
            "ros_domain_id": domain_id,
            "capabilities": capabilities_for(robot_type),
            "namespace": f"/{resolved_id}",
            "controller_started": started,
            "message": message if not started else f"Robot approved as {custom_name}",
        }
    )


@router.post("/registrations/reject", response_model=StatusResponse)
async def reject(
    body: MacAddressBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    row = await robot_registrations_repo.set_status(
        db, body.mac_address, RegistrationStatus.rejected
    )
    if row is None:
        raise NotFoundError("Pending registration not found")
    return StatusResponse(message=f"Registration {body.mac_address} rejected")
