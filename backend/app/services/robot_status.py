"""One definition of "what state is this robot in", used everywhere.

Pure function, no I/O: the WebSocket frame, `GET /robots`, the scheduler and
the Mongo write-behind all call `derive_status()` with the same inputs.

Order matters — the first matching rule wins:

    offline            controller not running, or nothing heard for too long
    stop_active        physical E-stop button pressed          (UI: red)
    e_stopped          software E-stop engaged                 (UI: red outline)
    awaiting_approval  step-mode mission waiting for a click   (UI: amber pulse)
    paused             mission paused (incl. after an E-stop)  (UI: amber)
    error              last leg failed / timed out             (UI: orange)
    moving             a waypoint leg is in progress           (UI: blue)
    idle               online and free                         (UI: green)
"""

from __future__ import annotations

from typing import Optional

from app.db.documents import RobotStatus

_MOVING_NAV = {"active"}
_ERROR_NAV = {"failed"}


def derive_status(
    *,
    connected: bool,
    seconds_since_seen: Optional[float],
    stale_after_seconds: float,
    stop_active: bool = False,
    emergency_active: bool = False,
    task_status: Optional[str] = None,
    nav_status: Optional[str] = None,
) -> RobotStatus:
    if not connected or seconds_since_seen is None or seconds_since_seen > stale_after_seconds:
        return RobotStatus.offline
    if stop_active:
        return RobotStatus.stop_active
    if emergency_active:
        return RobotStatus.e_stopped
    if task_status == "awaiting_approval":
        return RobotStatus.awaiting_approval
    if task_status == "paused" or nav_status == "paused":
        return RobotStatus.paused
    if nav_status in _ERROR_NAV:
        return RobotStatus.error
    if nav_status in _MOVING_NAV or task_status == "running":
        return RobotStatus.moving
    return RobotStatus.idle
