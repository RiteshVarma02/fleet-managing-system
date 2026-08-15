"""Compatibility session helpers for legacy SQL-era call sites.

The active backend uses MongoDB with Motor. This module keeps old imports
working while migration is in progress.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator, Optional

from app.db.mongo import get_database


@dataclass
class _DummyConnection:
    """Tiny SQLAlchemy-like facade used by readiness code paths."""

    def execute(self, _query: Any) -> int:
        return 1


class _DummyEngine:
    @contextmanager
    def connect(self) -> Generator[_DummyConnection, None, None]:
        yield _DummyConnection()


engine = _DummyEngine()


def get_db():
    return get_database()


def init_db() -> None:
    """No-op for MongoDB mode."""


@contextmanager
def session_scope() -> Generator[Any, None, None]:
    """Yield the shared Motor database handle for compatibility."""
    yield get_database()


def run_coro_sync(coro):
    """Run an async coroutine from sync code, even inside an event-loop thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - pass through
            error["err"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "err" in error:
        raise error["err"]
    return result.get("value")
