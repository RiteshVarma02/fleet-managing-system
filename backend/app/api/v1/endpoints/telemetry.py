"""WebSocket telemetry fan-out.

One frame per `TELEMETRY_WS_INTERVAL_SECONDS` for the whole fleet, produced
once by the telemetry bus and shared by every subscriber. Adding operators
costs a socket write, not a database query — this is what replaces per-client
polling of `/robots/{id}/status`.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import principal_from_websocket
from app.core.logging_config import get_logger
from app.services.telemetry_bus import telemetry_bus

logger = get_logger(__name__)

router = APIRouter(tags=["telemetry"])

WS_CLOSE_POLICY_VIOLATION = 1008


@router.websocket("/telemetry/ws")
async def telemetry_ws(websocket: WebSocket) -> None:
    principal = principal_from_websocket(websocket)
    if principal is None:
        await websocket.close(code=WS_CLOSE_POLICY_VIOLATION)
        return

    await websocket.accept()
    queue = telemetry_bus.subscribe()
    try:
        # Send the current state immediately so the UI never renders empty.
        await websocket.send_json(
            {"type": "telemetry", "robots": telemetry_bus.fleet_snapshot()}
        )
        while True:
            frame = await queue.get()
            await websocket.send_text(frame)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:  # pragma: no cover - transport dependent
        logger.debug("Telemetry socket closed: %s", exc)
    finally:
        telemetry_bus.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()
