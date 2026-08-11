"""
state.py

Shared, in-memory application state. One instance lives for the life of
the FastAPI process and is read/written from exactly two places:

  - core/poller.py's background loop, which owns all hardware access
  - api/routes.py, which reads the latest result and writes the
    requested limit - it never touches the charger hardware directly

Keeping all hardware access in a single background task avoids two
requests racing to use the SPI bus at once, which the hardware has no
protection against.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from comms import PollResult


@dataclass
class AppState:
    # What the poller should request on its next cycle. Changed via the
    # API. Starts at 0 (stop charging) rather than any active current, so
    # a fresh process never starts by asking the charger to deliver power.
    requested_amps: float = 0.0

    # The most recent successful poll result. None until the first poll
    # completes after startup.
    latest: Optional[PollResult] = None

    # Set if the last poll attempt failed, so the API can report it
    # rather than silently serving stale data forever.
    last_error: Optional[str] = None

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


state = AppState()
