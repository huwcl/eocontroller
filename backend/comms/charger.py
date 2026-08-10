"""
charger.py

The public interface the rest of the app talks to. Everything else in
comms/ is a building block for this: spi_bridge.py moves bytes, ade7858.py
reads CT clamps, protocol.py builds/parses packets. This file wires them
together into three calls - discover(), set_limit(), poll() - and nothing
outside comms/ needs to know how any of that works underneath.
"""

import logging
from dataclasses import dataclass

from . import protocol
from .spi_bridge import SpiUartBridge
from .ade7858 import Ade7858

_LOGGER = logging.getLogger(__name__)

# Retry a failed exchange this many times before giving up. An empty or
# overrun response is fairly common on a busy bus, and a single retry
# clears most of them.
MAX_RETRIES = 1


class ChargerCommsError(Exception):
    """Raised when the board can't be reached at all - no response after
    retries, or DISCOVER has never succeeded."""


@dataclass
class PollResult:
    """One full poll cycle: board state plus CT clamp readings, combined
    the same way openeo did - on the Mini Pro 2, the board's own p1
    current is more accurate for vehicle current than the CT clamp, since
    the CT channels measure at the meter level rather than the charger
    output."""
    state: protocol.ChargerState
    site_current: float
    vehicle_current: float
    solar_current: float


class EoCharger:
    """High-level Mini Pro 2 controller.

    Usage:
        charger = EoCharger()
        charger.discover()
        result = charger.set_limit(16)   # 16A, returns a PollResult
    """

    def __init__(self):
        self._bridge = SpiUartBridge()
        self._ct = Ade7858()
        self.address: str | None = None

    @property
    def connected(self) -> bool:
        return self.address is not None

    def _exchange(self, packet: str, recv_delay: float) -> str | None:
        """Send a packet, read the response, verify its checksum, and
        return the payload with the frame markers stripped. Returns None
        if the exchange failed in a way that's worth retrying (empty
        response, overrun, bad checksum) rather than raising - callers
        decide whether to retry or give up."""
        self._bridge.tx(packet)
        raw = self._bridge.rx(recv_delay=recv_delay)

        if not raw:
            _LOGGER.info("No response from controller board (empty or overrun)")
            return None

        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError:
            _LOGGER.warning("Controller response was not valid ASCII")
            return None

        # RX frame is "<marker><payload><checksum>\r" - the checksum covers
        # everything except itself and the trailing \r, INCLUDING the
        # leading marker byte. That marker isn't guaranteed to be "!" - the
        # board has been observed sending other values there - so it's
        # treated as an opaque frame marker by position, not matched
        # against a fixed character.
        checksum_body, checksum = text[:-3], text[-3:-1]
        if not protocol.verify_checksum(checksum_body, checksum):
            _LOGGER.warning("Controller response failed checksum verification")
            return None

        # Strip the leading marker byte and the trailing checksum for the
        # payload we hand back to the caller.
        return text[1:-3]

    def _exchange_with_retry(self, packet: str, recv_delay: float) -> str:
        last_result = None
        for attempt in range(MAX_RETRIES + 1):
            last_result = self._exchange(packet, recv_delay)
            if last_result is not None:
                return last_result
            _LOGGER.debug("Retrying exchange (attempt %d)", attempt + 1)
        raise ChargerCommsError("No usable response from controller board after retries")

    def discover(self) -> str:
        """Fetch the control board's serial address. Must succeed before
        set_limit() will work, since every SET_LIMIT packet has to echo
        this address back."""
        payload = self._exchange_with_retry(protocol.DISCOVER_PACKET, recv_delay=3.0)
        if not payload:
            raise ChargerCommsError("DISCOVER returned an empty address")
        self.address = payload
        _LOGGER.info("Discovered controller board address: %s", self.address)
        return self.address

    def set_limit(self, amps: float) -> PollResult:
        """Set the charging current limit and return the full board state
        plus CT readings in one call - this mirrors the real protocol,
        where SET_LIMIT's response IS the state poll. There's no separate
        "just read state" command; every state update comes from asking
        for a (possibly unchanged) current limit.
        """
        if not self.connected:
            self.discover()

        packet = protocol.build_set_limit_packet(self.address, amps)
        # "!" is re-added here because parse_state_frame's slice offsets
        # are documented against the full RX frame, including the marker
        # that _exchange() already stripped off for checksum handling.
        payload = "!" + self._exchange_with_retry(packet, recv_delay=0.5)
        state = protocol.parse_state_frame(payload)

        ct = self._ct.read_currents()
        vehicle_current = state.p1_current  # more accurate than the CT clamp on this hardware

        return PollResult(
            state=state,
            site_current=ct["site"],
            vehicle_current=vehicle_current,
            solar_current=ct["solar"],
        )

    def stop_charging(self) -> PollResult:
        """Convenience wrapper - anything below MIN_CHARGE_AMPS stops the
        charge session, so 0 is an explicit, readable way to say that."""
        return self.set_limit(0)
