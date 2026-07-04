"""Recording overlay: a borderless always-on-top panel with a live waveform.

Shown while the push-to-talk hotkey is held. It takes keyboard focus so
stray keypresses don't reach the target app, and restores focus to the
previously active window when hidden (before the transcript is pasted).

Tk objects must live on one thread, so the overlay owns the main thread's
mainloop and other threads talk to it through a command queue.
"""
from __future__ import annotations

import collections
import ctypes
import logging
import queue
import tkinter as tk

log = logging.getLogger("wisper")

user32 = ctypes.windll.user32
GA_ROOT = 2
VK_MENU = 0x12  # ALT

WIDTH, HEIGHT = 380, 96
BARS = 64
BG = "#1e1f24"
BAR_COLOR = "#e05555"
IDLE_BAR = "#3a3c44"
TICK_MS = 40  # waveform refresh (25 fps)


def _force_foreground(hwnd: int) -> bool:
    """SetForegroundWindow with the ALT-key trick to beat the focus lock."""
    user32.keybd_event(VK_MENU, 0, 0, 0)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.keybd_event(VK_MENU, 0, 2, 0)  # ALT up
    return ok


class WaveformOverlay:
    """Owns the Tk mainloop. show()/hide()/quit() are thread-safe."""

    def __init__(self, recorder):
        self.recorder = recorder
        self._cmds: queue.Queue = queue.Queue()
        self._levels = collections.deque([0.0] * BARS, maxlen=BARS)
        self._visible = False
        self._prev_hwnd: int | None = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)  # no title bar / taskbar entry
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.configure(bg=BG)

        # Bottom-center of the primary screen.
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = (sw - WIDTH) // 2, sh - HEIGHT - 120
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT,
                                bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.root.after(30, self._poll_cmds)

    # ------------------------------------------------------------- public
    def show(self):
        """Called from the hotkey thread when recording starts."""
        self._cmds.put("show")

    def hide(self):
        """Called from the hotkey thread when recording stops."""
        self._cmds.put("hide")

    def quit(self):
        self._cmds.put("quit")

    def run(self):
        """Blocks: runs the Tk mainloop on the calling (main) thread."""
        self.root.mainloop()

    # ------------------------------------------------------- command pump
    def _poll_cmds(self):
        try:
            while True:
                cmd = self._cmds.get_nowait()
                if cmd == "show":
                    self._do_show()
                elif cmd == "hide":
                    self._do_hide()
                elif cmd == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(30, self._poll_cmds)

    def _do_show(self):
        if self._visible:
            return
        self._visible = True
        self._levels.extend([0.0] * BARS)
        # Remember where the user was typing so we can send focus back.
        self._prev_hwnd = user32.GetForegroundWindow()
        self.root.deiconify()
        self.root.lift()
        self.root.update_idletasks()
        hwnd = user32.GetAncestor(self.root.winfo_id(), GA_ROOT)
        took = _force_foreground(hwnd)
        log.info("overlay shown (focus taken=%s, prev hwnd=%s)",
                 took, self._prev_hwnd)
        self._tick()

    def _do_hide(self):
        if not self._visible:
            return
        self._visible = False
        self.root.withdraw()
        restored = False
        if self._prev_hwnd:
            restored = _force_foreground(self._prev_hwnd)
        log.info("overlay hidden (focus restored=%s)", restored)
        self._prev_hwnd = None

    # ---------------------------------------------------------- waveform
    def _tick(self):
        if not self._visible:
            return
        self._levels.append(self.recorder.last_rms)
        self._draw()
        self.root.after(TICK_MS, self._tick)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        c.create_text(WIDTH // 2, 14, text="●  Recording — release to transcribe",
                      fill="#c9cad1", font=("Segoe UI", 9))
        mid = HEIGHT // 2 + 12
        span = (HEIGHT - 36) / 2
        bar_w = WIDTH / BARS
        peak = max(max(self._levels), 1e-6)
        # Normalise against a rolling peak so quiet mics still show movement.
        scale = span / max(peak, 0.02)
        for i, lvl in enumerate(self._levels):
            h = max(2.0, lvl * scale)
            x = i * bar_w + bar_w * 0.25
            color = BAR_COLOR if lvl > 0.003 else IDLE_BAR
            c.create_rectangle(x, mid - h, x + bar_w * 0.5, mid + h,
                               fill=color, outline="")
