"""Global `/map` publisher fed by map images loaded through the API."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.logging_config import get_logger
from app.ros.runtime import RosModules

logger = get_logger(__name__)


class MapPublisher:
    """Owns the latched-ish `/map` republish loop.

    A single background thread re-stamps and republishes the cached
    OccupancyGrid so late-joining subscribers receive the current map.
    """

    def __init__(self, ros: RosModules, node: Any) -> None:
        self._ros = ros
        self._node = node
        self._publisher = node.create_publisher(ros.OccupancyGrid, settings.map_topic, 10)
        self._grid: Optional[Any] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def set_grid(self, grid: Any) -> None:
        with self._lock:
            self._grid = grid
        self.start()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="map-publisher", daemon=True)
        self._thread.start()
        logger.info("Map publisher loop started on %s", settings.map_topic)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _loop(self) -> None:
        interval = settings.map_publish_interval_seconds
        while not self._stop.wait(interval):
            try:
                with self._lock:
                    grid = self._grid
                if grid is None:
                    continue
                grid.header.stamp = self._node.get_clock().now().to_msg()
                self._publisher.publish(grid)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Map publish failed: %s", exc)
                time.sleep(interval)


def build_occupancy_grid(ros: RosModules, image_gray, resolution: float, origin_x: float, origin_y: float):
    """Convert a grayscale PIL image into a nav_msgs/OccupancyGrid.

    Vectorised with numpy — the naive per-pixel Python loop is O(n) round
    trips and takes seconds on a real 4000x4000 map.
    """
    import numpy as np

    arr = np.asarray(image_gray, dtype=np.uint8)
    # ROS occupancy grids are row-major starting at the bottom-left corner,
    # while image row 0 is the top row.
    arr = np.flipud(arr)
    height, width = arr.shape

    occupancy = np.full(arr.shape, -1, dtype=np.int8)
    occupancy[arr > 250] = 0
    occupancy[arr < 5] = 100

    grid = ros.OccupancyGrid()
    grid.header.frame_id = "map"
    grid.info.resolution = float(resolution)
    grid.info.width = int(width)
    grid.info.height = int(height)
    grid.info.origin.position.x = float(origin_x)
    grid.info.origin.position.y = float(origin_y)
    grid.info.origin.position.z = 0.0
    grid.info.origin.orientation.w = 1.0
    grid.data = occupancy.flatten().tolist()
    return grid
