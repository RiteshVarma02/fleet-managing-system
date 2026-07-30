"""Application configuration.

All runtime configuration is read from environment variables (or a `.env`
file) exactly once at import time and exposed through a cached singleton.
Nothing else in the codebase reads `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

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
    app_name: str = "ROS2 Swarm Controller API"
    environment: str = Field(default="development")
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # --- Security ----------------------------------------------------------
    # MUST be overridden in production (`SECRET_KEY=...`).
    secret_key: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 12 * 60
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # --- Database ----------------------------------------------------------
    database_url: str = Field(default="sqlite:///./swarm.db")
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_echo: bool = False
    # Convenience for dev only. In production run Alembic migrations instead.
    auto_create_tables: bool = True

    # --- Storage -----------------------------------------------------------
    data_dir: Path = Field(default=BASE_DIR / "data")
    maps_dir: Path = Field(default=BASE_DIR / "maps")

    # --- ROS 2 -------------------------------------------------------------
    ros_enabled: bool = True
    ros_domain_id: int | None = None
    map_topic: str = "/map"
    map_publish_interval_seconds: float = 1.0
    robot_db_update_interval_seconds: float = 0.5
    registration_topic: str = "/robot/register"
    registration_response_topic: str = "/robot/register/response"
    autostart_robot_controllers: bool = True

    # --- Navigation / tasks -------------------------------------------------
    nav_goal_timeout_seconds: float = 300.0
    nav_poll_interval_seconds: float = 5.0
    max_task_repeats: int = 1000
    slam_launch_command: List[str] = Field(
        default_factory=lambda: ["ros2", "launch", "slam_toolbox", "online_async_launch.py"]
    )
    map_saver_command: List[str] = Field(
        default_factory=lambda: ["ros2", "run", "nav2_map_server", "map_saver_cli"]
    )
    map_save_timeout_seconds: int = 30

    @field_validator("cors_origins", "slam_launch_command", "map_saver_command", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow `A,B,C` style env values for list fields."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.maps_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
