"""Global hold-to-talk for Linux.

Listens on keyboard event devices with evdev. The same press/release
contract as the Windows hook: on_press fires once when the whole chord is
down, on_release fires once when it is not. Key auto-repeat is ignored.
Either the left or the right modifier satisfies ctrl, alt, and shift.

The listener does not grab the device, so the focused application keeps
focus and the later Ctrl+V lands there.
"""
from __future__ import annotations

import logging
import select
import threading
from typing import Callable

log = logging.getLogger("wisper")

# linux/input-event-codes.h. Hard-coded so the chord tracker can be tested
# without the evdev package.
KEY_LEFTCTRL = 29
KEY_RIGHTCTRL = 97
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_LEFTALT = 56
KEY_RIGHTALT = 100
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126
KEY_SPACE = 57

_MODIFIERS: dict[str, frozenset[int]] = {
    "ctrl": frozenset({KEY_LEFTCTRL, KEY_RIGHTCTRL}),
    "control": frozenset({KEY_LEFTCTRL, KEY_RIGHTCTRL}),
    "alt": frozenset({KEY_LEFTALT, KEY_RIGHTALT}),
    "shift": frozenset({KEY_LEFTSHIFT, KEY_RIGHTSHIFT}),
    "win": frozenset({KEY_LEFTMETA, KEY_RIGHTMETA}),
    "super": frozenset({KEY_LEFTMETA, KEY_RIGHTMETA}),
    "meta": frozenset({KEY_LEFTMETA, KEY_RIGHTMETA}),
}

_NAMED: dict[str, int] = {
    "space": KEY_SPACE,
    "enter": 28,
    "return": 28,
    "tab": 15,
    "esc": 1,
    "escape": 1,
    "backspace": 14,
}

# QWERTY scan codes, not alphabetical order.
_LETTERS: dict[str, int] = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34,
    "h": 35, "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49,
    "o": 24, "p": 25, "q": 16, "r": 19, "s": 31, "t": 20, "u": 22,
    "v": 47, "w": 17, "x": 45, "y": 21, "z": 44,
}

_DIGITS: dict[str, int] = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
    "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
}

# KEY_F1 is 59 through KEY_F10 at 68; KEY_F11 is 87 and KEY_F12 is 88.
_FUNCTIONS: dict[str, int] = {
    **{f"f{n}": 58 + n for n in range(1, 11)},
    "f11": 87,
    "f12": 88,
}


def chord_groups(hotkey: str) -> list[frozenset[int]]:
    groups: list[frozenset[int]] = []
    for part in hotkey.split("+"):
        name = part.strip().lower()
        if not name:
            continue
        if name in _MODIFIERS:
            groups.append(_MODIFIERS[name])
        elif name in _NAMED:
            groups.append(frozenset({_NAMED[name]}))
        elif name in _LETTERS:
            groups.append(frozenset({_LETTERS[name]}))
        elif name in _DIGITS:
            groups.append(frozenset({_DIGITS[name]}))
        elif name in _FUNCTIONS:
            groups.append(frozenset({_FUNCTIONS[name]}))
        else:
            raise ValueError(f"unknown hotkey key {part!r}")
    if not groups:
        raise ValueError("empty hotkey")
    return groups


class ChordTracker:
    """Pure key-state machine. feed() takes evdev-style (code, value)."""

    def __init__(self, hotkey: str, on_press: Callable[[], None],
                 on_release: Callable[[], None]):
        self.groups = chord_groups(hotkey)
        self.on_press = on_press
        self.on_release = on_release
        self._down: set[int] = set()
        self._active = False

    def feed(self, code: int, value: int) -> None:
        # 1 = down, 0 = up, 2 = kernel auto-repeat.
        if value == 2:
            return
        if value == 1:
            self._down.add(code)
        elif value == 0:
            self._down.discard(code)
        else:
            return
        held = self._chord_down()
        if held and not self._active:
            self._active = True
            try:
                self.on_press()
            except Exception:
                self._active = False
                raise
        elif not held and self._active:
            self._active = False
            self.on_release()

    def _chord_down(self) -> bool:
        return all(self._down & group for group in self.groups)


