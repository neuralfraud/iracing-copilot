"""Local, offline text-to-speech for spoken delivery of diagnoses.

Uses pyttsx3 (SAPI5 on Windows, NSSpeechSynthesizer on macOS, espeak on
Linux) rather than a cloud TTS API - no API key, no per-call cost, and low
enough latency for in-car feedback, unlike the paid Whisper/Claude calls
elsewhere in this project.

pyttsx3 engines aren't thread-safe or reentrant - TextToSpeechWorker owns a
single engine on one dedicated background thread and feeds it through a
queue, so callers never touch the engine directly or call speak()
concurrently.
"""

import queue
import threading

import pyttsx3


class TextToSpeechWorker:
    def __init__(self, rate=None, voice_id=None, engine_factory=pyttsx3.init):
        self._queue = queue.Queue()
        self._rate = rate
        self._voice_id = voice_id
        self._engine_factory = engine_factory
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def say(self, text):
        """Thread-safe: call from any thread to enqueue text to be spoken."""
        self._queue.put(text)

    def stop(self):
        self._queue.put(None)

    def _run(self):
        engine = self._engine_factory()
        if self._rate is not None:
            engine.setProperty("rate", self._rate)
        if self._voice_id is not None:
            engine.setProperty("voice", self._voice_id)

        while True:
            text = self._queue.get()
            if text is None:
                break
            engine.say(text)
            engine.runAndWait()
