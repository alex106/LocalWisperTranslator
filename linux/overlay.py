"""Recording overlay for Linux.

Same waveform as the Windows panel, without the Win32 focus calls. It does not
take keyboard focus: on Wayland a focused overlay would steal the Ctrl+V
that should land in the application the user was typing in.
"""
from __future__ import annotations

import collections
import ctypes
import logging
import math
import queue
import tkinter as tk

log = logging.getLogger("wisper")

WIDTH, HEIGHT = 380, 96
BARS = 64
BG = "#1e1f24"
BAR_COLOR = "#e05555"
IDLE_BAR = "#3a3c44"
PROC_COLOR = "#e0a83a"
TRANSLATE_COLOR = "#4fa8e0"
STAGE_LABELS = {
    "transcribing": "⏳  Transcribing…",
    "translating": "🌐  Translating…",
}
TICK_MS = 40
FONT = ("DejaVu Sans", 9)

# Xutil.h InputHint. XSetWMHints replaces the hints, which is fine: this
# window has no icon and no initial state we need to keep.
_INPUT_HINT = 1

# The default Xlib error handler exits the process. A wrong window id must
# not take Wisper down with it. The callback is module-level so it is not
# collected while X11 still holds the function pointer.
_X_ERROR = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


@_X_ERROR
def _ignore_x_error(display, event):  # noqa: ARG001
    return 0


class _XWMHints(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_long),
        ("input", ctypes.c_int),
        ("initial_state", ctypes.c_int),
        ("icon_pixmap", ctypes.c_ulong),
        ("icon_window", ctypes.c_ulong),
        ("icon_x", ctypes.c_int),
        ("icon_y", ctypes.c_int),
        ("icon_mask", ctypes.c_ulong),
        ("window_group", ctypes.c_ulong),
    ]


def _refuse_focus(window_id: int) -> bool:
    """Tell X11 this window does not want keyboard input.

    Tk on this desktop goes through XWayland, so the X id from winfo_id is
    valid on a fresh XOpenDisplay of the same DISPLAY. A failure here must
    not stop the overlay from being shown. The previous X error handler is
    put back so Tk keeps its own.
    """
    lib = None
    display = None
    previous = None
    handler_set = False
    try:
        lib = ctypes.CDLL("libX11.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_void_p]
        lib.XSetWMHints.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                    ctypes.POINTER(_XWMHints)]
        lib.XSetWMHints.restype = ctypes.c_int
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.restype = ctypes.c_void_p
        previous = lib.XSetErrorHandler(ctypes.cast(_ignore_x_error, ctypes.c_void_p))
        handler_set = True
        display = lib.XOpenDisplay(None)
        if not display:
            return False
        hints = _XWMHints()
        hints.flags = _INPUT_HINT
        hints.input = 0
        lib.XSetWMHints(display, ctypes.c_ulong(window_id), ctypes.byref(hints))
        lib.XFlush(display)
        return True
    except Exception:
        log.exception("could not set WM_HINTS input=false")
        return False
    finally:
        # Close the display before restoring the previous handler. Xlib
        # reports a BadWindow on the next request, and that request must
        # still be inside the ignore handler or the default handler exits.
        if lib is not None and display:
            try:
                lib.XCloseDisplay(display)
            except Exception:
                pass
        if lib is not None and handler_set:
            try:
                lib.XSetErrorHandler(previous)
            except Exception:
                pass


class WaveformOverlay:
    """Owns the Tk mainloop. show()/processing()/set_stage()/hide()/quit()
    are thread-safe."""

    def __init__(self, recorder):
        self.recorder = recorder
        self._cmds: queue.Queue = queue.Queue()
        self._levels = collections.deque([0.0] * BARS, maxlen=BARS)
        self._mode = "hidden"
        self._stage = "transcribing"
        self._phase = 0

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        try:
            # Splash-type windows are shown and usually not given focus.
            self.root.attributes("-type", "splash")
        except tk.TclError:
            pass
        self.root.configure(bg=BG)

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x, y = (sw - WIDTH) // 2, sh - HEIGHT - 120
        self.root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT,
                                bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.root.after(30, self._poll_cmds)

    def show(self):
        self._cmds.put("show")

    def processing(self):
        self._cmds.put("processing")

    def set_stage(self, stage: str):
        self._cmds.put(("stage", stage))

    def hide(self):
        self._cmds.put("hide")

    def quit(self):
        self._cmds.put("quit")

    def run(self):
        self.root.mainloop()

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
        self.root.deiconify()
        self.root.lift()
        self.root.update_idletasks()
        refused = _refuse_focus(int(self.root.winfo_id()))
        log.info("overlay shown (focus refused=%s)", refused)
        self._tick()

    def _do_processing(self):
        if self._mode != "recording":
            return
        self._mode = "processing"
        self._stage = "transcribing"
        log.info("overlay processing")

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
        log.info("overlay hidden")

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
                      fill="#c9cad1", font=FONT)
        mid = HEIGHT // 2 + 12
        span = (HEIGHT - 36) / 2
        bar_w = WIDTH / BARS
        peak = max(max(self._levels), 1e-6)
        scale = span / max(peak, 0.02)
        for i, lvl in enumerate(self._levels):
            h = max(2.0, lvl * scale)
            x = i * bar_w + bar_w * 0.25
            color = BAR_COLOR if lvl > 0.003 else IDLE_BAR
            c.create_rectangle(x, mid - h, x + bar_w * 0.5, mid + h,
                               fill=color, outline="")

    def _draw_processing(self):
        c = self.canvas
        c.delete("all")
        color = PROC_COLOR if self._stage == "transcribing" else TRANSLATE_COLOR
        label = STAGE_LABELS[self._stage]
        c.create_text(WIDTH // 2, 14, text=label, fill="#c9cad1", font=FONT)
        mid = HEIGHT // 2 + 12
        span = (HEIGHT - 36) / 2
        bar_w = WIDTH / BARS
        t = self._phase * 0.35
        for i in range(BARS):
            env = 0.5 + 0.5 * math.sin(i * 0.30 - t)
            wob = 0.5 + 0.5 * math.sin(i * 0.11 - t * 0.6)
            h = max(2.0, span * (0.15 + 0.85 * env * wob))
            x = i * bar_w + bar_w * 0.25
            bar_color = color if env * wob > 0.15 else IDLE_BAR
            c.create_rectangle(x, mid - h, x + bar_w * 0.5, mid + h,
                               fill=bar_color, outline="")
