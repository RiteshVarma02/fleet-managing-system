"""Application configuration.

All runtime configuration is read from environment variables (or a `.env`
file) exactly once at import time and exposed through a cached singleton.
Nothing else in the codebase reads `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # --- Service -----------------------------------------------------------
    app_name: str = "Fleet Management System API"
    environment: str = Field(default="development")
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # --- Security ----------------------------------------------------------
    # MUST be overridden in production (`JWT_SECRET=...`).
    jwt_secret: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 12 * 60
    jwt_refresh_expiry_minutes: int = 7 * 24 * 60
    login_max_attempts: int = 5
    login_attempt_window_seconds: int = 15 * 60
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    bootstrap_operator_username: str = "operator"
    bootstrap_operator_password: str = "operator123"
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # --- MongoDB (local container or Atlas — selected purely by config) -----
    mongo_mode: str = Field(default="local")  # local | atlas
    mongo_uri: str = Field(default="mongodb://localhost:27017")
    mongo_db_name: str = "fleet_management"
    mongo_max_pool_size: int = 50
    mongo_min_pool_size: int = 0
    mongo_server_selection_timeout_ms: int = 5_000

    # --- Storage -----------------------------------------------------------
    data_dir: Path = Field(default=BASE_DIR / "data")
    maps_dir: Path = Field(default=BASE_DIR / "maps")

    # --- ROS 2 -------------------------------------------------------------
    ros_enabled: bool = True
    # V1: the whole fleet shares ONE ROS domain. Robots are separated by
    # namespace (/{robot}/...), not by domain.
    ros_domain_id: int = 0
    # Every topic name/type lives in this file — nothing is hard-coded.
    fleet_topics_file: Path = Field(default=BASE_DIR / "config" / "fleet_topics.yaml")
    autostart_robot_controllers: bool = True

    # --- Telemetry write-behind (server load control) ----------------------
    # ROS callbacks never touch Mongo directly: they push into an in-memory
    # bus that is flushed in one bulk write per interval.
    telemetry_flush_interval_seconds: float = 2.0
    telemetry_ws_interval_seconds: float = 0.5
    telemetry_stale_after_seconds: float = 15.0

    # --- Waypoint navigation / tasks ----------------------------------------
    # A leg with no arrival after this long fails (also catches a stopped
    # traffic_manager_node, which makes route_manager wait forever).
    nav_goal_timeout_seconds: float = 300.0
    nav_poll_interval_seconds: float = 0.5
    # `final_goal_reached` carries no goal id: a TRUE arriving this soon after a
    # new goal is treated as a late message from the previous leg and ignored.
    waypoint_arrival_debounce_seconds: float = 1.5
    fleet_files_ack_timeout_seconds: float = 8.0
    max_task_repeats: int = 1000
    max_task_stops: int = 50
    task_max_concurrent: int = 32

    @field_validator(
        "cors_origins",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow `A,B,C` style env values for list fields."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("mongo_mode")
    @classmethod
    def _check_mongo_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in {"local", "atlas"}:
            raise ValueError("MONGO_MODE must be 'local' or 'atlas'")
        return mode

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def ros_env(self) -> Dict[str, str]:
        return {"ROS_DOMAIN_ID": str(self.ros_domain_id)}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (settings.data_dir, settings.maps_dir):
        directory.mkdir(parents=True, exist_ok=True)
    if settings.is_production and settings.jwt_secret == "change-me-in-production":
        raise RuntimeError("JWT_SECRET must be set in production")
    return settings


settings = get_settings()
