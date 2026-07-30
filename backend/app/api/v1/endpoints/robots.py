"""Robot lifecycle, teleop and registration endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_current_user, require_admin
from app.db.repositories import robots as robot_repo
from app.db.session import get_db
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
from app.services import robot_service

router = APIRouter(prefix="/robots", tags=["robots"])


@router.get("", response_model=DataResponse[List[RobotOut]])
def list_robots(db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    robots = [RobotOut.from_model(robot) for robot in robot_service.list_robots(db)]
    return DataResponse(data=robots)


@router.post("/connect", response_model=DataResponse[RobotOut])
def connect(body: RobotIdBody, db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    robot, _message = robot_service.connect(db, body.robot_id)
    return DataResponse(data=RobotOut.from_model(robot))


@router.post("/disconnect", response_model=DataResponse[RobotOut])
def disconnect(body: RobotIdBody, db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    robot, _message = robot_service.disconnect(db, body.robot_id)
    return DataResponse(data=RobotOut.from_model(robot))


@router.post("/move", response_model=StatusResponse)
def move(body: MoveCommand, _: Principal = Depends(get_current_user)):
    robot_service.move(body.robot_id, body.linear, body.angular)
    return StatusResponse(message="Command sent")


@router.post("/stop", response_model=StatusResponse)
def stop(body: RobotIdBody, _: Principal = Depends(get_current_user)):
    robot_service.move(body.robot_id, 0.0, 0.0)
    return StatusResponse(message="Robot stopped")


@router.post("/emergency-stop", response_model=StatusResponse)
def emergency_stop(body: RobotIdBody, _: Principal = Depends(get_current_user)):
    robot_service.emergency_stop(body.robot_id)
    return StatusResponse(message=f"Emergency stop sent to {body.robot_id}")


@router.post("/emergency-stop-all", response_model=StatusResponse)
def emergency_stop_all(_: Principal = Depends(get_current_user)):
    count = robot_service.emergency_stop_all()
    return StatusResponse(message=f"Emergency stop sent to {count} robot(s)")


@router.get("/{robot_id}/status", response_model=DataResponse[dict])
def status(robot_id: str, db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    return DataResponse(data=robot_service.get_status(db, robot_id))


@router.delete("/{robot_id}", response_model=StatusResponse)
def delete_robot(robot_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_admin)):
    robot_service.delete_robot(db, robot_id)
    return StatusResponse(message=f"Robot {robot_id} removed")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------
@router.post("/register", response_model=DataResponse[dict])
def register(body: RobotRegisterRequest, db: Session = Depends(get_db)):
    """Called by the robot itself over HTTP; intentionally unauthenticated.

    A registration only creates a *pending* row — an operator must approve it
    before the robot gets an identity or a controller.
    """
    return DataResponse(data=robot_service.register(db, body.mac_address, body.hostname, body.ip_address))


@router.get("/registrations/pending", response_model=DataResponse[List[PendingRegistrationOut]])
def pending(db: Session = Depends(get_db), _: Principal = Depends(get_current_user)):
    rows = robot_repo.list_pending_registrations(db)
    return DataResponse(data=[PendingRegistrationOut.model_validate(row) for row in rows])


@router.post("/registrations/approve", response_model=DataResponse[dict])
def approve(body: RobotApproveRequest, db: Session = Depends(get_db), _: Principal = Depends(require_admin)):
    return DataResponse(data=robot_service.approve(db, body.mac_address, body.custom_name, body.robot_id))


@router.post("/registrations/reject", response_model=StatusResponse)
def reject(body: MacAddressBody, db: Session = Depends(get_db), _: Principal = Depends(require_admin)):
    robot_service.reject(db, body.mac_address)
    return StatusResponse(message=f"Registration {body.mac_address} rejected")
