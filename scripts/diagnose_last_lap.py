#!/usr/bin/env python3
"""Demo: connect to iRacing, and after each completed lap take a typed
driver complaint (a stand-in for the push-to-talk/STT step, which comes
later) and print Claude's structured setup diagnosis.

This makes a real Claude API call and will incur usage cost - requires
ANTHROPIC_API_KEY (or `ant auth login`) to be configured.

Usage:
    python scripts/diagnose_last_lap.py
    python scripts/diagnose_last_lap.py --test snapshot.bin
"""

import argparse
import os
import sys
import time

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "lib", "pyirsdk"))  # vendored irsdk.py - see lib/pyirsdk/VENDORED.md
sys.path.insert(0, _PROJECT_ROOT)

from iracing_copilot.car_setup import CarSetupReader
from iracing_copilot.cli_format import print_diagnosis
from iracing_copilot.diagnosis import DiagnosisError, diagnose
from iracing_copilot.features import extract_lap_features
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

    print("waiting for iRacing... (Ctrl+C to quit)")
    last_completed_seen = None

    try:
        while True:
            session.poll_connection()

            if session.is_connected:
                telemetry.poll()
                completed_lap = telemetry.get_last_completed_lap()

                if completed_lap and completed_lap[-1].get("Lap") != last_completed_seen:
                    last_completed_seen = completed_lap[-1].get("Lap")
                    _run_diagnosis(completed_lap, car_setup.read())

            time.sleep(1 / POLL_HZ)
    except KeyboardInterrupt:
        pass
    finally:
        session.shutdown()


def _run_diagnosis(lap_samples, setup):
    if not setup:
        print("\n(no car setup available yet - get in the car/garage)")
        return

    print(f"\nlap {lap_samples[-1].get('Lap')} complete. How did that feel? (blank to skip)")
    complaint = input("> ").strip()
    if not complaint:
        return

    features = extract_lap_features(lap_samples).to_dict()

    try:
        result = diagnose(complaint, features, setup)
    except DiagnosisError as e:
        print(f"diagnosis failed: {e}")
        return

    print_diagnosis(result)


if __name__ == "__main__":
    main()
