#!/usr/bin/env python3
"""End-to-end demo: hold the push-to-talk hotkey, speak your complaint about
the car, and get Claude's structured setup diagnosis back - spoken aloud
immediately (text-to-speech) and logged in an always-on-top overlay window
you can scroll back through, grounded in the last completed lap's telemetry
features and the car's current setup.

One run of this script is one DiagnosisSession (iracing_copilot/diagnosis.py):
every complaint in the session is a new turn in the same conversation with
Claude, not a fresh context-free call, so it can track what's already been
tried and how the car's behavior is evolving across the session.

Speech-to-text is local/offline (faster-whisper) and free, same as
text-to-speech - no OpenAI key needed (see iracing_copilot/speech_to_text.py;
the very first run ever on a machine downloads the model, needing network
access that one time only). Claude needs an ANTHROPIC_API_KEY - a Claude.ai
Pro/Max/Team *subscription* login is not sufficient on its own (confirmed in
practice: it returns 429s on Messages API calls), so this needs a separate
Anthropic Console API key regardless of what chat plan you already have.

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
from iracing_copilot.diagnosis import DiagnosisError, DiagnosisSession
from iracing_copilot.features import extract_lap_features
from iracing_copilot.overlay import Overlay
from iracing_copilot.push_to_talk import PushToTalkRecorder
from iracing_copilot.session import IRacingSession
from iracing_copilot.speech_to_text import TranscriptionError, preload_model, transcribe_local_whisper
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

    # One DiagnosisSession for this whole process run - every complaint this
    # session hears is a turn in the same conversation with Claude.
    diagnosis_session = DiagnosisSession()

    shutdown = threading.Event()
    threading.Thread(
        target=_poll_telemetry_loop, args=(session, telemetry, shutdown), daemon=True
    ).start()

    # Push-to-talk releases fire on pynput's listener thread; hand recordings
    # off to a worker thread so transcription/diagnosis calls never block the
    # hotkey listener, the telemetry poll loop, or the overlay.
    work_queue = queue.Queue()
    recorder = PushToTalkRecorder(on_recording=work_queue.put)

    threading.Thread(
        target=_process_recordings,
        args=(work_queue, telemetry, car_setup, overlay, tts, recorder.hotkey, diagnosis_session),
        daemon=True,
    ).start()

    recorder.start()

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


def _process_recordings(work_queue, telemetry, car_setup, overlay, tts, hotkey, diagnosis_session):
    overlay.post("loading local speech-to-text model (first run may need to download it)...")
    preload_model()
    overlay.post(f"ready - hold {hotkey} and speak to get setup feedback")

    while True:
        wav_bytes = work_queue.get()

        try:
            complaint = transcribe_local_whisper(wav_bytes)
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
            result = diagnosis_session.ask(complaint, features, setup)
        except DiagnosisError as e:
            overlay.post(f"diagnosis failed: {e}")
            continue

        print_diagnosis(result)  # terminal log, in addition to the overlay/voice
        overlay.post(format_diagnosis(result))
        tts.say(speakable_diagnosis(result))


if __name__ == "__main__":
    main()
