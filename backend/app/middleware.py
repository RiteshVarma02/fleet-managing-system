"""Request-scoped logging context and timing."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_config import get_logger, request_id_var

logger = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach an `X-Request-ID` to every request and log its duration."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.endswith(("/health", "/ready")):
            logger.info(
                "%s %s -> %s (%.1f ms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        return response
