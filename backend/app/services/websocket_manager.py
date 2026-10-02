"""WebSocket connection manager: pushes new analytics to dashboards without page refresh."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.schemas.analytics import RoomUpdateMessage

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Keeps the open WebSocket connections of every room."""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the server's event loop so other threads (MQTT, thread pool) can publish."""
        self._loop = loop

    async def connect(self, room_id: int, websocket: WebSocket) -> None:
        """Accept a connection and register it for a room."""
        await websocket.accept()
        self._connections[room_id].add(websocket)
        logger.info("WebSocket connected for room %s (%d total)", room_id, len(self._connections[room_id]))

    def disconnect(self, room_id: int, websocket: WebSocket) -> None:
        """Forget a connection."""
        self._connections[room_id].discard(websocket)

    async def broadcast(self, room_id: int, payload: dict[str, Any]) -> None:
        """Send a JSON payload to every client watching a room; drop dead connections."""
        for websocket in list(self._connections.get(room_id, ())):
            try:
                await websocket.send_json(payload)
            except Exception:  # client went away
                self.disconnect(room_id, websocket)

    def publish_threadsafe(self, room_id: int, message: RoomUpdateMessage) -> None:
        """Broadcast from ANY thread (used by the ingestion pipeline)."""
        if self._loop is None or not self._connections.get(room_id):
            return
        payload = message.model_dump(mode="json")
        future = asyncio.run_coroutine_threadsafe(self.broadcast(room_id, payload), self._loop)
        future.add_done_callback(_log_failure)

    def connection_count(self, room_id: int) -> int:
        """Number of clients currently watching a room."""
        return len(self._connections.get(room_id, ()))


def _log_failure(future: "asyncio.futures.Future | Any") -> None:
    """Log exceptions of fire-and-forget broadcasts."""
    if not future.cancelled() and future.exception() is not None:
        logger.error("WebSocket broadcast failed: %s", future.exception())
