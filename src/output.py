"""Deliver transcribed text to the focused application.

Default strategy is clipboard-paste: set the clipboard, send Ctrl+V, then
restore the previous clipboard. This handles Unicode (Cyrillic, emoji)
reliably, unlike per-character simulated typing. A "type" fallback uses
keyboard.write for apps that block paste.
"""
from __future__ import annotations

import time

import keyboard
import pyperclip

from config import Config


class Output:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def deliver(self, text: str):
        if not text:
            return
        if self.cfg.output_mode == "type":
            self._type(text)
        else:
            self._paste(text)

    def _paste(self, text: str):
        previous = ""
        if self.cfg.restore_clipboard:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = ""
        pyperclip.copy(text)
        # Small delay so the clipboard is settled before paste.
        time.sleep(0.05)
        keyboard.send("ctrl+v")
        if self.cfg.restore_clipboard:
            # Restore after the target app has consumed the paste.
            time.sleep(0.2)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass

    def _type(self, text: str):
        keyboard.write(text, delay=0.005)
