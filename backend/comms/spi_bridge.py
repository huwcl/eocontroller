"""
spi_bridge.py

Driver for the SPI-to-UART bridge chip that sits between the Pi Zero and
the RS485 transceiver on the EO Mini Pro 2 control board. The Pi Zero has
no native UART wired to the bus, so every byte we send or receive to the
control board goes: our code -> SPI -> bridge chip -> RS485 -> board.

This file only knows about that bridge chip. It has no idea what the bytes
it's moving mean - that's protocol.py's job.
"""

import time
import logging

import spidev
import RPi.GPIO as GPIO

_LOGGER = logging.getLogger(__name__)

# BCM GPIO pin wired to the bridge chip's reset line.
PIN_NRESET = 16

# Bridge chip register indices (this is a standard SPI-UART bridge
# register layout, e.g. SC16IS750-family).
REG_DLL = 0        # Divisor latch, low byte
REG_DLH = 1        # Divisor latch, high byte
REG_EFR = 2        # Enhanced features register
REG_FCR_IIR = 2    # FIFO control (write) / interrupt ID (read) - shares an index with EFR
REG_LCR = 3        # Line control (data bits, parity, stop bits, divisor access)
REG_MCR = 4        # Modem control
REG_LSR = 5        # Line status - bit 1 flags an RX overrun
REG_RXLVL = 9      # Number of bytes currently sitting in the RX FIFO
REG_EFCR = 15      # Extra features - RS485 direction control lives here

BIT_LSR_OVERRUN = 0x02

# Values written during init to bring the bridge up as 115200 8N1 with
# automatic RS485 direction switching. See __init__ for the sequence.
_BAUD_DIVISOR_LOW = 0x01
_BAUD_DIVISOR_HIGH = 0x00
_LCR_ENABLE_DIVISOR_ACCESS = 0x80
_LCR_ENHANCED_MODE = 0xBF
_LCR_8N1 = 0x03
_FCR_ENABLE_RESET_FIFOS = 0x07
_EFCR_RS485_AUTO_DIRECTION = 0x30

_SPI_BUS = 0
_SPI_DEVICE = 0
_SPI_SPEED_HZ = 1_000_000


class SpiRxOverrun(Exception):
    """Raised when the bridge chip's RX FIFO overran during a read - we
    were not pulling bytes out fast enough and some were lost. The caller
    should treat the response as unusable and retry."""


class SpiUartBridge:
    """Talks RS485 to the EO control board via the SPI-to-UART bridge.

    Usage:
        bridge = SpiUartBridge()
        bridge.tx("+15C")
        raw = bridge.rx(recv_delay=3)
    """

    def __init__(self):
        self._setup_reset_pin()
        self._spi = spidev.SpiDev()
        self._spi.open(_SPI_BUS, _SPI_DEVICE)
        self._spi.max_speed_hz = _SPI_SPEED_HZ
        self._configure_bridge()
        _LOGGER.debug("SPI-UART bridge initialised (115200 8N1, RS485 auto-direction)")

    def _setup_reset_pin(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIN_NRESET, GPIO.OUT)
        # Pulse reset low then high - the chip needs a clean reset before
        # any register access will behave predictably.
        GPIO.output(PIN_NRESET, GPIO.LOW)
        time.sleep(0.001)
        GPIO.output(PIN_NRESET, GPIO.HIGH)

    def _register_write(self, register: int, value: int):
        # Register address is shifted left 3 bits for a write; read sets
        # the top bit as well (see _register_read).
        addr = register << 3
        self._spi.xfer2([addr, value])

    def _register_read(self, register: int) -> int:
        addr = (register << 3) | 0x80
        response = self._spi.xfer2([addr, 0x00])
        return response[1]

    def _configure_bridge(self):
        """Register sequence to bring the bridge up as 115200 8N1 with
        RS485 auto-direction control. Order matters - LCR has to be put
        into divisor-access mode before the baud divisor registers are
        writable, then switched to enhanced mode for EFR, then back to
        normal 8N1 framing."""
        self._register_write(REG_LCR, _LCR_ENABLE_DIVISOR_ACCESS)
        self._register_write(REG_DLL, _BAUD_DIVISOR_LOW)
        self._register_write(REG_DLH, _BAUD_DIVISOR_HIGH)
        self._register_write(REG_LCR, _LCR_ENHANCED_MODE)
        self._register_write(REG_EFR, 0x00)
        self._register_write(REG_LCR, _LCR_8N1)
        self._register_write(REG_FCR_IIR, _FCR_ENABLE_RESET_FIFOS)
        self._register_write(REG_EFCR, _EFCR_RS485_AUTO_DIRECTION)

    def tx(self, packet: str):
        """Send an ASCII packet, terminated with \\r as the protocol
        requires. Resets the FIFOs first so a stale byte from a previous
        exchange can't get mixed into this one."""
        self._register_write(REG_FCR_IIR, _FCR_ENABLE_RESET_FIFOS)
        payload = [0] + list(packet.encode("ascii")) + [13]  # 13 = '\r'
        self._spi.xfer2(payload)

    def rx(self, recv_delay: float = 3.0) -> bytes | None:
        """Read whatever comes back within `recv_delay` seconds. Returns
        None if an RX overrun was detected during the read - the data is
        not trustworthy at that point and should be discarded, not
        partially used.
        """
        data = b""
        deadline = time.monotonic() + recv_delay
        overrun_count = 0

        while time.monotonic() < deadline:
            bytes_waiting = self._register_read(REG_RXLVL)

            if bytes_waiting > 0:
                # First byte of the xfer is the read-address byte we sent;
                # the FIFO contents come back starting at index 1.
                request = [0x80] + [0x00] * bytes_waiting
                data += bytes(self._spi.xfer2(request)[1:])

                if self._register_read(REG_LSR) & BIT_LSR_OVERRUN:
                    _LOGGER.warning("RS485 overrun detected during rx()")
                    overrun_count += 1
            else:
                time.sleep(0.001)

        if overrun_count > 0:
            return None
        return data