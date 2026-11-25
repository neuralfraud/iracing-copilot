"""Connection lifecycle management for the iRacing SDK.

iRacing's shared memory only exists while the sim is running, and has to be
re-opened every time the sim (re)starts. This mirrors the check_iracing()
pattern from pyirsdk's own tutorial, but throttles reconnect attempts so
polling it every loop iteration doesn't hammer the local sim-status check.
"""

import time

import irsdk


class IRacingSession:
    RECONNECT_INTERVAL = 1.0  # seconds between reconnect attempts while disconnected

    def __init__(self, test_file=None):
        self.ir = irsdk.IRSDK()
        self._test_file = test_file
        self._was_connected = False
        self._last_reconnect_attempt = 0.0

    @property
    def is_connected(self):
        return self.ir.is_initialized and self.ir.is_connected

    def poll_connection(self):
        """Call once per loop iteration. Returns True on a connect/disconnect transition."""
        if self._was_connected:
            if not self.is_connected:
                self._was_connected = False
                self.ir.shutdown()
                return True
            return False

        now = time.monotonic()
        if now - self._last_reconnect_attempt < self.RECONNECT_INTERVAL:
            return False
        self._last_reconnect_attempt = now

        if self.ir.startup(test_file=self._test_file) and self.is_connected:
            self._was_connected = True
            return True
        return False

    def shutdown(self):
        self.ir.shutdown()
        self._was_connected = False
