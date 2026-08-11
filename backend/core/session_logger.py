"""
session_logger.py

Watches poller output for the car-connected -> charge-complete lifecycle
(the same transitions we watched by eye in dump_state.py) and records
one row per charge session to sessions.db. Called once per poll from
poller.py, so it sees exactly what the API sees - no separate polling
loop, no chance of missing a transition between two different
observers.

kWh is an ESTIMATE - p1_current x live_voltage integrated over each
poll interval - sampled once a second rather than measured continuously.
Treat it as a reasonable indicator, not a certified reading you'd expect
to exactly match an electricity bill.
"""

import sqlite3
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from comms import PollResult

_LOGGER = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "db" / "sessions.db"

# Matches poller.py's POLL_INTERVAL_SECONDS. Kept as a separate constant
# here rather than importing it, so this file has no dependency on
# poller.py's internals - just needs to agree on the same interval.
POLL_INTERVAL_HOURS = 1.0 / 3600


def _init_schema(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS charge_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            amp_limit_requested REAL,
            min_amps REAL,
            max_amps REAL,
            total_kwh REAL,
            avg_kw REAL
        )
        """
    )
    conn.commit()


@dataclass
class _ActiveSession:
    started_at: datetime
    amp_limit_requested: float
    min_amps: float = float("inf")
    max_amps: float = 0.0
    total_kwh: float = 0.0
    poll_count: int = 0


class SessionLogger:
    """Call record() once per poll with the latest PollResult and the
    amps that were requested for that poll. Session start/end is
    detected purely from charger_state_name transitions."""

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _init_schema(self._conn)
        self._active: Optional[_ActiveSession] = None
        self._last_state: Optional[str] = None

    def record(self, result: PollResult, requested_amps: float):
        current_state = result.state.charger_state_name

        # Only open a session on the state actually CHANGING to
        # car-connected, not every poll while it happens to already be
        # in that state - and only if one isn't already open, in case a
        # brief plug-present blip (like we saw during real testing)
        # bounces back through car-connected before charging starts.
        just_entered_connected = (
            current_state == "car-connected" and self._last_state != "car-connected"
        )
        if just_entered_connected and self._active is None:
            self._active = _ActiveSession(
                started_at=datetime.now(),
                amp_limit_requested=requested_amps,
            )
            _LOGGER.info("Charge session started")

        if self._active is not None:
            amps = result.state.p1_current
            if amps > 0:
                self._active.min_amps = min(self._active.min_amps, amps)
                self._active.max_amps = max(self._active.max_amps, amps)
            self._active.total_kwh += (
                (amps * result.state.live_voltage / 1000) * POLL_INTERVAL_HOURS
            )
            self._active.poll_count += 1

        if current_state == "charge-complete" and self._active is not None:
            self._close_session()

        self._last_state = current_state

    def _close_session(self):
        session = self._active
        duration_hours = session.poll_count * POLL_INTERVAL_HOURS
        avg_kw = (session.total_kwh / duration_hours) if duration_hours > 0 else 0.0
        # min_amps stays at its inf() starting value if the car never
        # actually drew current during the session - report 0 instead.
        min_amps = session.min_amps if session.min_amps != float("inf") else 0.0

        self._conn.execute(
            """
            INSERT INTO charge_sessions
                (started_at, ended_at, amp_limit_requested, min_amps, max_amps, total_kwh, avg_kw)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.started_at.isoformat(),
                datetime.now().isoformat(),
                session.amp_limit_requested,
                min_amps,
                session.max_amps,
                round(session.total_kwh, 4),
                round(avg_kw, 4),
            ),
        )
        self._conn.commit()
        _LOGGER.info(
            "Charge session logged: %.3f kWh over %.1f min",
            session.total_kwh,
            duration_hours * 60,
        )
        self._active = None
