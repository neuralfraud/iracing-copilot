#!/usr/bin/env python3
"""End-to-end demo: hold the push-to-talk hotkey, speak your complaint about
the car, and get Claude's structured setup diagnosis back - spoken aloud
immediately (text-to-speech) and logged in an always-on-top overlay window
you can scroll back through, grounded in the last completed lap's telemetry
features and the car's current setup.

Requires OPENAI_API_KEY (speech-to-text, real cost per recording) and Claude
authenticated for diagnosis - either ANTHROPIC_API_KEY (also real cost per
call) or a Claude.ai subscription login (`ant auth login` / Claude Code
`/login`, draws from that plan's usage instead); see README.md's
"Authenticating Claude" section. Text-to-speech is local/offline and free
(see iracing_copilot/text_to_speech.py).

tkinter (the overlay) owns the main thread and its mainloop; telemetry
polling and recording processing run on background threads and only ever
reach the overlay through its thread-safe `post()` queue.

Default hotkey is F13 (see iracing_copilot/push_to_talk.py for why, and how
to map a wheel/button-box button to it).

Usage:
    python scripts/ptt_copilot.py
    python scripts/ptt_copilot.py --test snapshot.bin
"""

import argparse
import os
import queue
import sys
import threading
import time

_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "lib", "pyirsdk"))  # vendored irsdk.py - see lib/pyirsdk/VENDORED.md
sys.path.insert(0, _PROJECT_ROOT)

from iracing_copilot.car_setup import CarSetupReader
from iracing_copilot.cli_format import format_diagnosis, print_diagnosis, speakable_diagnosis
from iracing_copilot.diagnosis import DiagnosisError, diagnose
from iracing_copilot.features import extract_lap_features
from iracing_copilot.overlay import Overlay
from iracing_copilot.push_to_talk import PushToTalkRecorder
from iracing_copilot.session import IRacingSession
from iracing_copilot.speech_to_text import TranscriptionError, transcribe_whisper_api
from iracing_copilot.telemetry import TelemetryLogger
from iracing_copilot.text_to_speech import TextToSpeechWorker

POLL_HZ = 20


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", help="replay a dumped irsdk shared-memory file instead of connecting live")
    args = parser.parse_args()

    session = IRacingSession(test_file=args.test)
    telemetry = TelemetryLogger(session.ir)
    car_setup = CarSetupReader(session.ir)

    overlay = Overlay()
    tts = TextToSpeechWorker()
    tts.start()

    shutdown = threading.Event()
    threading.Thread(
        target=_poll_telemetry_loop, args=(session, telemetry, shutdown), daemon=True
    ).start()

    # Push-to-talk releases fire on pynput's listener thread; hand recordings
    # off to a worker thread so transcription/diagnosis network calls never
    # block the hotkey listener, the telemetry poll loop, or the overlay.
    work_queue = queue.Queue()
    threading.Thread(
        target=_process_recordings, args=(work_queue, telemetry, car_setup, overlay, tts), daemon=True
    ).start()

    recorder = PushToTalkRecorder(on_recording=work_queue.put)
    recorder.start()

    overlay.post(f"ready - hold {recorder.hotkey} and speak to get setup feedback")

    try:
        overlay.run()  # blocks on the Tk mainloop until the window is closed
    finally:
        shutdown.set()
        recorder.stop()
        tts.stop()
        session.shutdown()


def _poll_telemetry_loop(session, telemetry, shutdown):
    while not shutdown.is_set():
        session.poll_connection()
        if session.is_connected:
            telemetry.poll()
        time.sleep(1 / POLL_HZ)


def _process_recordings(work_queue, telemetry, car_setup, overlay, tts):
    while True:
        wav_bytes = work_queue.get()

        try:
            complaint = transcribe_whisper_api(wav_bytes)
        except TranscriptionError as e:
            overlay.post(f"couldn't transcribe: {e}")
            continue

        overlay.post(f'heard: "{complaint}"')

        setup = car_setup.read()
        if not setup:
            overlay.post("no car setup available yet - get in the car/garage")
            continue

        lap_samples = telemetry.get_last_completed_lap() or telemetry.get_current_lap()
        if not lap_samples:
            overlay.post("no telemetry recorded yet - get on track first")
            continue

        features = extract_lap_features(lap_samples).to_dict()

        try:
            result = diagnose(complaint, features, setup)
        except DiagnosisError as e:
            overlay.post(f"diagnosis failed: {e}")
            continue

        print_diagnosis(result)  # terminal log, in addition to the overlay/voice
        overlay.post(format_diagnosis(result))
        tts.say(speakable_diagnosis(result))


if __name__ == "__main__":
    main()
