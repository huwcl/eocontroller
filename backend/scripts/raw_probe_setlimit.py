"""
raw_probe_setlimit.py

Same idea as raw_probe.py, but for the SET_LIMIT response - the frame our
field map (protocol.parse_state_frame) is currently getting wrong. Prints
the raw response alongside a position ruler so field boundaries can be
counted by hand against what we expected.

Run with sudo, same as the other scripts. Requests 0A so nothing actually
changes on the charger - this is read-only in effect.
"""

import sys
sys.path.insert(0, "..")

from comms.spi_bridge import SpiUartBridge
from comms import protocol

bridge = SpiUartBridge()

# --- DISCOVER first, same as raw_probe.py, to get a real address ---
bridge.tx(protocol.DISCOVER_PACKET)
raw = bridge.rx(recv_delay=3.0)
text = raw.decode("ascii")
address = text[1:-3]
print(f"Discovered address: {address!r}\n")

# --- Now SET_LIMIT at 0A ---
packet = protocol.build_set_limit_packet(address, 0)
print(f"Sending: {packet!r}")
bridge.tx(packet)
raw = bridge.rx(recv_delay=0.5)

print(f"Raw bytes:  {raw!r}")
print(f"Length:     {len(raw) if raw else 0}")

if raw:
    text = raw.decode("ascii")
    print(f"Hex:        {raw.hex(' ')}")
    print()
    # Print the text with a position ruler underneath, in blocks of 10,
    # so field boundaries can be counted by hand.
    print("Position ruler (each column = 1 character):")
    print(text)
    ruler_tens = "".join(str((i // 10) % 10) for i in range(len(text)))
    ruler_ones = "".join(str(i % 10) for i in range(len(text)))
    print(ruler_tens)
    print(ruler_ones)
