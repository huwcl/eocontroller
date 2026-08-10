"""
protocol.py

Pure protocol logic for talking to the EO Mini Pro 2 control board over the
RS485 link. Nothing in this file touches SPI, GPIO, or any hardware - it only
builds and parses ASCII packet strings. That split means the packet format
can be tested on a laptop with no Pi attached.

Frame format (confirmed against the original openeo source):

  TX: "+" <command> <payload> <checksum> "\r"
  RX: "!" <payload> <checksum> "\r\n"

The checksum is the sum of the ASCII byte values of everything before it,
masked to 8 bits, printed as two uppercase hex digits.
"""

from dataclasses import dataclass
from enum import IntEnum


# Command codes used in the "+<command>..." TX frame.
CMD_SET_LIMIT = "0"
CMD_DISCOVER = "1"

# The DISCOVER packet is fixed - it carries no address, since we don't have
# one yet. "+1" checksums to 0x5C, so the full packet is always "+15C".
DISCOVER_PACKET = "+" + CMD_DISCOVER + "5C"

# Minimum current the board will actually start a charge at. Anything below
# this is treated as "stop charging" (duty 0).
MIN_CHARGE_AMPS = 6
MAX_CHARGE_AMPS = 32

# duty = amps / DUTY_STEP, and the inverse, amps = duty * DUTY_STEP.
DUTY_STEP = 0.06


class ChargerStateId(IntEnum):
    """Numeric charger_state values, as returned by the board."""
    START = 0
    SETTLE_TIME = 1
    TEST_INCOMING_MAINS = 2
    MAINS_FAULT_START = 3
    MAINS_FAULT = 4
    IDLE_START = 5
    IDLE = 6
    PLUG_PRESENT_START = 7
    PLUG_PRESENT = 8
    CAR_CONNECTED_START = 9
    CAR_CONNECTED = 10
    CHARGING_START = 11
    CHARGING = 12
    CHARGE_COMPLETE_START = 13
    CHARGE_COMPLETE = 14
    CHARGE_SUSPENDED_START = 15
    CHARGE_SUSPENDED = 16
    CHARGE_PAUSED = 18
    CHARGE_SIMULATED = 99


# Human-readable names, kept separate from the enum so an unknown or future
# state id doesn't blow up parsing - we fall back to "unknown-<id>".
CHARGER_STATE_NAMES = {
    ChargerStateId.START: "start",
    ChargerStateId.SETTLE_TIME: "settle-time",
    ChargerStateId.TEST_INCOMING_MAINS: "test-incoming-mains",
    ChargerStateId.MAINS_FAULT_START: "mains-fault-start",
    ChargerStateId.MAINS_FAULT: "mains-fault",
    ChargerStateId.IDLE_START: "idle-start",
    ChargerStateId.IDLE: "idle",
    ChargerStateId.PLUG_PRESENT_START: "plug-present-start",
    ChargerStateId.PLUG_PRESENT: "plug-present",
    ChargerStateId.CAR_CONNECTED_START: "car-connected-start",
    ChargerStateId.CAR_CONNECTED: "car-connected",
    ChargerStateId.CHARGING_START: "charging-start",
    ChargerStateId.CHARGING: "charging",
    ChargerStateId.CHARGE_COMPLETE_START: "charge-complete-start",
    ChargerStateId.CHARGE_COMPLETE: "charge-complete",
    ChargerStateId.CHARGE_SUSPENDED_START: "charge-suspended-start",
    ChargerStateId.CHARGE_SUSPENDED: "charge-suspended",
    ChargerStateId.CHARGE_PAUSED: "charge-paused",
    ChargerStateId.CHARGE_SIMULATED: "charge-simulated",
}


class ProtocolError(Exception):
    """Raised for anything wrong with a packet: bad checksum, wrong length,
    or a field that won't decode as expected ASCII/hex."""


def generate_checksum(text: str) -> str:
    """Sum the ASCII byte values of `text`, keep the low 8 bits, return as
    two uppercase hex digits. Used for both building TX packets and
    verifying RX packets."""
    checksum = sum(text.encode("ascii"))
    return "%02X" % (checksum & 0xFF)


def verify_checksum(payload: str, checksum: str) -> bool:
    """Check a received checksum against one we compute ourselves."""
    return checksum.upper() == generate_checksum(payload)


