"""Robot lifecycle, teleop, capability commands and registration endpoints.

Reads never hit MongoDB for live values: `robot_service` merges the stored
document with the in-memory controller/telemetry-bus snapshot, so the fleet
list and the operator console cost one query and zero per-robot I/O.
"""

from __future__ import annotations

import re
from contextlib import suppress
from typing import List, Optional

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import Principal, get_current_user, get_db, require_admin, require_operator
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.documents import RegistrationStatus, RobotStatus
from app.db.repositories import robot_registrations_repo, robots_repo
from app.ros.manager import ros_manager
from app.ros.topics_registry import (
    capabilities_for,
    default_robot_type,
    is_known_type,
    is_valid_robot_id,
    robot_types as list_robot_types,
    type_spec,
)
from app.schemas.common import DataResponse, Position, StatusResponse, Velocity
from app.schemas.robot import (
    DockCommand,
    ForkCommand,
    GripperCommand,
    MacAddressBody,
    MoveCommand,
    PendingRegistrationOut,
    RobotApproveRequest,
    RobotCreateRequest,
    RobotIdBody,
    RobotOut,
    RobotRegisterRequest,
    RobotTelemetryOut,
    RobotTypeOut,
)
from app.services import robot_service
from app.services.task_service import task_engine

router = APIRouter(prefix="/robots", tags=["robots"])
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify_robot_id(name: str) -> str:
    """Display name -> ROS namespace ("Kumki 2" -> "kumki_2", "7bot" -> "r_7bot")."""
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_") or "robot"
    return slug if slug[0].isalpha() else f"r_{slug}"


def _resolve_robot_type(robot_type: Optional[str]) -> str:
    resolved = robot_type or default_robot_type()
    if not is_known_type(resolved):
        raise ValidationError(
            f"Unknown robot_type '{resolved}'. Defined in fleet_topics.yaml: {list_robot_types()}"
        )
    return resolved


def _robot_out(view: dict) -> RobotOut:
    return RobotOut.from_document(
        view["document"],
        connected=view["connected"],
        capabilities=view["capabilities"],
        live=view["live"],
        status=view["status"],
    )


# --------------------------------------------------------------------------
# Catalogue / introspection
# --------------------------------------------------------------------------
@router.get("/types", response_model=DataResponse[List[RobotTypeOut]])
def robot_types(_: Principal = Depends(get_current_user)):
    """Robot types from fleet_topics.yaml — drives the type picker in the UI."""
    out = []
    for name in list_robot_types():
        spec = type_spec(name)
        out.append(
            RobotTypeOut(
                name=name,
                description=spec["description"],
                capabilities=spec["capabilities"],
                extends=spec.get("extends"),
                topics={k: {"name": v["name"], "type": v["type"]} for k, v in spec["topics"].items()},
            )
        )
    return DataResponse(data=out)


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


@router.post("", response_model=DataResponse[RobotOut], status_code=201)
async def add_robot(
    body: RobotCreateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_admin),
):
    """Add a robot by its ROS namespace, without MAC registration."""
    robot_type = _resolve_robot_type(body.robot_type)
    existing = await robots_repo.get(db, body.robot_id, include_deleted=True)
    if existing and not existing.get("is_deleted"):
        raise ConflictError(f"Robot '{body.robot_id}' already exists")
    await robots_repo.upsert(
        db,
        body.robot_id,
        display_name=(body.name or body.robot_id).strip(),
        approved=True,
        status=RobotStatus.offline,
        robot_type=robot_type,
        is_deleted=False,
    )
    robot = await robots_repo.get(db, body.robot_id)
    if body.connect:
        _ok, _message, robot = await robot_service.connect(db, body.robot_id)
    return DataResponse(data=_robot_out(robot_service.view(robot)))


