"""
config.py

Loads backend/config.toml. This is for startup/runtime settings only -
NOT charge session logs (that's db/sessions.db, see session_logger.py)
and not hardware-protocol constants (that's comms/protocol.py).

If config.toml doesn't exist, or a key is missing, sane defaults are
used rather than raising - a missing config file shouldn't stop the
service from starting.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.toml"


@dataclass
class Config:
    # Amps requested automatically every time the poller starts - on
    # service boot, a manual restart, AND a crash-triggered restart
    # (systemd's Restart=always doesn't distinguish between them).
    # Defaults to 0 (don't charge) if unset, so a missing or incomplete
    # config file never accidentally commands full power on its own.
    startup_amps: float = 0.0


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return Config()

    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)

    charging = data.get("charging", {})
    return Config(
        startup_amps=charging.get("startup_amps", 0.0),
    )