def _open_keyboards() -> list:
    """Keyboard event devices only. Mice expose buttons but not KEY_A."""
    try:
        import evdev
        from evdev import ecodes
    except ImportError:
        log.exception("python3-evdev is not installed")
        return []
    found = []
    for path in evdev.list_devices():
        dev = None
        try:
            dev = evdev.InputDevice(path)
            keys = dev.capabilities().get(ecodes.EV_KEY, [])
            if ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys:
                found.append(dev)
            else:
                dev.close()
        except (OSError, PermissionError):
            log.info("skip unreadable input device %s", path)
            if dev is not None:
                try:
                    dev.close()
                except OSError:
                    pass
    return found


class PushToTalk:
    def __init__(self, hotkey: str, on_press: Callable[[], None],
                 on_release: Callable[[], None]):
        self.tracker = ChordTracker(hotkey, on_press, on_release)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._devices: list = []

    def start(self) -> bool:
        """Start the listener. False when no keyboard device is readable."""
        if self._thread is not None:
            return True
        devices = _open_keyboards()
        if not devices:
            log.error("no readable keyboard devices")
            return False
        self._devices = devices
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="wisper-hotkey",
                                        daemon=True)
        self._thread.start()
        log.info("hotkey listening on %d keyboard(s)", len(devices))
        return True

    def stop(self):
        self._stop.set()
        for dev in self._devices:
            try:
                dev.close()
            except OSError:
                pass
        self._devices = []
        self._thread = None
        self.tracker._active = False

    def _loop(self):
        from evdev import ecodes
        while not self._stop.is_set():
            if not self._devices:
                return
            try:
                readable, _, _ = select.select(self._devices, [], [], 0.4)
            except (OSError, ValueError):
                log.exception("hotkey select failed")
                return
            for dev in readable:
                try:
                    for event in dev.read():
                        if event.type == ecodes.EV_KEY:
                            self.tracker.feed(event.code, event.value)
                except BlockingIOError:
                    continue
                except OSError:
                    log.warning("lost input device %s", getattr(dev, "path", dev))
                    try:
                        dev.close()
                    except OSError:
                        pass
                    self._devices = [d for d in self._devices if d is not dev]
                    if not self._devices:
                        log.error("no keyboard devices left")
                        return


def _self_check() -> None:
    """Fake key events: press and release fire once, including key repeat."""
    events: list[str] = []
    tracker = ChordTracker(
        "ctrl+alt+space",
        lambda: events.append("down"),
        lambda: events.append("up"),
    )
    tracker.feed(KEY_LEFTCTRL, 1)
    tracker.feed(KEY_LEFTCTRL, 2)  # auto-repeat must not re-fire
    tracker.feed(KEY_LEFTALT, 1)
    assert events == [], events
    tracker.feed(KEY_SPACE, 1)
    assert events == ["down"], events
    tracker.feed(KEY_SPACE, 2)
    tracker.feed(KEY_LEFTCTRL, 2)
    assert events == ["down"], events
    tracker.feed(KEY_SPACE, 0)
    assert events == ["down", "up"], events
    tracker.feed(KEY_LEFTCTRL, 0)
    tracker.feed(KEY_LEFTALT, 0)

    tracker.feed(KEY_RIGHTCTRL, 1)
    tracker.feed(KEY_RIGHTALT, 1)
    tracker.feed(KEY_SPACE, 1)
    assert events == ["down", "up", "down"], events
    tracker.feed(KEY_RIGHTCTRL, 0)
    assert events == ["down", "up", "down", "up"], events

    failed = False
    try:
        chord_groups("ctrl+notakey")
    except ValueError:
        failed = True
    assert failed
    print("chord tracker ok")


if __name__ == "__main__":
    _self_check()
