"""Fleet file sync: push the graph JSON / map to a robot and collect its ack.

* `file_update`  server -> robot (latched String carrying JSON)
* `file_ack`     robot -> server (String JSON), one per applied/rejected update

Protocol and payloads: `app/services/fleet_file_protocol.py`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class FleetFilesCapability:
    name = "fleet_files"

    def setup_fleet_files(self) -> None:
        self._file_update_pub = self.publisher("file_update")
        self._file_acks: Dict[str, Dict[str, Any]] = {}
        self.subscribe("file_ack", self._on_file_ack)

    def _on_file_ack(self, msg: Any) -> None:
        try:
            ack = json.loads(getattr(msg, "data", "") or "{}")
        except json.JSONDecodeError:
            logger.warning("%s: unreadable file_ack", self.robot_id)
            return
        kind = str(ack.get("kind") or "")
        if not kind:
            return
        with self._state_lock:
            self._file_acks[kind] = ack
        logger.info(
            "%s: file ack kind=%s version=%s ok=%s", self.robot_id, kind,
            ack.get("version"), ack.get("ok"),
        )

    def push_file_update(self, update: Dict[str, Any]) -> bool:
        """Publish an update envelope. False when the robot has no such topic."""
        if self._file_update_pub is None:
            return False
        msg = self.msg("file_update")
        msg.data = json.dumps(update)
        self._file_update_pub.publish(msg)
        return True

    def file_ack(self, kind: str) -> Optional[Dict[str, Any]]:
        with self._state_lock:
            ack = self._file_acks.get(kind)
            return dict(ack) if ack else None

    def fleet_files_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return {"file_acks": {k: dict(v) for k, v in self._file_acks.items()}}
