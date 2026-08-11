"""
api/routes.py

REST endpoints. These only ever read/write the shared AppState - they
never import comms/ or touch the hardware directly. All hardware access
goes through core/poller.py's background loop.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from core.state import state
from core.session_logger import DB_PATH
from core.status import build_status_payload
from core.ws_manager import manager as ws_manager
from comms.protocol import MAX_CHARGE_AMPS
import sqlite3

router = APIRouter()


class SetLimitRequest(BaseModel):
    # 0 is a valid, deliberate value - it's how the protocol says "stop
    # charging" (see MIN_CHARGE_AMPS in protocol.py), so it's allowed
    # here rather than rejected.
    amps: float = Field(..., ge=0, le=MAX_CHARGE_AMPS)


@router.get("/status")
async def get_status():
    async with state.lock:
        return build_status_payload(state)


@router.websocket("/ws")
async def websocket_status(websocket: WebSocket):
    """Pushes a status update once a second automatically - no polling
    needed on the frontend. poller.py calls ws_manager.broadcast() after
    each successful poll; this endpoint just registers the connection
    and keeps it open until the client disconnects."""
    await ws_manager.connect(websocket)

    # Send an immediate snapshot on connect, rather than making the
    # client wait up to a full poll interval for its first update.
    async with state.lock:
        payload = build_status_payload(state)
    await websocket.send_json(payload)

    try:
        while True:
            # We don't expect the client to send anything meaningful -
            # this just keeps the connection open and lets us detect a
            # disconnect via the exception it raises when the client
            # goes away.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


@router.post("/limit")
async def set_limit(body: SetLimitRequest):
    async with state.lock:
        state.requested_amps = body.amps
    return {"requested_amps": body.amps}


@router.get("/sessions")
async def get_sessions(limit: int = 20):
    # Read-only, separate sqlite3 connection - session_logger.py owns
    # writes from the poller's own thread, this just reads for the API.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM charge_sessions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
