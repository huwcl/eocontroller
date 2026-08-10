"""
dump_state.py

Diagnostic tool - NOT part of the app itself. Run this directly on the Pi
over SSH to log every field from the charger, once a second, to a CSV.
Use it to eyeball which fields move and correlate them against something
you can observe physically (plug in/out, charging start, elapsed time).

Usage:
    python3 dump_state.py [amps] [duration_seconds]

    python3 dump_state.py          # defaults: 6A, runs until Ctrl+C
    python3 dump_state.py 16 300   # requests 16A, runs for 5 minutes

Safety note: this only calls set_limit() with a fixed, sane amps value on
a timer - it never changes the requested current mid-run and never sends
anything outside the normal protocol. If in doubt, run it with amps=0,
which just polls state without asking the board to charge at all.
"""

import sys
import csv
import time
import dataclasses
from datetime import datetime

sys.path.insert(0, "..")  # allow running this file directly from scripts/
from comms import EoCharger, ChargerCommsError

POLL_INTERVAL_SECONDS = 1.0
LOG_PATH = "charger_state_log.csv"


def main():
    amps = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    duration = float(sys.argv[2]) if len(sys.argv) > 2 else None

    print(f"Connecting to controller board, will request {amps}A per poll...")
    charger = EoCharger()
    charger.discover()
    print(f"Connected. Board address: {charger.address}")
    print(f"Logging to {LOG_PATH} every {POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.\n")

    fieldnames = ["timestamp", "site_current", "vehicle_current", "solar_current"]
    fieldnames += [f.name for f in dataclasses.fields(charger.set_limit(amps).state.__class__)]

    start = time.monotonic()
    with open(LOG_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        while duration is None or (time.monotonic() - start) < duration:
            try:
                result = charger.set_limit(amps)
            except ChargerCommsError as e:
                print(f"  comms error, skipping this poll: {e}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            row = {
                "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                "site_current": result.site_current,
                "vehicle_current": result.vehicle_current,
                "solar_current": result.solar_current,
                **dataclasses.asdict(result.state),
            }
            writer.writerow(row)
            f.flush()

            print(
                f"  state={result.state.charger_state_name:<22} "
                f"plug={result.state.plug_state} "
                f"p1={result.state.p1_current}A "
                f"site={result.site_current}A "
                f"vehicle_ct={result.vehicle_current}A "
                f"solar={result.solar_current}A "
                f"hub_duty_limit={result.state.hub_duty_limit_amps}A "
                f"max_current_raw={result.state.max_current_raw} "
            )

            time.sleep(POLL_INTERVAL_SECONDS)

    print(f"\nDone. Full log written to {LOG_PATH}")


if __name__ == "__main__":
    main()
