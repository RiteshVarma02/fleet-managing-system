"""Structured-ish logging setup used by every module (`logging.getLogger(__name__)`)."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from logging.config import dictConfig

from app.core.config import settings

_CONFIGURED = False
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": sys.stdout,
                }
            },
            "root": {"handlers": ["console"], "level": settings.log_level.upper()},
            "loggers": {
                "uvicorn": {"handlers": ["console"], "level": settings.log_level.upper(), "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
                "sqlalchemy.engine": {"level": "WARNING"},
            },
        }
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
