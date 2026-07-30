"""Listener for `/robot/register` announcements from field robots."""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.models import RobotStatusEnum
from app.db.repositories import robots as robot_repo
from app.db.session import session_scope
from app.ros.runtime import RosModules

logger = get_logger(__name__)

MAC_RE = re.compile(r"^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$")


def build_registration_listener_class(ros: RosModules):
    class RegistrationListener(ros.Node):  # type: ignore[misc, valid-type]
        """Robots publish `std_msgs/String` JSON on `/robot/register`:

            {"mac_address": "AA:BB:CC:DD:EE:FF", "hostname": "bot-01",
             "ip_address": "192.168.1.50"}

        Approved MACs are auto-reconnected; unknown ones become pending
        registrations that an operator approves in the Robots panel.
        """

        def __init__(self, on_approved: Optional[Callable[[str], None]] = None) -> None:
            super().__init__("registration_listener")
            self._on_approved = on_approved
            self.create_subscription(ros.String, settings.registration_topic, self._on_message, 10)
            self._response_pub = self.create_publisher(
                ros.String, settings.registration_response_topic, 10
            )
            logger.info("Registration listener active on %s", settings.registration_topic)

        def _respond(self, payload: dict) -> None:
            msg = ros.String()
            msg.data = json.dumps(payload)
            self._response_pub.publish(msg)

        def _on_message(self, msg) -> None:
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError):
                logger.error("Invalid JSON on %s: %r", settings.registration_topic, msg.data)
                return

            mac = str(data.get("mac_address", "")).strip().upper()
            if not MAC_RE.match(mac):
                logger.warning("Registration ignored, bad MAC: %r", data.get("mac_address"))
                return

            hostname = data.get("hostname")
            ip_address = data.get("ip_address")
            logger.info("Registration request MAC=%s host=%s ip=%s", mac, hostname, ip_address)

            try:
                with session_scope() as db:
                    robot = robot_repo.get_robot_by_mac(db, mac)
                    if robot and robot.approved and not robot.is_deleted:
                        robot_repo.upsert_robot(
                            db,
                            robot_id=robot.id,
                            hostname=hostname,
                            ip_address=ip_address,
                            status=RobotStatusEnum.online,
                        )
                        robot_id = robot.id
                    else:
                        robot_repo.upsert_pending_registration(db, mac, hostname, ip_address)
                        robot_id = None
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Registration handling failed for %s: %s", mac, exc)
                return

            if robot_id:
                self._respond(
                    {
                        "status": "approved",
                        "robot_id": robot_id,
                        "message": f"Welcome back! Registered as {robot_id}",
                    }
                )
                if self._on_approved:
                    try:
                        self._on_approved(robot_id)
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning("Could not start controller for %s: %s", robot_id, exc)
            else:
                self._respond(
                    {
                        "status": "pending",
                        "message": f"Registration submitted for MAC {mac}. Awaiting operator approval.",
                    }
                )

    return RegistrationListener
