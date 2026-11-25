"""Speech-to-text: turns recorded WAV audio (from push_to_talk) into text.

Claude's API doesn't do audio transcription, so this calls OpenAI's hosted
Whisper transcription endpoint directly over HTTP rather than pulling in the
`openai` SDK - keeps the dependency to just `requests` and avoids pinning to
a specific SDK's method signatures for a single REST call. Swap
`transcribe_whisper_api` for another provider by matching its
(wav_bytes) -> str signature.
"""

import os

import requests

WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"


class TranscriptionError(RuntimeError):
    """Raised when the STT API call fails."""


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
