"""
ade7858.py

Driver for the ADE7858 3-phase energy measurement IC, wired on a separate
SPI bus/CS to the same Pi Zero. This chip reads the site, vehicle, and
solar CT clamps independently of the RS485 link to the control board -
it's a completely separate measurement path.

Calibration (gain/offset) is intentionally NOT applied here. This module
returns raw amps as measured by the chip; scaling those against a
reference meter is a config-layer concern, not a hardware-driver one.
"""

import time
import logging

import spidev
import RPi.GPIO as GPIO

_LOGGER = logging.getLogger(__name__)

PIN_IRQ0 = 20     # Chip interrupt line (not currently used, wired for future use)
PIN_NRESET = 22   # Chip reset line
PIN_PM1 = 17      # Chip power mode select

_SPI_BUS = 0
_SPI_DEVICE = 1
_SPI_SPEED_HZ = 1_000_000
_SPI_MODE = 0b11

# Control/config registers used during setup.
REG_RUN = 0xE228       # Start/stop the DSP
REG_CFMODE = 0xE610    # Waveform/CF output mode
REG_CONFIG = 0xE618    # General configuration
REG_HPFDIS = 0x43B6    # High-pass filter disable
REG_GAIN = 0xE60F      # Analog input gain

# Per-phase current gain and RMS offset registers.
REG_AIGAIN = 0x4380
REG_BIGAIN = 0x4382
REG_CIGAIN = 0x4384

REG_AIRMSOS = 0x4387
REG_BIRMSOS = 0x4389
REG_CIRMSOS = 0x438B

# RMS current readback registers - what we actually poll for CT readings.
REG_AIRMS = 0x43C0  # Site CT
REG_BIRMS = 0x43C2  # Vehicle CT
REG_CIRMS = 0x43C4  # Solar CT

# Fixed config values taken from the working openeo setup. These aren't
# independently derived - they're the manufacturer/vendor defaults the
# original project used, kept as-is to avoid changing chip behaviour we
# haven't independently verified.
_RMS_OFFSET = 0x0002E45C
_GAIN = 0x0FE6060C

# RMS reading -> amps. The chip reports RMS current as a raw integer;
# dividing by this constant converts it to amps.
_RMS_TO_AMPS_DIVISOR = 10000


class Ade7858:
    """Reads site/vehicle/solar CT clamp currents from the ADE7858."""

    def __init__(self):
        self._setup_gpio()
        self._spi = spidev.SpiDev()
        self._spi.open(_SPI_BUS, _SPI_DEVICE)
        self._spi.max_speed_hz = _SPI_SPEED_HZ
        self._spi.mode = _SPI_MODE
        self._wake_spi_interface()
        self._configure()
        _LOGGER.debug("ADE7858 initialised")

    def _setup_gpio(self):
        GPIO.setup(PIN_IRQ0, GPIO.IN)
        GPIO.setup(PIN_NRESET, GPIO.OUT)
        GPIO.setup(PIN_PM1, GPIO.OUT)

        GPIO.output(PIN_PM1, GPIO.LOW)
        GPIO.output(PIN_NRESET, GPIO.HIGH)
        time.sleep(0.001)
        GPIO.output(PIN_NRESET, GPIO.LOW)
        time.sleep(0.001)
        GPIO.output(PIN_NRESET, GPIO.HIGH)
        time.sleep(0.02)

    def _wake_spi_interface(self):
        # The chip's SPI interface needs a few dummy transfers after reset
        # before it will respond to real register access.
        for _ in range(3):
            self._spi.xfer2([0x00])
            time.sleep(0.001)

    def reg_read(self, register: int, size: int = 4) -> int:
        """Read `size` bytes (1-4) from a 2-byte-addressed register."""
        assert 1 <= size <= 4
        request = [0x01] + list(register.to_bytes(2, "big")) + [0x00] * size
        response = self._spi.xfer2(request)[3:]
        return int.from_bytes(response, "big", signed=False)

    def reg_write(self, register: int, value: int, size: int = 4):
        """Write `size` bytes (1-4) to a 2-byte-addressed register."""
        assert 1 <= size <= 4
        request = [0x00] + list(register.to_bytes(2, "big")) + list(value.to_bytes(size, "big"))
        self._spi.xfer2(request)

    def _configure(self):
        """Bring the chip up with the known-good config values, then
        verify each one was actually accepted before starting the DSP."""
        config = (
            (REG_CFMODE, 0x0E88, 2),
            (REG_CONFIG, 0, 2),
            (REG_HPFDIS, 0, 4),
            (REG_GAIN, 0, 2),
            (REG_AIGAIN, _GAIN, 4),
            (REG_BIGAIN, _GAIN, 4),
            (REG_CIGAIN, _GAIN, 4),
            (REG_AIRMSOS, _RMS_OFFSET, 4),
            (REG_BIRMSOS, _RMS_OFFSET, 4),
            (REG_CIRMSOS, _RMS_OFFSET, 4),
        )

        self.reg_write(REG_RUN, 0, 2)  # stop the DSP while we configure it

        for register, value, size in config:
            self.reg_write(register, value, size)

        # Write the last setting twice - the DSP pipeline needs a second
        # write to pick up the final value (behaviour carried over from
        # the original driver; not independently explained by the
        # datasheet excerpts we have).
        last = config[-1]
        self.reg_write(*last)
        self.reg_write(*last)

        for register, expected, size in config:
            actual = self.reg_read(register, size)
            if actual != expected:
                _LOGGER.error("ADE7858 register 0x%04X did not accept expected value", register)

        self.reg_write(REG_RUN, 1, 2)  # start the DSP

    def read_currents(self) -> dict[str, float]:
        """Return the three CT clamp readings in amps, uncalibrated."""
        return {
            "site": self.reg_read(REG_AIRMS, 4) / _RMS_TO_AMPS_DIVISOR,
            "vehicle": self.reg_read(REG_BIRMS, 4) / _RMS_TO_AMPS_DIVISOR,
            "solar": self.reg_read(REG_CIRMS, 4) / _RMS_TO_AMPS_DIVISOR,
        }