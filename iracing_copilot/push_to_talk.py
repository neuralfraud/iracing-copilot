"""Push-to-talk audio capture: hold a hotkey to record, release to get the
recording back as WAV bytes ready for transcription.

Uses sounddevice for capture and pynput for the global hotkey - both work
without admin rights on Windows (the deployment target, since that's where
iRacing runs), unlike some global-hotkey libraries.

Note on wheels/button boxes: this listens for a *keyboard* key, not a
joystick button. To push-to-talk from a wheel or button box, map that
button to a keyboard key in your wheel's own software (Logitech G HUB,
Fanatec FanaLab, Simagic, etc. all support this) - that's the standard way
sim-racing tools handle this rather than talking to DirectInput directly.
"""

import io
import threading
import wave

import numpy as np
import sounddevice as sd
from pynput import keyboard

SAMPLE_RATE = 16000  # what most STT APIs expect/prefer
CHANNELS = 1
DTYPE = "int16"

# F13+ keys don't exist on most physical keyboards, so they never collide
# with anything else - the same reason push-to-talk tools commonly default
# to them. Remap via your wheel software to whatever key you'd rather hold.
DEFAULT_HOTKEY = keyboard.Key.f13


class PushToTalkRecorder:
    """on_recording(wav_bytes) is called once per hold-and-release cycle."""

    def __init__(self, on_recording, hotkey=DEFAULT_HOTKEY, device=None, stream_factory=sd.InputStream):
        self.on_recording = on_recording
        self.hotkey = hotkey
        self.device = device
        self._stream_factory = stream_factory

        self._stream = None
        self._frames = []
        self._lock = threading.Lock()
        self._recording = False
        self._listener = None

    def start(self):
        """Arms the global hotkey listener. Non-blocking (runs its own thread)."""
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._teardown_stream()

    def _on_press(self, key):
        if key == self.hotkey and not self._recording:
            self._start_recording()

    def _on_release(self, key):
        if key == self.hotkey and self._recording:
            self._stop_recording()

    def _start_recording(self):
        with self._lock:
            self._recording = True
            self._frames = []

        self._stream = self._stream_factory(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()

    def _audio_callback(self, indata, frames, time_info, status):
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())

    def _stop_recording(self):
        with self._lock:
            self._recording = False

        self._teardown_stream()

        with self._lock:
            frames, self._frames = self._frames, []

        if not frames:
            return

        audio = np.concatenate(frames, axis=0)
        self.on_recording(_to_wav_bytes(audio, SAMPLE_RATE))

    def _teardown_stream(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def _to_wav_bytes(audio, sample_rate):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)  # int16 = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio.tobytes())
    return buf.getvalue()
