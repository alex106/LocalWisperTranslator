"""Recording overlay: a borderless always-on-top panel with a live waveform.

Shown while the push-to-talk hotkey is held. It takes keyboard focus so
stray keypresses don't reach the target app. When recording stops it enters
a "processing" mode: focus returns to the previously active window right
away (before the transcript is pasted) while the panel stays visible with a
transcribing animation until hidden.

Tk objects must live on one thread, so the overlay owns the main thread's
mainloop and other threads talk to it through a command queue.
"""
from __future__ import annotations

import collections
import ctypes
import logging
import math
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
PROC_COLOR = "#e0a83a"  # amber scanner while transcribing (matches tray icon)
TRANSLATE_COLOR = "#4fa8e0"  # blue scanner while translating
STAGE_LABELS = {
    "transcribing": "⏳  Transcribing…",
    "translating": "🌐  Translating…",
}
TICK_MS = 40  # waveform refresh (25 fps)


def _force_foreground(hwnd: int) -> bool:
    """SetForegroundWindow with the ALT-key trick to beat the focus lock."""
    user32.keybd_event(VK_MENU, 0, 0, 0)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.keybd_event(VK_MENU, 0, 2, 0)  # ALT up
    return ok


class WaveformOverlay:
    """Owns the Tk mainloop. show()/processing()/set_stage()/hide()/quit()
    are thread-safe."""

    def __init__(self, recorder):
        self.recorder = recorder
        self._cmds: queue.Queue = queue.Queue()
        self._levels = collections.deque([0.0] * BARS, maxlen=BARS)
        self._mode = "hidden"  # "hidden" | "recording" | "processing"
        self._stage = "transcribing"  # sub-state while "processing": transcribing | translating
        self._phase = 0        # animation phase counter for the scanner
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

    def processing(self):
        """Called when recording stops: hand focus back to the target app but
        keep an animated 'transcribing' panel on screen until hide()."""
        self._cmds.put("processing")

    def set_stage(self, stage: str):
        """Switch the label/color shown during processing (e.g. "translating"
        once transcription hands off to NLLB). No-op outside processing."""
        self._cmds.put(("stage", stage))

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
                if isinstance(cmd, tuple) and cmd[0] == "stage":
                    self._do_set_stage(cmd[1])
                elif cmd == "show":
                    self._do_show()
                elif cmd == "processing":
                    self._do_processing()
                elif cmd == "hide":
                    self._do_hide()
                elif cmd == "quit":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(30, self._poll_cmds)

    def _do_show(self):
        if self._mode != "hidden":
            return
        self._mode = "recording"
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

    def _do_processing(self):
        # Only meaningful as a transition out of recording. Give keyboard focus
        # back to the target app now (so the upcoming Ctrl+V lands there) but
        # keep the panel visible and animated until _do_hide.
        if self._mode != "recording":
            return
        self._mode = "processing"
        self._stage = "transcribing"
        restored = False
        if self._prev_hwnd:
            restored = _force_foreground(self._prev_hwnd)
        self._prev_hwnd = None  # focus already handed back; hide won't re-grab
        log.info("overlay processing (focus restored=%s)", restored)
        # _tick keeps running (mode != "hidden"); no need to restart it.

    def _do_set_stage(self, stage: str):
        if self._mode != "processing" or stage not in STAGE_LABELS:
            return
        self._stage = stage
        log.info("overlay stage=%s", stage)

    def _do_hide(self):
        if self._mode == "hidden":
            return
        self._mode = "hidden"
        self.root.withdraw()
        restored = False
        if self._prev_hwnd:  # only set if we never went through processing
            restored = _force_foreground(self._prev_hwnd)
        log.info("overlay hidden (focus restored=%s)", restored)
        self._prev_hwnd = None

    # ---------------------------------------------------------- waveform
    def _tick(self):
        if self._mode == "hidden":
            return
        self._phase += 1
        if self._mode == "recording":
            self._levels.append(self.recorder.last_rms)
        self._draw()
        self.root.after(TICK_MS, self._tick)

    def _draw(self):
        if self._mode == "processing":
            self._draw_processing()
        else:
            self._draw_recording()

    def _draw_recording(self):
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

    def _draw_processing(self):
        """A travelling colored wave across the bars so it's obvious work is
        still happening; color/label reflect the current stage (transcribing
        vs translating) so the two phases are visually distinct."""
        c = self.canvas
        c.delete("all")
        color = PROC_COLOR if self._stage == "transcribing" else TRANSLATE_COLOR
        label = STAGE_LABELS[self._stage]
        c.create_text(WIDTH // 2, 14, text=label,
                      fill="#c9cad1", font=("Segoe UI", 9))
        mid = HEIGHT // 2 + 12
        span = (HEIGHT - 36) / 2
        bar_w = WIDTH / BARS
        t = self._phase * 0.35
        for i in range(BARS):
            # Two offset sines give a lively, non-repetitive travelling wave.
            env = 0.5 + 0.5 * math.sin(i * 0.30 - t)
            wob = 0.5 + 0.5 * math.sin(i * 0.11 - t * 0.6)
            h = max(2.0, span * (0.15 + 0.85 * env * wob))
            x = i * bar_w + bar_w * 0.25
            bar_color = color if env * wob > 0.15 else IDLE_BAR
            c.create_rectangle(x, mid - h, x + bar_w * 0.5, mid + h,
                               fill=bar_color, outline="")
