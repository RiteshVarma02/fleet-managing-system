"""Listener for `/robot/register` announcements from field robots.

This node performs no I/O of its own: it validates the payload and delegates to
an injected `handle(mac, hostname, ip) -> dict` callable (see
`services.registration_service`), which owns the database work. That keeps
`rclpy` threads free of Mongo calls and keeps this file testable without a DB.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional

from app.core.logging_config import get_logger
from app.ros.runtime import RosModules, message_class, qos_profile
from app.ros.topics_registry import topic_registry

logger = get_logger(__name__)

MAC_RE = re.compile(r"^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$")

RegistrationHandler = Callable[[str, Optional[str], Optional[str]], Dict[str, Any]]


def build_registration_listener_class(ros: RosModules):
    class RegistrationListener(ros.Node):  # type: ignore[misc, valid-type]
        """Robots publish `std_msgs/String` JSON on `/robot/register`:

            {"mac_address": "AA:BB:CC:DD:EE:FF", "hostname": "bot-01",
             "ip_address": "192.168.1.50"}

        Approved MACs are auto-reconnected; unknown ones become pending
        registrations an administrator approves in the fleet dashboard.
        """

        def __init__(self, handle: RegistrationHandler) -> None:
            super().__init__("registration_listener")
            self._handle = handle
            request = topic_registry.fleet_topic("registration")
            response = topic_registry.fleet_topic("registration_response")
            self._topic_name = request["name"]
            self._response_cls = message_class(response["type"])
            self.create_subscription(
                message_class(request["type"]),
                request["name"],
                self._on_message,
                qos_profile(ros, request["qos"]),
            )
            self._response_pub = self.create_publisher(
                self._response_cls, response["name"], qos_profile(ros, response["qos"])
            )
            logger.info("Registration listener active on %s", request["name"])

        def _respond(self, payload: Dict[str, Any]) -> None:
            msg = self._response_cls()
            msg.data = json.dumps(payload, default=str)
            self._response_pub.publish(msg)

        def _on_message(self, msg: Any) -> None:
            try:
                data = json.loads(getattr(msg, "data", "") or "")
            except (json.JSONDecodeError, TypeError):
                logger.error("Invalid JSON on %s: %r", self._topic_name, msg.data)
                return
            if not isinstance(data, dict):
                return

            mac = str(data.get("mac_address", "")).strip().upper()
            if not MAC_RE.match(mac):
                logger.warning("Registration ignored, bad MAC: %r", data.get("mac_address"))
                return

            hostname = data.get("hostname")
            ip_address = data.get("ip_address")
            logger.info("Registration request MAC=%s host=%s ip=%s", mac, hostname, ip_address)

            try:
                result = self._handle(mac, hostname, ip_address)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Registration handling failed for %s: %s", mac, exc)
                return
            self._respond(result)

    return RegistrationListener
