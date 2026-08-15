"""ASGI application factory and process lifespan.

Startup order matters:
1. logging  2. database  3. ROS runtime  4. controllers/listener
Shutdown reverses it so no thread outlives the objects it uses.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_exception_handlers
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging_config import configure_logging, get_logger
from app.db.documents import RobotStatus
from app.db.mongo import close_client, connect_and_verify, ensure_indexes
from app.db.repositories import robots_repo
from app.middleware import RequestContextMiddleware
from app.ros.manager import ros_manager
from app.services.map_service import map_service
from app.startup import seed_initial_data

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("Starting %s (%s)", settings.app_name, settings.environment)

    db = await connect_and_verify()
    await ensure_indexes()
    await seed_initial_data(db)
    await robots_repo.mark_all_offline(db)

    if ros_manager.start():
        ros_manager.start_registration_listener(
            on_approved=lambda robot_id: ros_manager.start_controller(robot_id)
        )
        if settings.autostart_robot_controllers:
            for robot in await robots_repo.list_all(db, approved_only=True):
                robot_id = str(robot.get("robot_id") or "")
                if not robot_id:
                    continue
                started, message = ros_manager.start_controller(robot_id)
                if started:
                    await robots_repo.set_status(db, robot_id, RobotStatus.online)
                else:
                    logger.warning("Controller not started for %s: %s", robot_id, message)
    else:
        logger.warning("Running without ROS 2 — robot control endpoints will return 503")

    try:
        yield
    finally:
        logger.info("Shutting down")
        map_service.shutdown()
        ros_manager.shutdown()
        try:
            await robots_repo.mark_all_offline(db)
        finally:
            await close_client()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    install_exception_handlers(app)
    app.include_router(api_router, prefix=f"{settings.api_prefix}/v1")
    return app


app = create_app()
