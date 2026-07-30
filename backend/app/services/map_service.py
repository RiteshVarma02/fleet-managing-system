"""Map image handling, SLAM process control and map file listing."""

from __future__ import annotations

import base64
import io
import os
import shutil
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.ros.manager import ros_manager
from app.ros.map_publisher import build_occupancy_grid

logger = get_logger(__name__)

MAX_MAP_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {".pgm", ".png", ".jpg", ".jpeg", ".bmp"}


def _safe_path(directory: Path, name: str) -> Path:
    """Resolve `name` inside `directory`, refusing traversal."""
    candidate = (directory / name).resolve()
    root = directory.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValidationError("Invalid path")
    return candidate


class MapService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slam_process: Optional[subprocess.Popen] = None
        self._current_map: Optional[Dict[str, Any]] = None

    # ---------------- upload / publish ----------------
    def load_map(self, filename: str, content: bytes, resolution: float, origin_x: float,
                 origin_y: float) -> Dict[str, Any]:
        from PIL import Image  # local import: heavy and optional at import time

        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValidationError(f"Unsupported map format '{suffix}'")
        if not content:
            raise ValidationError("Empty file")
        if len(content) > MAX_MAP_BYTES:
            raise ValidationError("Map file too large (max 25 MB)")

        try:
            image = Image.open(io.BytesIO(content))
            image.load()
            image = image.convert("L")
        except Exception as exc:
            raise ValidationError(f"Could not decode image: {exc}") from exc

        stored = _safe_path(settings.maps_dir, Path(filename).name)
        stored.write_bytes(content)

        metadata = {
            "width": image.width,
            "height": image.height,
            "resolution": resolution,
            "origin_x": origin_x,
            "origin_y": origin_y,
        }

        published = False
        if ros_manager.available:
            try:
                grid = build_occupancy_grid(
                    ros_manager.require_ros(), image, resolution, origin_x, origin_y
                )
                ros_manager.publish_map(grid)
                published = True
            except Exception as exc:  # pragma: no cover - ROS runtime issues
                logger.error("Map publish failed: %s", exc)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        with self._lock:
            self._current_map = {
                "name": stored.name,
                "path": str(stored),
                "metadata": metadata,
                "image": encoded,
            }
        return {"metadata": metadata, "image": encoded, "published": published}

    def current_map(self) -> Dict[str, Any]:
        with self._lock:
            if self._current_map is None:
                raise NotFoundError("No map has been loaded yet")
            return dict(self._current_map)

    # ---------------- filesystem ----------------
    def list_maps(self) -> List[Dict[str, Any]]:
        maps: Dict[str, Dict[str, Any]] = {}
        for path in sorted(settings.maps_dir.glob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in ALLOWED_SUFFIXES and suffix != ".yaml":
                continue
            entry = maps.setdefault(
                path.stem,
                {"name": path.stem, "modified_at": "", "has_yaml": False, "has_image": False},
            )
            entry["modified_at"] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            if suffix == ".yaml":
                entry["has_yaml"] = True
            else:
                entry["has_image"] = True
        return list(maps.values())

    def delete_map(self, name: str) -> None:
        removed = False
        for suffix in ALLOWED_SUFFIXES | {".yaml"}:
            path = _safe_path(settings.maps_dir, f"{name}{suffix}")
            if path.exists():
                path.unlink()
                removed = True
        if not removed:
            raise NotFoundError(f"Map '{name}' not found")

    # ---------------- SLAM ----------------
    def start_slam(self, robot_id: str, map_name: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self._slam_process and self._slam_process.poll() is None:
                raise ConflictError("SLAM is already running")

            executable = settings.slam_launch_command[0]
            if shutil.which(executable) is None:
                raise ConflictError(f"'{executable}' is not available on this host")

            command = [*settings.slam_launch_command, f"namespace:={robot_id}"]
            logger.info("Starting SLAM: %s", " ".join(command))
            # start_new_session so we can signal the whole launch process group.
            self._slam_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {"pid": self._slam_process.pid, "map_name": map_name, "robot_id": robot_id}

    def stop_slam(self) -> bool:
        with self._lock:
            process = self._slam_process
            self._slam_process = None
        if process is None or process.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGINT)
            process.wait(timeout=10)
        except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):  # pragma: no cover
                pass
        return True

    def slam_running(self) -> bool:
        with self._lock:
            return bool(self._slam_process and self._slam_process.poll() is None)

    def save_map(self, filename: str) -> Dict[str, Any]:
        executable = settings.map_saver_command[0]
        if shutil.which(executable) is None:
            raise ConflictError(f"'{executable}' is not available on this host")

        target = _safe_path(settings.maps_dir, filename)
        command = [*settings.map_saver_command, "-f", str(target)]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.map_save_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConflictError("Map save timed out") from exc

        if result.returncode != 0:
            raise ConflictError(f"Map save failed: {result.stderr.strip()[:500]}")
        return {"filename": f"{target.name}.yaml", "path": f"{target}.yaml"}

    def shutdown(self) -> None:
        try:
            self.stop_slam()
        except Exception:  # pragma: no cover
            pass


map_service = MapService()
