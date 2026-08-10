"""
raw_probe.py

Bypasses everything except the SPI bridge itself. Sends the fixed DISCOVER
packet and prints exactly what comes back - as raw bytes, hex, and ascii -
so we can see what the board is actually sending before any parsing or
checksum logic touches it.

Run with sudo, same as dump_state.py.
"""

import sys
sys.path.insert(0, "..")

from comms.spi_bridge import SpiUartBridge
from comms import protocol

bridge = SpiUartBridge()

print(f"Sending: {protocol.DISCOVER_PACKET!r}")
bridge.tx(protocol.DISCOVER_PACKET)
raw = bridge.rx(recv_delay=3.0)

print(f"Raw bytes:  {raw!r}")
print(f"Length:     {len(raw) if raw else 0}")
if raw:
    print(f"Hex:        {raw.hex(' ')}")
    try:
        print(f"As ASCII:   {raw.decode('ascii')!r}")
    except UnicodeDecodeError as e:
        print(f"Not valid ASCII: {e}")
