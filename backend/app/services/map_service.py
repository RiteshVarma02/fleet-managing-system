"""Map image handling, SLAM process control and map file listing."""

from __future__ import annotations

import base64
import io
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.db.repositories import map_state_repo, maps_repo

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
        """Cache the PNG + metadata in memory for the dashboard.

        V1: robots keep their own copy of the single fleet map (delivered via
        fleet file sync), so nothing is published on ROS here.
        """
        published = False

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

    def shutdown(self) -> None:
        """Nothing to stop: V1 has no SLAM process and no ROS map publisher."""
        return None


map_service = MapService()
