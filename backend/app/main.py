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
from app.db.repositories import robots as robot_repo
from app.db.session import init_db, session_scope
from app.middleware import RequestContextMiddleware
from app.ros.manager import ros_manager
from app.services import robot_service
from app.services.map_service import map_service
from app.services.task_service import task_runner
from app.startup import seed_initial_data

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    logger.info("Starting %s (%s)", settings.app_name, settings.environment)

    if settings.auto_create_tables:
        init_db()
    with session_scope() as db:
        seed_initial_data(db)
        robot_repo.mark_all_offline(db)

    if ros_manager.start():
        ros_manager.start_registration_listener(
            on_approved=lambda robot_id: ros_manager.start_controller(robot_id)
        )
        if settings.autostart_robot_controllers:
            with session_scope() as db:
                robot_service.autostart_controllers(db)
    else:
        logger.warning("Running without ROS 2 — robot control endpoints will return 503")

    try:
        yield
    finally:
        logger.info("Shutting down")
        task_runner.stop_all()
        map_service.shutdown()
        ros_manager.shutdown()
        with session_scope() as db:
            robot_repo.mark_all_offline(db)


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
