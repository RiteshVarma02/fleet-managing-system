"""In-memory telemetry bus — the server's load-control valve.

ROS callbacks fire at 10-50 Hz per robot. They never touch MongoDB and never
touch a WebSocket: they update the latest snapshot in memory (O(1), lock-held
for microseconds). Two consumers drain it:

* `flush_loop`     — one bulk Mongo write per `telemetry_flush_interval_seconds`
                     for the whole fleet (1 round trip, not N x rate).
* `broadcast_loop` — one JSON frame per `telemetry_ws_interval_seconds` fanned
                     out to subscribed clients, replacing per-client polling.

Result: DB and network cost is O(flush rate), independent of the ROS rate and
of the number of connected operators.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.documents import utcnow
from app.db.mongo import get_database
from app.db.repositories import robots_repo

logger = get_logger(__name__)


class TelemetryBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Dict[str, Dict[str, Any]] = {}
        self._dirty: Set[str] = set()
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: List[asyncio.Task] = []
        # Injected at startup (robot_service.status_of) so the bus stays free
        # of service imports; every frame / flush carries the derived status.
        self._status_provider: Optional[Callable[[str], Any]] = None

    def set_status_provider(self, provider: Callable[[str], Any]) -> None:
        self._status_provider = provider

    def _status(self, robot_id: str) -> Optional[str]:
        if self._status_provider is None:
            return None
        try:
            value = self._status_provider(robot_id)
        except Exception:  # pragma: no cover - defensive
            return None
        return getattr(value, "value", value)

    # ------------------------------------------------------------------
    # producer side (ROS threads)
    # ------------------------------------------------------------------
    def publish(self, robot_id: str, **fields: Any) -> None:
        if not robot_id:
            return
        with self._lock:
            snapshot = self._latest.setdefault(robot_id, {"robot_id": robot_id})
            snapshot.update({k: v for k, v in fields.items() if v is not None})
            snapshot["at"] = utcnow()
            snapshot["monotonic"] = time.monotonic()
            self._dirty.add(robot_id)

    def snapshot(self, robot_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            snapshot = self._latest.get(robot_id)
            return dict(snapshot) if snapshot else None

    def fleet_snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(value) for value in self._latest.values()]

    def forget(self, robot_id: str) -> None:
        with self._lock:
            self._latest.pop(robot_id, None)
            self._dirty.discard(robot_id)

    def is_live(self, robot_id: str) -> bool:
        snapshot = self.snapshot(robot_id)
        if not snapshot:
            return False
        return (time.monotonic() - snapshot.get("monotonic", 0.0)) < settings.telemetry_stale_after_seconds

    def _take_dirty(self) -> List[Dict[str, Any]]:
        with self._lock:
            if not self._dirty:
                return []
            batch = [dict(self._latest[rid]) for rid in self._dirty if rid in self._latest]
            self._dirty.clear()
        for snap in batch:
            snap["status"] = self._status(str(snap.get("robot_id"))) or snap.get("status")
        return batch

    # ------------------------------------------------------------------
    # consumer side (event loop)
    # ------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._tasks = [
            asyncio.create_task(self._flush_loop(), name="telemetry-flush"),
            asyncio.create_task(self._broadcast_loop(), name="telemetry-broadcast"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        await self._flush_once()

    async def _flush_once(self) -> None:
        batch = self._take_dirty()
        if not batch:
            return
        try:
            await robots_repo.bulk_apply_telemetry(get_database(), batch)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Telemetry flush failed for %d robot(s): %s", len(batch), exc)

    async def _flush_loop(self) -> None:
        interval = max(0.5, settings.telemetry_flush_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            await self._flush_once()

    async def _broadcast_loop(self) -> None:
        interval = max(0.1, settings.telemetry_ws_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            if not self._subscribers:
                continue
            frame = json.dumps(
                {
                    "type": "telemetry",
                    "robots": [
                        {
                            "robot_id": snap.get("robot_id"),
                            "position": snap.get("position"),
                            "battery": snap.get("battery"),
                            "status": self._status(str(snap.get("robot_id")))
                            or snap.get("status"),
                            "nav": snap.get("nav"),
                            "stop_active": bool(snap.get("stop_active")),
                            "emergency_active": bool(snap.get("emergency_active")),
                            "at": snap.get("at"),
                        }
                        for snap in self.fleet_snapshot()
                    ],
                },
                default=str,
            )
            for queue in list(self._subscribers):
                # Latest-value semantics: a slow client never blocks the loop.
                if queue.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(frame)


telemetry_bus = TelemetryBus()
