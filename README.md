# iRacing Copilot

Foundational telemetry/setup-reading layer for a voice-driven race-engineer
assistant, built on [pyirsdk](https://github.com/kutu/pyirsdk).

## Requires

- Windows, with iRacing installed and running - the SDK connects to local
  shared memory that iRacing only exposes on Windows while the sim is
  running. (`--test` mode below lets you develop on non-Windows machines
  against a recorded snapshot instead.)
- Python 3.7+

## Install

    pip install -r requirements.txt

## What's here

- `iracing_copilot/session.py` - connection lifecycle: connects to iRacing,
  detects disconnects/restarts, throttles reconnect attempts.
- `iracing_copilot/telemetry.py` - polls live telemetry every tick and
  buckets it into a rolling per-lap buffer (`get_current_lap()`,
  `get_last_completed_lap()`, `recent_samples(seconds)`). Needed because
  iRacing's shared memory only exposes the latest tick, not history.
- `iracing_copilot/car_setup.py` - reads the car's current setup
  (`ir['CarSetup']`) with change detection, so callers only react when the
  driver actually applies a setup change in the garage.
- `iracing_copilot/channels.py` - the default telemetry channel list. Some
  cars expose extra car-specific channels not included here - inspect
  `ir.var_headers_names` at runtime to discover them.
- `iracing_copilot/features.py` - turns a lap's raw samples into compact,
  labeled evidence for the LLM diagnosis step: corner segmentation off
  lateral G, brake lock-up and trail-braking detection, a simplified
  under/oversteer "tell" from steering-vs-yaw-rate behavior, and tire
  carcass-temp spread/balance. These are heuristic proxies, not a vehicle
  dynamics model - see the module docstring for the exact rules.
- `iracing_copilot/diagnosis.py` - sends a driver complaint + the lap's
  feature summary + the current car setup to Claude (Anthropic Messages
  API, structured output via Pydantic) and returns a validated
  `Diagnosis`: symptom summary, cited evidence, setup-change
  recommendations (addressed by the exact key path in `CarSetup`, since
  the schema differs per car), and caveats. Requires `ANTHROPIC_API_KEY`
  (or `ant auth login`) and **does incur real API cost per call**.
- `iracing_copilot/push_to_talk.py` - hold a hotkey (default F13, see the
  module docstring for why and how to remap a wheel/button-box button to
  it) to record audio, release to get it back as WAV bytes. Uses
  `sounddevice` + `pynput`, no admin rights needed on Windows.
- `iracing_copilot/speech_to_text.py` - transcribes that WAV audio via
  OpenAI's hosted Whisper endpoint (raw HTTP, not the `openai` SDK - see
  module docstring). Requires `OPENAI_API_KEY` and **incurs real API
  cost per recording**.
- `iracing_copilot/overlay.py` - an always-on-top window (plain `tkinter`,
  no extra dependency) logging every diagnosis, scrollable. Not iRacing's
  own in-sim chat - `ir.chat_command()` only reaches other drivers, not a
  private channel for this tool. Runs on the main thread; other components
  post to it through a thread-safe queue.
- `iracing_copilot/text_to_speech.py` - speaks each diagnosis aloud via
  `pyttsx3` (local/offline - SAPI5 on Windows), so it's free and has no
  network dependency, unlike the Whisper/Claude calls elsewhere in this
  project. Runs its own engine on a dedicated background thread, fed
  through a queue, since `pyttsx3` engines aren't thread-safe.
- `iracing_copilot/cli_format.py` - shared `Diagnosis` formatting:
  `format_diagnosis()` (full text, for the terminal/overlay) and
  `speakable_diagnosis()` (a short natural-language version for TTS, which
  skips key paths and caveats since those read poorly out loud).

## Try it

With iRacing running (in a car, on track or in the garage):

    python scripts/run_logger.py

To develop without iRacing running, dump a shared-memory snapshot once while
connected, then replay it:

    python -m irsdk --dump snapshot.bin
    python scripts/run_logger.py --test snapshot.bin

To exercise the full pipeline (telemetry -> features -> setup -> Claude diagnosis) after each completed lap, with `ANTHROPIC_API_KEY` set:

    python scripts/diagnose_last_lap.py

For the full voice pipeline - push-to-talk capture -> Whisper transcription
-> Claude diagnosis -> spoken + on-screen overlay delivery - with both
`OPENAI_API_KEY` and `ANTHROPIC_API_KEY` set:

    python scripts/ptt_copilot.py

(On macOS, granting your terminal/Python Microphone and Input Monitoring
permissions is required for mic capture and the global hotkey listener;
on the Windows deployment target neither needs elevated permissions. Also
on macOS: if your Python build lacks `tkinter`/Tk support, the overlay
window will fail to open - a python.org installer build has it built in,
which is also what a typical Windows Python install includes.)

## Known limitations

- The iRacing SDK can only *read* the car setup - there is no command to
  write values back into the garage. Recommendations from this project
  need to be applied by the driver manually in-game.
- `diagnose()` and `transcribe_whisper_api()` each call a paid API on
  every use (Claude and OpenAI Whisper respectively) - there is no local/
  offline mode for those two steps. Text-to-speech delivery is local and
  free.
