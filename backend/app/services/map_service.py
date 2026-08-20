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
from app.db.repositories import map_state_repo, maps_repo
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


def _map_yaml(name: str, metadata: Dict[str, Any]) -> str:
    """nav2_map_server `*.yaml` companion for a saved `.pgm` map file."""
    return (
        f"image: {name}.pgm\n"
        f"resolution: {metadata['resolution']}\n"
        f"origin: [{metadata['origin_x']}, {metadata['origin_y']}, 0.0]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.196\n"
    )


class MapService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slam_process: Optional[subprocess.Popen] = None
        self._current_map: Optional[Dict[str, Any]] = None
        self._active_name: Optional[str] = None

    # ---------------- upload / publish ----------------
    async def load_map(self, db, filename: str, content: bytes, resolution: float,
                       origin_x: float, origin_y: float) -> Dict[str, Any]:
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

        # Persist the metadata so the map can be reactivated later; the raster
        # itself stays on disk. The upload immediately becomes the active map.
        await maps_repo.upsert(
            db,
            name=stored.stem,
            metadata=metadata,
            source="upload",
            file_path=str(stored),
        )
        result = self._publish_and_cache(stored.stem, image, metadata, stored)
        await map_state_repo.set(
            db, name=stored.stem, metadata=metadata, source="upload"
        )
        return result

    async def activate_map(self, db, name: str) -> Dict[str, Any]:
        """Load a saved map from disk and make it the active fleet map."""
        image_path = self._find_image(settings.maps_dir, name)
        if image_path is None:
            raise NotFoundError(f"Map '{name}' has no image on disk")

        from PIL import Image  # local import: heavy and optional at import time

        try:
            image = Image.open(image_path)
            image.load()
            image = image.convert("L")
        except Exception as exc:
            raise ValidationError(f"Could not decode map '{name}': {exc}") from exc

        metadata = await self._metadata_for(db, name, image)
        result = self._publish_and_cache(name, image, metadata, image_path)
        await map_state_repo.set(db, name=name, metadata=metadata, source="activate")
        logger.info("Activated map '%s' (resolution=%.3f, origin=(%.2f, %.2f))",
                    name, metadata["resolution"], metadata["origin_x"], metadata["origin_y"])
        return result

    async def promote_robot_map(self, db, robot_id: str, map_name: Optional[str] = None) -> Dict[str, Any]:
        """Make a robot's own SLAM grid the active fleet map.

        The grid is captured straight from the controller's telemetry
        (no map_saver_cli involved), saved as a PNG on disk, published to ROS
        and recorded as the active map with `source="robot"`.
        """
        from app.services.robot_service import latest_map

        grid = latest_map(robot_id)
        if grid is None:
            raise NotFoundError(f"Robot '{robot_id}' has no map yet")

        from app.ros.map_publisher import occupancy_grid_to_image

        image, metadata = occupancy_grid_to_image(grid)
        name = (map_name or f"{robot_id}_map").strip()
        target = _safe_path(settings.maps_dir, f"{name}.png")
        image.save(target, format="PNG")

        result = self._publish_and_cache(name, image, metadata, target)
        await maps_repo.upsert(
            db,
            name=name,
            metadata=metadata,
            source="robot",
            file_path=str(target),
        )
        await map_state_repo.set(
            db, name=name, metadata=metadata, source="robot", robot_id=robot_id
        )
        logger.info("Promoted robot map for %s as '%s'", robot_id, name)
        return result

    async def save_from_robot(self, db, robot_id: str, filename: str) -> Dict[str, Any]:
        """Persist a robot's captured grid as a .pgm/.yaml/.png map set.

        Written straight from the controller's OccupancyGrid — this is the
        build-map flow, so `map_saver_cli` is not involved. Unlike promote, this
        only saves the files: activation is an explicit follow-up step.
        """
        from app.services.robot_service import latest_map

        grid = latest_map(robot_id)
        if grid is None:
            raise NotFoundError(f"Robot '{robot_id}' has no map yet")

        from app.ros.map_publisher import occupancy_grid_to_image

        image, metadata = occupancy_grid_to_image(grid)
        name = Path(filename).stem
        base = _safe_path(settings.maps_dir, f"{name}.pgm")

        pgm_buffer = io.BytesIO()
        image.save(pgm_buffer, format="PPM")  # P5 binary PGM for mode "L"
        base.write_bytes(pgm_buffer.getvalue())

        png_buffer = io.BytesIO()
        image.save(png_buffer, format="PNG")
        png_path = base.with_suffix(".png")
        png_path.write_bytes(png_buffer.getvalue())
        encoded = base64.b64encode(png_buffer.getvalue()).decode("ascii")

        base.with_suffix(".yaml").write_text(_map_yaml(name, metadata), encoding="utf-8")

        await maps_repo.upsert(
            db,
            name=name,
            metadata=metadata,
            source="robot",
            file_path=str(png_path),
            image_base64=encoded,
        )
        logger.info("Saved map from robot %s as '%s'", robot_id, name)
        return {"name": name, "metadata": dict(metadata), "image": encoded}

    async def restore_active_map(self, db) -> Optional[Dict[str, Any]]:
        """Startup restore: republish the persisted active map (best effort)."""
        state = await map_state_repo.get(db)
        if state is None:
            return None
        name = str(state.get("name") or "")
        if not name:
            return None
        metadata = dict(state.get("metadata") or {})
        image_path = self._find_image(settings.maps_dir, name)
        if image_path is None:
            logger.warning("Active map '%s' is missing from disk; skipping restore", name)
            return None

        from PIL import Image  # local import

        try:
            image = Image.open(image_path)
            image.load()
            image = image.convert("L")
        except Exception as exc:
            logger.warning("Could not restore active map '%s': %s", name, exc)
            return None

        # Guard against a stale pointer doc lacking the full metadata block.
        for key, fallback in (("resolution", 0.05), ("origin_x", 0.0), ("origin_y", 0.0)):
            metadata.setdefault(key, fallback)
        metadata.setdefault("width", image.width)
        metadata.setdefault("height", image.height)

        result = self._publish_and_cache(name, image, metadata, image_path)
        logger.info("Restored active map '%s' from disk", name)
        return result

    def _publish_and_cache(self, name: str, image: Any, metadata: Dict[str, Any],
                           path: Path) -> Dict[str, Any]:
        """Build the grid, publish it and cache the PNG + metadata in memory."""
        published = False
        if ros_manager.available:
            try:
                grid = build_occupancy_grid(
                    ros_manager.require_ros(),
                    image,
                    metadata["resolution"],
                    metadata["origin_x"],
                    metadata["origin_y"],
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
                "name": name,
                "path": str(path),
                "metadata": dict(metadata),
                "image": encoded,
            }
            self._active_name = name
        return {"metadata": dict(metadata), "image": encoded, "published": published}

    async def _metadata_for(self, db, name: str, image: Any) -> Dict[str, Any]:
        """Metadata for a saved map: Mongo first, then derive from the image."""
        doc = await maps_repo.get_by_name(db, name, with_image=False)
        if doc and doc.get("metadata"):
            return dict(doc["metadata"])
        return {
            "width": image.width,
            "height": image.height,
            "resolution": 0.05,
            "origin_x": 0.0,
            "origin_y": 0.0,
        }

    def _find_image(self, directory: Path, name: str) -> Optional[Path]:
        for path in directory.iterdir():
            if path.is_file() and path.stem == name and path.suffix.lower() in ALLOWED_SUFFIXES:
                return path
        return None

    def current_map(self) -> Dict[str, Any]:
        with self._lock:
            if self._current_map is None:
                raise NotFoundError("No map has been loaded yet")
            return dict(self._current_map)

    # ---------------- filesystem ----------------
    def list_maps(self) -> List[Dict[str, Any]]:
        maps: Dict[str, Dict[str, Any]] = {}
        active = self._active_name
        for path in sorted(settings.maps_dir.glob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in ALLOWED_SUFFIXES and suffix != ".yaml":
                continue
            entry = maps.setdefault(
                path.stem,
                {
                    "name": path.stem,
                    "modified_at": "",
                    "has_yaml": False,
                    "has_image": False,
                    "active": False,
                },
            )
            entry["modified_at"] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            if suffix == ".yaml":
                entry["has_yaml"] = True
            else:
                entry["has_image"] = True
        for entry in maps.values():
            entry["active"] = entry["name"] == active
        return list(maps.values())

    async def delete_map(self, db, name: str) -> None:
        removed = False
        for suffix in ALLOWED_SUFFIXES | {".yaml"}:
            path = _safe_path(settings.maps_dir, f"{name}{suffix}")
            if path.exists():
                path.unlink()
                removed = True
        if not removed:
            raise NotFoundError(f"Map '{name}' not found")
        await maps_repo.delete(db, name)
        if self._active_name == name:
            await map_state_repo.clear(db)
            with self._lock:
                self._active_name = None
                self._current_map = None

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
