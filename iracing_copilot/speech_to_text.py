"""Speech-to-text: turns recorded WAV audio (from push_to_talk) into text.

Local/offline via faster-whisper (a CTranslate2 reimplementation of
Whisper) is the default - no API key, no per-call cost, and no network
dependency once the model has been downloaded once (cached under
~/.cache/huggingface, or HF_HOME, by default). This replaces the OpenAI
Whisper API call previously used here, which needed its own paid key
separate from Claude's.

transcribe_whisper_api() (OpenAI's hosted endpoint) is kept as an opt-in
alternative - e.g. to avoid local CPU/GPU load on a lower-spec machine -
requires OPENAI_API_KEY and incurs real per-call cost.
"""

import io
import os
import threading

import requests
from faster_whisper import WhisperModel

WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"

DEFAULT_MODEL_SIZE = "base"  # tiny/base/small/medium/large-v3 - bigger = more accurate, slower

_model_lock = threading.Lock()
_model = None


class TranscriptionError(RuntimeError):
    """Raised when transcription fails."""


def transcribe_local_whisper(
    wav_bytes, language="en", model_size=None, device="cpu", compute_type="int8", model_factory=WhisperModel
):
    """Transcribe WAV audio with a local faster-whisper model.

    The model loads once per process (lazily, on first call) and is reused
    after that - the very first call ever made on a machine also downloads
    the model, which needs network access that one time; every call after
    that is fully offline. `model_size`/`device`/`compute_type` only take
    effect on that first call; set the `WHISPER_MODEL_SIZE` env var to
    change the default model size without touching code. `language=None`
    lets Whisper auto-detect, at the cost of a little latency and accuracy
    on very short clips - pin it when you know the driver's language.
    """
    model = _get_model(
        model_size or os.environ.get("WHISPER_MODEL_SIZE", DEFAULT_MODEL_SIZE),
        device,
        compute_type,
        model_factory,
    )

    try:
        segments, _info = model.transcribe(io.BytesIO(wav_bytes), language=language)
        return " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as e:
        raise TranscriptionError(f"local transcription failed: {e}") from e


def preload_model(model_size=None, device="cpu", compute_type="int8", model_factory=WhisperModel):
    """Load (and cache) the local model now instead of lazily on the first
    transcribe_local_whisper() call - call this once at startup so the
    first push-to-talk isn't slowed down by model load (or, on a fresh
    machine, the one-time download)."""
    _get_model(
        model_size or os.environ.get("WHISPER_MODEL_SIZE", DEFAULT_MODEL_SIZE),
        device,
        compute_type,
        model_factory,
    )


def _get_model(model_size, device, compute_type, model_factory):
    global _model
    with _model_lock:
        if _model is None:
            _model = model_factory(model_size, device=device, compute_type=compute_type)
    return _model


def transcribe_whisper_api(wav_bytes, api_key=None, model="whisper-1", timeout=30):
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError("OPENAI_API_KEY not set and no api_key provided")

    try:
        response = requests.post(
            WHISPER_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("push_to_talk.wav", wav_bytes, "audio/wav")},
            data={"model": model},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise TranscriptionError(f"could not reach Whisper API: {e}") from e

    if response.status_code != 200:
        raise TranscriptionError(f"Whisper API error ({response.status_code}): {response.text}")

    return response.json()["text"].strip()
