"""WebSocket endpoint: live room updates for the dashboard.

Connect to  ws://localhost:8000/ws/rooms/{room_id}
You immediately receive the latest state (if any) and then one message per processed reading.
Message shape: see `RoomUpdateMessage` (room_id, occupancy, thermal, recommendation, simulated, ...).
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.database.database import SessionLocal
from app.models.room import Room
from app.services.analytics_service import build_update_message, get_latest_analytics

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])

UNKNOWN_ROOM_CLOSE_CODE = 4404


def _load_snapshot(room_id: int) -> tuple[bool, dict | None]:
    """Return (room_exists, latest_message_as_json_or_None). Runs in a worker thread."""
    with SessionLocal() as db:
        if db.get(Room, room_id) is None:
            return False, None
        row = get_latest_analytics(db, room_id)
        return True, None if row is None else build_update_message(row).model_dump(mode="json")


@router.websocket("/ws/rooms/{room_id}")
async def room_updates(websocket: WebSocket, room_id: int) -> None:
    """Stream analytics updates of one room."""
    manager = websocket.app.state.ws_manager
    await manager.connect(room_id, websocket)
    try:
        exists, snapshot = await run_in_threadpool(_load_snapshot, room_id)
        if not exists:
            await websocket.close(code=UNKNOWN_ROOM_CLOSE_CODE, reason="Room not found")
            return
        if snapshot is not None:
            await websocket.send_json(snapshot)
        while True:  # keep the connection open; we only push, clients may send pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room_id, websocket)
