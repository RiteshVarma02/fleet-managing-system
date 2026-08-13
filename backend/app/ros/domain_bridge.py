"""Cross-domain transport via `ros2 run domain_bridge domain_bridge`.

Each robot runs on its own `ROS_DOMAIN_ID`; the server runs on
`settings.ros_domain_id`. For every approved robot we generate a bridge config
from `topics_registry` (so a new robot model needs no bridge editing) and
supervise one `domain_bridge` process per robot — a crash on one robot's bridge
never takes the fleet down.

Actions are deliberately not bridged: `deploy/robot_action_forwarder.py` runs on
the robot domain and converts the bridged `goal_request` topic into a
`NavigateToPose` action goal, reporting back on `navigation_status`.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.core.config import settings
from app.core.logging_config import get_logger
from app.ros.topics_registry import DOWN, UP, resolve_topics

logger = get_logger(__name__)


def build_bridge_config(robot_id: str, robot_type: str, robot_domain: int) -> Dict[str, Any]:
    """Declarative `domain_bridge` config for one robot, derived from the registry."""
    server_domain = settings.ros_domain_id
    topics: Dict[str, Any] = {}

    for spec in resolve_topics(robot_type, robot_id).values():
        if spec["direction"] == UP:
            # Robot publishes on its local name; the server sees it namespaced.
            topics[spec["robot"].lstrip("/")] = {
                "type": spec["type"],
                "from_domain": robot_domain,
                "to_domain": server_domain,
                "remap": spec["server"],
            }
        elif spec["direction"] == DOWN:
            topics[spec["server"].lstrip("/")] = {
                "type": spec["type"],
                "from_domain": server_domain,
                "to_domain": robot_domain,
                "remap": spec["robot"],
            }
    return {"name": f"{robot_id}_bridge", "topics": topics}


def write_bridge_config(robot_id: str, robot_type: str, robot_domain: int) -> Path:
    config = build_bridge_config(robot_id, robot_type, robot_domain)
    path = settings.domain_bridge_config_dir / f"{robot_id}.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


class _BridgeProcess:
    """One supervised `domain_bridge` process."""

    def __init__(self, robot_id: str, config_path: Path) -> None:
        self.robot_id = robot_id
        self.config_path = config_path
        self.restarts = 0
        self._process: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._supervise, name=f"bridge-{robot_id}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def _spawn(self) -> subprocess.Popen:
        env = {**os.environ, "ROS_DOMAIN_ID": str(settings.ros_domain_id)}
        command = [*settings.domain_bridge_command, str(self.config_path)]
        logger.info("Starting domain bridge for %s: %s", self.robot_id, " ".join(command))
        return subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _supervise(self) -> None:
        while not self._stop.is_set():
            try:
                self._process = self._spawn()
            except Exception as exc:  # pragma: no cover - host dependent
                logger.error("Bridge spawn failed for %s: %s", self.robot_id, exc)
                return
            self._process.wait()
            if self._stop.is_set():
                return
            self.restarts += 1
            if self.restarts > settings.domain_bridge_max_restarts:
                logger.error(
                    "Domain bridge for %s exceeded %d restarts — giving up",
                    self.robot_id,
                    settings.domain_bridge_max_restarts,
                )
                return
            logger.warning(
                "Domain bridge for %s exited; restart %d in %.1fs",
                self.robot_id,
                self.restarts,
                settings.domain_bridge_restart_backoff_seconds,
            )
            time.sleep(settings.domain_bridge_restart_backoff_seconds)

    @property
    def running(self) -> bool:
        return bool(self._process and self._process.poll() is None)

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
            process.wait(timeout=5)
        except Exception:  # pragma: no cover - best effort
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                pass


class DomainBridgeManager:
    """Registry of per-robot bridges. Idempotent and thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bridges: Dict[str, _BridgeProcess] = {}

    @property
    def available(self) -> bool:
        return (
            settings.domain_bridge_enabled
            and shutil.which(settings.domain_bridge_command[0]) is not None
        )

    def ensure(self, robot_id: str, robot_type: str, robot_domain: Optional[int]) -> Dict[str, Any]:
        domain = int(
            robot_domain if robot_domain is not None else settings.domain_bridge_default_robot_domain
        )
        config_path = write_bridge_config(robot_id, robot_type, domain)

        if domain == settings.ros_domain_id:
            return {
                "robot_id": robot_id,
                "running": False,
                "reason": "same domain as server — no bridge needed",
                "config_path": str(config_path),
            }
        if not self.available:
            return {
                "robot_id": robot_id,
                "running": False,
                "reason": "domain_bridge not installed or disabled",
                "config_path": str(config_path),
            }

        with self._lock:
            existing = self._bridges.get(robot_id)
            if existing and existing.running:
                return {"robot_id": robot_id, "running": True, "config_path": str(config_path)}
            if existing:
                existing.stop()
            bridge = _BridgeProcess(robot_id, config_path)
            self._bridges[robot_id] = bridge
        bridge.start()
        return {
            "robot_id": robot_id,
            "running": True,
            "domain": domain,
            "config_path": str(config_path),
        }

    def stop(self, robot_id: str) -> bool:
        with self._lock:
            bridge = self._bridges.pop(robot_id, None)
        if bridge is None:
            return False
        bridge.stop()
        return True

    def status(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "robot_id": robot_id,
                    "running": bridge.running,
                    "restarts": bridge.restarts,
                    "config_path": str(bridge.config_path),
                }
                for robot_id, bridge in self._bridges.items()
            ]

    def shutdown(self) -> None:
        with self._lock:
            bridges = list(self._bridges.values())
            self._bridges.clear()
        for bridge in bridges:
            bridge.stop()


domain_bridge_manager = DomainBridgeManager()
