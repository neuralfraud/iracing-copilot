"""Always-on-top overlay window showing the diagnosis log.

Plain tkinter (stdlib - no extra dependency) rather than iRacing's own chat
system: ir.chat_command() only sends to iRacing's in-sim driver chat,
visible to other racers, not a private channel for this tool (see the
design notes in diagnosis.py / car_setup.py).

tkinter must run on the main thread. Other components here (telemetry
polling, push-to-talk, text-to-speech) run on background threads and post
updates through `post()`, which is thread-safe - it only touches a
queue.Queue, never the Tk widgets directly. The widgets are only ever
touched from `_poll_queue`, which `root.after` always calls back on the main
thread.
"""

import queue
import tkinter as tk
from tkinter import scrolledtext

POLL_INTERVAL_MS = 150


class Overlay:
    def __init__(self, title="iRacing Copilot", width=520, height=360):
        self._queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title(title)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{width}x{height}")

        self.text = scrolledtext.ScrolledText(self.root, wrap="word", state="disabled")
        self.text.pack(fill="both", expand=True)

        self._closed = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def post(self, message):
        """Thread-safe: call from any thread to append a block to the overlay."""
        self._queue.put(message)

    def run(self):
        """Blocks on the Tk mainloop - call only from the main thread."""
        self._poll_queue()
        self.root.mainloop()

    def _poll_queue(self):
        if self._closed:
            return
        try:
            while True:
                self._append(self._queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _append(self, message):
        self.text.configure(state="normal")
        if self.text.index("end-1c") != "1.0":
            self.text.insert("end", "\n" + "-" * 40 + "\n")
        self.text.insert("end", message)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _on_close(self):
        self._closed = True
        self.root.destroy()
