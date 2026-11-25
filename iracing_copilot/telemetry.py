"""Continuous live telemetry logging into a rolling per-lap buffer.

iRacing's shared memory only exposes the *current* tick's values - there is
no history. This module is what turns that into "give me what happened on
lap N" by sampling every tick and bucketing by lap number.
"""

from collections import deque

from .channels import DEFAULT_CHANNELS


class TelemetrySample(dict):
    """A single tick's worth of telemetry values, keyed by channel name."""


class TelemetryLogger:
    def __init__(self, ir, channels=None, max_laps=5):
        self.ir = ir
        self.channels = list(channels or DEFAULT_CHANNELS)
        self.max_laps = max_laps

        self._available_channels = None
        self._laps = {}  # lap_number -> list[TelemetrySample]
        self._lap_order = deque()  # insertion order, for evicting old laps
        self._current_lap = None

    def _resolve_available_channels(self):
        if self._available_channels is None:
            names = set(self.ir.var_headers_names or [])
            self._available_channels = [c for c in self.channels if c in names]
            missing = sorted(set(self.channels) - names)
            if missing:
                print(f"[TelemetryLogger] channels not available for this car, skipping: {missing}")
        return self._available_channels

    def poll(self):
        """Sample the current tick. Call every loop iteration while connected."""
        self.ir.freeze_var_buffer_latest()
        try:
            lap = self.ir["Lap"]
            if lap is None or lap < 0:
                return None

            sample = TelemetrySample(
                (channel, self.ir[channel]) for channel in self._resolve_available_channels()
            )
            self._store(lap, sample)
            return sample
        finally:
            self.ir.unfreeze_var_buffer_latest()

    def _store(self, lap, sample):
        if lap not in self._laps:
            self._laps[lap] = []
            self._lap_order.append(lap)
            while len(self._lap_order) > self.max_laps:
                oldest = self._lap_order.popleft()
                self._laps.pop(oldest, None)
        self._laps[lap].append(sample)
        self._current_lap = lap

    def get_lap(self, lap_number):
        return self._laps.get(lap_number, [])

    def get_current_lap(self):
        if self._current_lap is None:
            return []
        return self.get_lap(self._current_lap)

    def get_last_completed_lap(self):
        if self._current_lap is None:
            return []
        completed = [lap for lap in self._laps if lap < self._current_lap]
        if not completed:
            return []
        return self.get_lap(max(completed))

    def recent_samples(self, seconds, session_time_channel="SessionTime"):
        """All buffered samples within `seconds` of the most recent one."""
        all_samples = [s for lap in self._laps for s in self._laps[lap]]
        if not all_samples:
            return []

        latest_time = all_samples[-1].get(session_time_channel)
        if latest_time is None:
            return all_samples

        return [
            s for s in all_samples
            if session_time_channel in s and (latest_time - s[session_time_channel]) <= seconds
        ]
