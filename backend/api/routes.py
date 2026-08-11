"""
api/routes.py

REST endpoints. These only ever read/write the shared AppState - they
never import comms/ or touch the hardware directly. All hardware access
goes through core/poller.py's background loop.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.state import state
from core.session_logger import DB_PATH
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
        if state.latest is None:
            raise HTTPException(
                status_code=503,
                detail="No data yet - poller hasn't completed a cycle",
            )
        result = state.latest
        error = state.last_error
        requested = state.requested_amps

    return {
        "requested_amps": requested,
        "charger_state": result.state.charger_state_name,
        "plug_state": result.state.plug_state,
        "vehicle_current_amps": result.state.p1_current,
        "hub_duty_limit_amps": result.state.hub_duty_limit_amps,
        "site_current_amps": result.site_current,
        "last_error": error,
    }


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
