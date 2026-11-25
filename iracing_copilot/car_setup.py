"""Reads the live CarSetup section from iRacing's session-info YAML block.

iRacing only (re)writes the CarSetup section when the driver presses Apply
in the garage. This wraps ir['CarSetup'] with change detection so callers
can react to actual setup changes instead of re-parsing on every tick.

Note: the SDK only *reads* the setup - there is no command to write values
back into the garage, so any recommendations derived from this data have to
be applied by the driver manually in-game.
"""


class CarSetupReader:
    def __init__(self, ir):
        self.ir = ir
        self._last_update_tick = None

    def read(self):
        """Return the current CarSetup dict, or None if unavailable (e.g. not in a car)."""
        return self.ir["CarSetup"]

    def poll_for_update(self):
        """Return the new CarSetup dict only when it changed since the last call, else None."""
        setup = self.ir["CarSetup"]
        if setup is None:
            return None

        update_tick = self.ir.get_session_info_update_by_key("CarSetup")
        if update_tick == self._last_update_tick:
            return None

        self._last_update_tick = update_tick
        return setup
