"""Global push-to-talk hotkey listener (Windows).

Uses a single global keyboard hook and evaluates the full chord state on
every key event: when all keys of the configured combo become pressed we
fire on_press once; when the combo is no longer fully held we fire
on_release once. This gives clean hold-to-talk semantics and ignores key
auto-repeat.
"""
from __future__ import annotations

from typing import Callable

import keyboard


class PushToTalk:
    def __init__(self, hotkey: str, on_press: Callable[[], None],
                 on_release: Callable[[], None]):
        self.keys = [k.strip().lower() for k in hotkey.split("+") if k.strip()]
        self.on_press = on_press
        self.on_release = on_release
        self._active = False
        self._hook = None

    def _chord_down(self) -> bool:
        try:
            return all(keyboard.is_pressed(k) for k in self.keys)
        except Exception:
            return False

    def _handler(self, event):  # noqa: ARG002 - event unused, we poll chord state
        down = self._chord_down()
        if down and not self._active:
            self._active = True
            try:
                self.on_press()
            except Exception:
                self._active = False
                raise
        elif not down and self._active:
            self._active = False
            self.on_release()

    def start(self):
        if self._hook is None:
            self._hook = keyboard.hook(self._handler)

    def stop(self):
        if self._hook is not None:
            keyboard.unhook(self._hook)
            self._hook = None
        self._active = False
