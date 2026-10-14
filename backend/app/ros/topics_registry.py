"""Loads `config/fleet_topics.yaml`: the single source of truth for topics.

No topic name or message type is hard-coded anywhere else in the backend.
Capabilities ask for a *logical* topic (``"goal"``, ``"pose"`` …) and this
module resolves it to the concrete ROS name for one robot.

The file path comes from ``FLEET_TOPICS_FILE`` (see `core/config.py`).
`reload()` re-reads it at runtime; already-connected controllers keep their
old topics until they reconnect.
"""

from __future__ import annotations

import copy
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.core.config import settings

QOS_PROFILES = {"default", "sensor", "latched"}
_TYPE_RE = re.compile(r"^[A-Za-z_][\w]*/(msg|srv|action)/[A-Z]\w*$")
_ROBOT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class TopicConfigError(ValueError):
    """Raised when fleet_topics.yaml is malformed."""


# ---------------------------------------------------------------------------
# parsing + validation (pure functions: no ROS, easy to test)
# ---------------------------------------------------------------------------
def _validate_topic(where: str, spec: Any) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise TopicConfigError(f"{where}: must be a mapping with 'name' and 'type'")
    name = spec.get("name")
    msg_type = spec.get("type")
    qos = spec.get("qos", "default")
    if not isinstance(name, str) or not name.startswith("/"):
        raise TopicConfigError(f"{where}: 'name' must be an absolute topic, got {name!r}")
    if not isinstance(msg_type, str) or not _TYPE_RE.match(msg_type):
        raise TopicConfigError(f"{where}: 'type' must look like 'pkg/msg/Name', got {msg_type!r}")
    if qos not in QOS_PROFILES:
        raise TopicConfigError(f"{where}: 'qos' must be one of {sorted(QOS_PROFILES)}")
    return {"name": name, "type": msg_type, "qos": qos}


def _resolve_type(
    name: str, raw_types: Dict[str, Any], resolved: Dict[str, Any], stack: List[str]
) -> Dict[str, Any]:
    if name in resolved:
        return resolved[name]
    if name in stack:
        raise TopicConfigError(f"robot type inheritance cycle: {' -> '.join(stack + [name])}")
    raw = raw_types.get(name)
    if not isinstance(raw, dict):
        raise TopicConfigError(f"robot type '{name}' is not defined")

    parent: Dict[str, Any] = {"capabilities": [], "topics": {}, "description": ""}
    if raw.get("extends"):
        parent = _resolve_type(str(raw["extends"]), raw_types, resolved, stack + [name])

    capabilities = list(parent["capabilities"])
    for capability in raw.get("capabilities") or []:
        if capability not in capabilities:
            capabilities.append(str(capability))

    topics = copy.deepcopy(parent["topics"])
    for logical, spec in (raw.get("topics") or {}).items():
        if spec is None:  # explicit removal in a child type
            topics.pop(logical, None)
            continue
        topics[str(logical)] = _validate_topic(f"robot_types.{name}.topics.{logical}", spec)

    result = {
        "description": str(raw.get("description") or parent.get("description") or ""),
        "extends": raw.get("extends"),
        "capabilities": capabilities,
        "topics": topics,
    }
    resolved[name] = result
    return result


def parse_config(data: Any) -> Dict[str, Any]:
    """Validate a loaded YAML document and flatten `extends` inheritance."""
    if not isinstance(data, dict):
        raise TopicConfigError("fleet_topics.yaml must be a mapping")
    raw_types = data.get("robot_types")
    if not isinstance(raw_types, dict) or not raw_types:
        raise TopicConfigError("'robot_types' must define at least one robot type")

    resolved: Dict[str, Any] = {}
    for name in raw_types:
        _resolve_type(str(name), raw_types, resolved, [])

    default_type = str(data.get("default_robot_type") or next(iter(raw_types)))
    if default_type not in resolved:
        raise TopicConfigError(f"default_robot_type '{default_type}' is not defined")

    fleet = {
        str(key): _validate_topic(f"fleet.{key}", spec)
        for key, spec in (data.get("fleet") or {}).items()
    }
    return {"default_robot_type": default_type, "robot_types": resolved, "fleet": fleet}


