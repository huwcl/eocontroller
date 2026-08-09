"""
backend.comms

RS485 communications layer for the EO Mini Pro 2 charger. Import EoCharger
from here - everything else in this package is an internal building block.
"""

from .charger import EoCharger, ChargerCommsError, PollResult
from .protocol import ChargerState, ChargerStateId

__all__ = [
    "EoCharger",
    "ChargerCommsError",
    "PollResult",
    "ChargerState",
    "ChargerStateId",
]