# iRacing Copilot

Foundational telemetry/setup-reading layer for a voice-driven race-engineer
assistant, built on [pyirsdk](https://github.com/kutu/pyirsdk) (vendored
under `lib/pyirsdk/` - see below).

## Requires

- Windows, with iRacing installed and running - the SDK connects to local
  shared memory that iRacing only exposes on Windows while the sim is
  running. (`--test` mode below lets you develop on non-Windows machines
  against a recorded snapshot instead.)
- Python 3.7+

## Install

    pip install -r requirements.txt

`pyirsdk` itself is vendored (see below), not pip-installed - it isn't in
`requirements.txt`; everything in that file is `irsdk.py`'s own runtime
dependency (`PyYAML`) plus this project's other dependencies.

## Authenticating Claude: API key vs. your Claude subscription

`diagnosis.py` picks an auth path itself (`_build_default_client()`), in
this order:

1. **`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or `ANTHROPIC_PROFILE` env
   var set** - treated as "you configured this on purpose," so it's left
   entirely to the Anthropic SDK's own resolution. `ANTHROPIC_API_KEY` is a
   separate Anthropic Console/platform API key, billed per token - a
   different kind of account from a Claude.ai chat subscription, created
   and funded separately. `ANTHROPIC_PROFILE` names a profile from
   `ant auth login` (the Anthropic CLI), stored under `~/.config/anthropic/`
   (`%APPDATA%\Anthropic` on Windows).
2. **Otherwise, Claude Code's own login** (`iracing_copilot/claude_code_credentials.py`)
   - read directly from Claude Code's credentials file,
   `~/.claude/.credentials.json` (`%USERPROFILE%\.claude\.credentials.json`
   on Windows). If you're already logged into Claude Code with a
   **Pro/Max/Team subscription**, this is it - no separate API key, no
   separate login step, nothing to set up. Usage draws from that
   subscription's own included usage instead of pay-per-token billing.
3. Otherwise, falls back to a plain `anthropic.Anthropic()` client, which
   surfaces the SDK's normal "not authenticated" error if nothing is
   configured at all.

So: if a Pro/Max/Team chat plan is what you have (per the brief above, the
common case vs. a separate developer/platform account) and you're already
logged into Claude Code **on the machine that actually runs the script**
(the Windows PC with iRacing), nothing further is needed - this just works.

Three things worth knowing:

- **This reads Claude Code's credentials file directly** - it re-reads it
  on every API call rather than caching the token, so if Claude Code
  refreshes it in the background you pick that up automatically; if
  nothing refreshes it and it actually expires, you'll get a clear error
  telling you to log in again (`claude_code_credentials.ClaudeCodeCredentialsError`,
  wrapped into `DiagnosisError`).
- **On macOS, Claude Code stores this in the OS Keychain instead of a
  plain file** - `claude_code_credentials.is_available()` will correctly
  report nothing found there, falling through to step 3 above. Use
  `ANTHROPIC_API_KEY` or `ant auth login` on macOS instead.
- **A stray `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_PROFILE`
  env var always wins**, even an empty one (`ANTHROPIC_API_KEY=""` still
  "wins" and then fails auth) - unset it if you want Claude Code's login
  used instead. And either way, it's the same usage pool as your other
  Claude Code/chat usage on that account, not a separate budget.

Speech-to-text is unrelated to this and local/offline by default (see
`iracing_copilot/speech_to_text.py` below) - no second API key needed.

## What's here

- `lib/pyirsdk/` - a verbatim, vendored copy of upstream
  [pyirsdk](https://github.com/kutu/pyirsdk) (MIT licensed), pinned to a
  known commit instead of pulled from PyPI - see `lib/pyirsdk/VENDORED.md`
  for why and its provenance. All of this project's scripts add it to
  `sys.path` before `import irsdk`; nothing else needs to change if you
  later modify it (e.g. to extend the `IBT` class so it also parses
  `CarSetup` from recorded `.ibt` files, which upstream doesn't do).
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
  the schema differs per car), and caveats. Picks an auth path itself -
  see "Authenticating Claude" above.
- `iracing_copilot/claude_code_credentials.py` - a custom credential
  provider for the Anthropic SDK (`Anthropic(credentials=...)`) that reads
  Claude Code's own login directly, so a Claude.ai subscription just works
  with no separate API key - see "Authenticating Claude" above for the
  full explanation.
- `iracing_copilot/push_to_talk.py` - hold a hotkey (default F13, see the
  module docstring for why and how to remap a wheel/button-box button to
  it) to record audio, release to get it back as WAV bytes. Uses
  `sounddevice` + `pynput`, no admin rights needed on Windows.
- `iracing_copilot/speech_to_text.py` - transcribes that WAV audio locally
  via `faster-whisper` by default: no API key, no per-call cost, no
  network dependency after the model's one-time download. `transcribe_whisper_api()`
  (OpenAI's hosted endpoint, raw HTTP) is kept as an opt-in alternative for
  lower-spec machines - requires `OPENAI_API_KEY` and incurs real cost
  per recording.
- `iracing_copilot/overlay.py` - an always-on-top window (plain `tkinter`,
  no extra dependency) logging every diagnosis, scrollable. Not iRacing's
  own in-sim chat - `ir.chat_command()` only reaches other drivers, not a
  private channel for this tool. Runs on the main thread; other components
  post to it through a thread-safe queue.
- `iracing_copilot/text_to_speech.py` - speaks each diagnosis aloud via
  `pyttsx3` (local/offline - SAPI5 on Windows), so it's free and has no
  network dependency, same as the local speech-to-text above (only the
  Claude diagnosis call needs the network). Runs its own engine on a
  dedicated background thread, fed through a queue, since `pyttsx3`
  engines aren't thread-safe.
- `iracing_copilot/cli_format.py` - shared `Diagnosis` formatting:
  `format_diagnosis()` (full text, for the terminal/overlay) and
  `speakable_diagnosis()` (a short natural-language version for TTS, which
  skips key paths and caveats since those read poorly out loud).

## Try it

With iRacing running (in a car, on track or in the garage):

    python scripts/run_logger.py

To develop without iRacing running, dump a shared-memory snapshot once while
connected, then replay it:

    python lib/pyirsdk/irsdk.py --dump snapshot.bin
    python scripts/run_logger.py --test snapshot.bin

To exercise the full pipeline (telemetry -> features -> setup -> Claude
diagnosis) after each completed lap, with Claude authenticated (API key or
subscription login - see "Authenticating Claude" above):

    python scripts/diagnose_last_lap.py

For the full voice pipeline - push-to-talk capture -> local Whisper
transcription -> Claude diagnosis -> spoken + on-screen overlay delivery -
with Claude authenticated as above (speech-to-text needs no key, just the
one-time model download on first run):

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
- `diagnose()` calls Claude on every use - either metered per-call
  (`ANTHROPIC_API_KEY`) or drawing from a Claude.ai subscription's usage
  (see "Authenticating Claude" above); there's no local/offline mode for
  this step, since the setup reasoning needs an actual LLM. Speech-to-text
  and text-to-speech are both local/offline and free by default.