@router.post("/connect", response_model=DataResponse[RobotOut])
async def connect(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    """Start the controller with the robot's stored `robot_type` (topics from config)."""
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
    controller = ros_manager.get_controller(robot_id)
    return DataResponse(
        data=RobotTelemetryOut(
            robot_id=robot_id,
            connected=view["connected"],
            status=view["status"],
            position=Position(**{k: float(position.get(k, 0.0)) for k in ("x", "y", "theta")}),
            velocity=Velocity(
                linear=float(velocity.get("linear", 0.0)),
                angular=float(velocity.get("angular", 0.0)),
            ),
            battery=battery if battery is not None else robot.get("battery_percentage"),
            nav=live.get("nav"),
            dock_state=live.get("dock_state"),
            fork_height=live.get("fork_height"),
            arm_state=live.get("arm_state"),
            emergency_active=bool(live.get("emergency_active")),
            stop_active=bool(live.get("stop_active")),
            safety_hold=live.get("safety_hold"),
            capabilities=view["capabilities"],
            topics=controller.topic_map() if controller is not None else {},
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
def _refuse_during_estop(controller) -> None:
    """E-stop is absolute: teleop and every other motion command are refused."""
    hold = controller.safety_hold() if hasattr(controller, "safety_hold") else None
    if hold:
        raise ConflictError(f"Robot is stopped: {hold}", code="safety_hold")


@router.post("/move", response_model=StatusResponse)
def move(body: MoveCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "movement")
    _refuse_during_estop(controller)
    if not controller.move(body.linear, body.angular):
        raise ConflictError("Robot cannot move right now", code="safety_hold")
    return StatusResponse(message="Command sent")


@router.post("/stop", response_model=StatusResponse)
def stop(body: RobotIdBody, _: Principal = Depends(require_operator)):
    robot_service.require_controller(body.robot_id, "movement").stop()
    return StatusResponse(message="Robot stopped")


@router.post("/emergency-stop", response_model=StatusResponse)
async def emergency_stop(
    body: RobotIdBody,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    """Stop the robot immediately and pause any running task.

    The task stays alive in a paused state so the operator can release the
    emergency stop and *resume* — the robot continues from where it stopped
    instead of restarting the mission.
    """
    await _engage_emergency(db, body.robot_id)
    return StatusResponse(message=f"Emergency stop sent to {body.robot_id}")


@router.post("/emergency-stop-all", response_model=StatusResponse)
async def emergency_stop_all(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: Principal = Depends(require_operator),
):
    count = 0
    for robot_id in ros_manager.connected_robot_ids():
        await _engage_emergency(db, robot_id)
        count += 1
    return StatusResponse(message=f"Emergency stop sent to {count} robot(s)")


@router.post("/emergency-release", response_model=StatusResponse)
def emergency_release(body: RobotIdBody, _: Principal = Depends(require_operator)):
    """Release the SOFTWARE E-stop. The mission stays paused until resumed.

    A physical E-stop (`stop_active`) can only be released on the robot.
    """
    controller = ros_manager.get_controller(body.robot_id)
    if controller is not None and controller.has_capability("emergency"):
        controller.publish_emergency(False)
    else:
        ros_manager.publish_emergency(body.robot_id, False)
    return StatusResponse(message=f"Emergency released for {body.robot_id}")


async def _engage_emergency(db, robot_id: str) -> None:
    """Software E-stop: halt the robot and pause (not fail) its mission."""
    controller = ros_manager.get_controller(robot_id)
    if controller is not None and controller.has_capability("emergency"):
        controller.publish_emergency(True)
    else:
        ros_manager.publish_emergency(robot_id, True)
    task_id = task_engine.running_task_id(robot_id)
    if task_id is not None:
        with suppress(Exception):
            await task_engine.pause_task(db, task_id, reason="Software E-stop engaged")


# --------------------------------------------------------------------------
# Capability commands (only for robot types that declare them)
# --------------------------------------------------------------------------
@router.post("/dock", response_model=StatusResponse)
def dock(body: DockCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "docking")
    _refuse_during_estop(controller)
    ok = controller.dock() if body.command == "dock" else controller.undock()
    if not ok:
        raise ConflictError("Dock command could not be published")
    return StatusResponse(message=f"{body.command} command sent")


@router.post("/fork", response_model=DataResponse[dict])
def fork(body: ForkCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "fork_control")
    _refuse_during_estop(controller)
    commanded = controller.set_fork_height(body.height)
    return DataResponse(data={"commanded_height": commanded})


@router.post("/gripper", response_model=StatusResponse)
def gripper(body: GripperCommand, _: Principal = Depends(require_operator)):
    controller = robot_service.require_controller(body.robot_id, "arm_control")
    _refuse_during_estop(controller)
    if not controller.send_gripper_command(body.command):
        raise ConflictError("Gripper command could not be published")
    return StatusResponse(message=f"Gripper {body.command} sent")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
@router.post("/register", response_model=DataResponse[dict])
async def register(body: RobotRegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Called by the robot itself over HTTP; intentionally unauthenticated.

    An unknown MAC only creates a *pending* row — an admin must approve it
    before the robot gets an identity (= its ROS namespace) and a controller.
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

    robot_type = _resolve_robot_type(body.robot_type)

    resolved_id = (body.robot_id or _slugify_robot_id(custom_name)).strip()
    if not is_valid_robot_id(resolved_id):
        raise ValidationError(f"'{resolved_id}' is not a valid ROS namespace")
    existing = await robots_repo.get(db, resolved_id, include_deleted=True)
    if existing and existing.get("mac_address") and existing.get("mac_address") != body.mac_address:
        raise ConflictError(f"Robot id '{resolved_id}' is already used by another robot")

    # Re-approving a robot whose MAC is already known: a soft-deleted robot is
    # resurrected under its stable id instead of tripping the MAC unique index;
    # a live one is rejected as already registered.
    existing_by_mac = await robots_repo.get_by_mac(db, body.mac_address)
    if existing_by_mac:
        if not bool(existing_by_mac.get("is_deleted")):
            raise ConflictError(
                f"MAC {body.mac_address} is already registered as robot '{existing_by_mac.get('robot_id')}'"
            )
        resolved_id = str(existing_by_mac["robot_id"])

    await robots_repo.upsert(
        db,
        resolved_id,
        display_name=custom_name,
        approved=True,
        status=RobotStatus.offline,
        mac_address=body.mac_address,
        robot_type=robot_type,
        is_deleted=False,
    )
    await robot_registrations_repo.set_status(db, body.mac_address, RegistrationStatus.approved)

    started, message, _robot = await robot_service.connect(db, resolved_id)

    return DataResponse(
        data={
            "robot_id": resolved_id,
            "name": custom_name,
            "robot_type": robot_type,
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