def amps_to_duty(amps: float) -> int:
    """Convert a requested charge current into the duty value the board
    expects. Anything below MIN_CHARGE_AMPS means "stop charging"."""
    if amps < MIN_CHARGE_AMPS:
        return 0
    return round(amps / DUTY_STEP)


def duty_to_amps(duty: int) -> float:
    """Inverse of amps_to_duty - used when decoding duty-shaped fields
    coming back from the board (e.g. hub_duty_limit)."""
    return round(duty * DUTY_STEP, 2)


def build_set_limit_packet(address: str, amps: float) -> str:
    """Build a full SET_LIMIT TX packet: command + board address + duty,
    with the checksum appended. `address` is whatever DISCOVER returned -
    it's opaque to us, we just echo it back."""
    if not (0 <= amps <= MAX_CHARGE_AMPS):
        raise ValueError(f"amps must be between 0 and {MAX_CHARGE_AMPS}, got {amps}")
    duty = amps_to_duty(amps)
    payload = "+" + CMD_SET_LIMIT + address + f"{duty:03X}"
    return payload + generate_checksum(payload)


@dataclass
class ChargerState:
    """Decoded fields from a SET_LIMIT response frame. Field names and
    slice positions are taken directly from the openeo source - see
    parse_state_frame() for the byte offsets they came from.

    Fields marked "raw" are passed through as the board's hex value with
    no known scaling - we haven't been able to confirm their units without
    risking the physical unit, so treat them as opaque until verified
    against real hardware behaviour.
    """
    version: str
    switch_setting: str
    cp_voltage_raw: int
    charge_duty_raw: int
    plug_voltage_raw: int
    live_voltage: float          # volts
    neutral_voltage_raw: int
    daylight_raw: int
    mains_freq_raw: int
    charger_state_id: int
    charger_state_name: str
    relay_state: str
    plug_state: str
    hub_duty_limit_amps: float
    charge_duty_timer_raw: int
    station_uptime_seconds: int
    charge_time_seconds: int
    state_of_mains_raw: int
    cp_line_state: str
    station_id: str
    random_value: str
    max_current_raw: int
    persistent_id: str
    watchdog_current_raw: int
    watchdog_time_raw: int
    p1_current: float            # amps
    p2_current: float            # amps
    p3_current: float            # amps
    eco7_switch: str


def parse_state_frame(payload: str) -> ChargerState:
    """Decode a SET_LIMIT response payload (checksum and frame markers
    already stripped) into a ChargerState.

    `payload` is expected to start with a marker byte at position 0
    (whatever the board sends there - not guaranteed to be "!", see
    charger.py), followed by the state fields. The checksum is NOT part
    of this string - it's stripped and verified separately in
    charger.py._exchange() before this function ever sees the data, so
    the full field map ends at eco7_switch (77 characters), not 79.
    """
    if len(payload) < 77:
        raise ProtocolError(
            f"state frame too short: expected at least 77 chars, got {len(payload)}"
        )

    def h(start: int, end: int) -> int:
        return int(payload[start:end], 16)

    state_id = h(25, 27)
    state_name = CHARGER_STATE_NAMES.get(state_id, f"unknown-{state_id}")

    return ChargerState(
        version=payload[1:3],
        switch_setting=payload[3],
        cp_voltage_raw=h(4, 7),
        charge_duty_raw=h(7, 10),
        plug_voltage_raw=h(10, 13),
        live_voltage=round(h(13, 16) / 3.78580786, 1),
        neutral_voltage_raw=h(16, 19),
        daylight_raw=h(19, 22),
        mains_freq_raw=h(22, 25),
        charger_state_id=state_id,
        charger_state_name=state_name,
        relay_state=payload[27],
        plug_state=payload[28],
        hub_duty_limit_amps=duty_to_amps(h(29, 32)),
        charge_duty_timer_raw=h(32, 36),
        station_uptime_seconds=h(36, 40),
        charge_time_seconds=h(40, 44),
        state_of_mains_raw=h(44, 46),
        cp_line_state=payload[46],
        station_id=payload[47],
        random_value=payload[48:50],
        max_current_raw=h(50, 53),
        persistent_id=payload[53:61],
        watchdog_current_raw=h(61, 64),
        watchdog_time_raw=h(64, 67),
        p1_current=round(h(67, 70) / 10, 1),
        p2_current=round(h(70, 73) / 10, 1),
        p3_current=round(h(73, 76) / 10, 1),
        eco7_switch=payload[76],
    )
