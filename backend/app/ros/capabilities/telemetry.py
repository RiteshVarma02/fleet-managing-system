"""Battery, lidar and per-robot map — the sensor data almost every robot has."""

from __future__ import annotations

from typing import Any, Dict, Optional


class TelemetryCapability:
    name = "telemetry"

    def setup_telemetry(self) -> None:
        self.subscribe("battery_state", self._ros.BatteryState, self._on_battery, qos=10)
        # Lidar and map are high-bandwidth: keep the queue at 1, best effort.
        self.subscribe("scan", self._ros.LaserScan, self._on_scan, qos=1, best_effort=True)
        self.subscribe("map", self._ros.OccupancyGrid, self._on_map, qos=1)
        self.battery_percentage = 100.0
        self.current_scan: Optional[Any] = None
        self.current_map: Optional[Any] = None

    def _on_battery(self, msg: Any) -> None:
        percentage = float(getattr(msg, "percentage", 0.0) or 0.0)
        # ROS publishes 0..1; tolerate drivers that already send 0..100.
        if percentage <= 1.0:
            percentage *= 100.0
        percentage = max(0.0, min(100.0, percentage))
        with self._state_lock:
            self.battery_percentage = percentage
        self.report_telemetry(battery=percentage)

    def _on_scan(self, msg: Any) -> None:
        # Kept as the latest sample only — never buffered, never persisted.
        self.current_scan = msg

    def _on_map(self, msg: Any) -> None:
        self.current_map = msg

    def telemetry_snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return {"battery": self.battery_percentage}

    def latest_map(self) -> Optional[Any]:
        return self.current_map
