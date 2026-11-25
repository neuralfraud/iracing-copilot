#!/usr/bin/env python3
"""Smoke-test / demo entry point: connects to iRacing, logs telemetry into a
rolling per-lap buffer, and prints the car setup whenever it changes.

Usage:
    python scripts/run_logger.py              # connect to a live, running iRacing session
    python scripts/run_logger.py --test FILE  # replay a dumped shared-memory snapshot

To create a snapshot for --test while iRacing is running:
    python -m irsdk --dump snapshot.bin
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iracing_copilot.car_setup import CarSetupReader
from iracing_copilot.session import IRacingSession
from iracing_copilot.telemetry import TelemetryLogger

POLL_HZ = 20


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", help="replay a dumped irsdk shared-memory file instead of connecting live")
    args = parser.parse_args()

    session = IRacingSession(test_file=args.test)
    telemetry = TelemetryLogger(session.ir)
    car_setup = CarSetupReader(session.ir)

    print("waiting for iRacing...")
    last_lap_printed = None

    try:
        while True:
            if session.poll_connection():
                print("connected" if session.is_connected else "disconnected")

            if session.is_connected:
                sample = telemetry.poll()

                setup = car_setup.poll_for_update()
                if setup is not None:
                    print(f"\ncar setup changed (update count {setup.get('UpdateCount')}):")
                    print(setup)

                if sample is not None and sample.get("Lap") != last_lap_printed:
                    last_lap_printed = sample.get("Lap")
                    speed = sample.get("Speed")
                    speed_str = f"{speed:.1f} m/s" if speed is not None else "n/a"
                    print(f"\non lap {last_lap_printed}, speed={speed_str}")

            time.sleep(1 / POLL_HZ)
    except KeyboardInterrupt:
        pass
    finally:
        session.shutdown()


if __name__ == "__main__":
    main()