def load_config(path: Path) -> Dict[str, Any]:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TopicConfigError(f"topic config not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise TopicConfigError(f"invalid YAML in {path}: {exc}") from exc
    return parse_config(raw)


def is_valid_robot_id(robot_id: str) -> bool:
    return bool(_ROBOT_ID_RE.match(robot_id or ""))


# ---------------------------------------------------------------------------
# process-wide registry
# ---------------------------------------------------------------------------
class TopicRegistry:
    def __init__(self, path: Optional[Path] = None) -> None:
        self._lock = threading.RLock()
        self._path = Path(path or settings.fleet_topics_file)
        self._config: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> Path:
        return self._path

    def _cfg(self) -> Dict[str, Any]:
        with self._lock:
            if self._config is None:
                self._config = load_config(self._path)
            return self._config

    def reload(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Re-read the file. A broken file raises and keeps the old config."""
        with self._lock:
            new_path = Path(path) if path else self._path
            config = load_config(new_path)
            self._path, self._config = new_path, config
            return config

    def use_config(self, config: Dict[str, Any]) -> None:
        """Install an already-parsed config (tests)."""
        with self._lock:
            self._config = config

    # --- queries -----------------------------------------------------------
    @property
    def default_robot_type(self) -> str:
        return self._cfg()["default_robot_type"]

    def robot_types(self) -> List[str]:
        return sorted(self._cfg()["robot_types"])

    def is_known_type(self, robot_type: str) -> bool:
        return robot_type in self._cfg()["robot_types"]

    def type_spec(self, robot_type: str) -> Dict[str, Any]:
        types = self._cfg()["robot_types"]
        return types.get(robot_type) or types[self.default_robot_type]

    def capabilities_for(self, robot_type: str) -> List[str]:
        return list(self.type_spec(robot_type)["capabilities"])

    def resolve_topics(self, robot_type: str, robot_id: str) -> Dict[str, Dict[str, Any]]:
        """Concrete topics for one robot instance: logical -> {name, type, qos}."""
        if not is_valid_robot_id(robot_id):
            raise TopicConfigError(
                f"robot id {robot_id!r} is not a valid ROS namespace "
                "(letters, digits, underscore; must start with a letter)"
            )
        return {
            logical: {**spec, "name": spec["name"].format(robot=robot_id)}
            for logical, spec in self.type_spec(robot_type)["topics"].items()
        }

    def topic(self, robot_type: str, robot_id: str, logical: str) -> Optional[Dict[str, Any]]:
        return self.resolve_topics(robot_type, robot_id).get(logical)

    def has_topic(self, robot_type: str, logical: str) -> bool:
        return logical in self.type_spec(robot_type)["topics"]

    def fleet_topic(self, logical: str) -> Dict[str, Any]:
        topic = self._cfg()["fleet"].get(logical)
        if topic is None:
            raise TopicConfigError(f"fleet topic '{logical}' is not defined in {self._path}")
        return dict(topic)

    def describe(self) -> Dict[str, Any]:
        """JSON-friendly view for the API / developer panel."""
        return {"path": str(self._path), **copy.deepcopy(self._cfg())}


topic_registry = TopicRegistry()


# Module-level helpers keep call sites short.
def robot_types() -> List[str]:
    return topic_registry.robot_types()


def default_robot_type() -> str:
    return topic_registry.default_robot_type


def type_spec(robot_type: str) -> Dict[str, Any]:
    return topic_registry.type_spec(robot_type)


def capabilities_for(robot_type: str) -> List[str]:
    return topic_registry.capabilities_for(robot_type)


def is_known_type(robot_type: str) -> bool:
    return topic_registry.is_known_type(robot_type)


def resolve_topics(robot_type: str, robot_id: str) -> Dict[str, Dict[str, Any]]:
    return topic_registry.resolve_topics(robot_type, robot_id)
