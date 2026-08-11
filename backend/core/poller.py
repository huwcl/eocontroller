"""
poller.py

Background task that owns the EoCharger instance and is the ONLY thing
in the app that talks to the hardware. Runs once a second, forever, for
the life of the process - this is what keeps a charge session alive
continuously, the same role dump_state.py played during testing, just
as a permanent background service instead of a one-off diagnostic
script.
"""

import asyncio
import logging

from comms import EoCharger, ChargerCommsError
from core.state import state
from core.session_logger import SessionLogger
from core.status import build_status_payload
from core.ws_manager import manager as ws_manager
from config import load_config

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0


async def run_poll_loop():
    charger = EoCharger()
    session_logger = SessionLogger()
    config = load_config()

    # discover() and set_limit() are blocking hardware calls (SPI/GPIO) -
    # run them off the event loop thread so they never stall the API.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, charger.discover)
    _LOGGER.info("Poller connected to controller board: %s", charger.address)

    # Apply the configured startup value before the first poll, so the
    # very first cycle already requests it rather than starting at 0 and
    # waiting for the API to be told separately.
    async with state.lock:
        state.requested_amps = config.startup_amps
    _LOGGER.info("Startup charge limit set from config.toml: %sA", config.startup_amps)

    while True:
        async with state.lock:
            requested = state.requested_amps

        try:
            result = await loop.run_in_executor(None, charger.set_limit, requested)
            async with state.lock:
                state.latest = result
                state.last_error = None
                payload = build_status_payload(state)
            session_logger.record(result, requested)
        except ChargerCommsError as e:
            _LOGGER.warning("Poll failed: %s", e)
            async with state.lock:
                state.last_error = str(e)
                payload = build_status_payload(state)

        # Broadcast every cycle, success or failure - a failed poll is
        # useful information for the frontend too (e.g. showing a
        # "connection issue" indicator), not just something to hide.
        await ws_manager.broadcast(payload)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
