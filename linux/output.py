"""Deliver transcribed text on Linux.

Paste copies with pyperclip (wl-copy from wl-clipboard on Wayland) and
injects Ctrl+V through ydotool. The focused window is whatever the user
was typing in, because the overlay does not take focus.

Ubuntu 22.04 ships ydotool 0.1.8, which wants named keys (`ctrl+v`) and
talks to /tmp/.ydotool_socket. ydotool 1.x wants numeric keycodes instead.
The choice is made from the installed package, not by running `ydotool key`,
because 0.1.8 opens /dev/uinput before it parses a subcommand.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

import pyperclip

log = logging.getLogger("wisper")

# KEY_LEFTCTRL=29, KEY_V=47. Press, press, release, release.
_V1_PASTE = ["29:1", "47:1", "47:0", "29:0"]
_SOCKET_CANDIDATES = ("/tmp/.ydotool_socket",)


def _ydotool_is_v1() -> bool:
    version = ""
    if shutil.which("dpkg-query"):
        try:
            version = subprocess.check_output(
                ["dpkg-query", "-W", "-f", "${Version}", "ydotool"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, OSError):
            version = ""
    if version:
        major = version.split(":", 1)[-1].split(".", 1)[0]
        return major.isdigit() and int(major) >= 1
    # 0.1.8 `ydotool help` exits before it touches uinput and lists
    # mousemove_relative, which 1.x removed.
    if not shutil.which("ydotool"):
        return False
    try:
        proc = subprocess.run(
            ["ydotool", "help"], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (proc.stdout or "") + (proc.stderr or "")
    return "mousemove_relative" not in text


def ydotool_env() -> dict[str, str]:
    """Point 1.x clients at whichever socket the daemon actually created."""
    env = os.environ.copy()
    if env.get("YDOTOOL_SOCKET"):
        return env
    runtime = env.get("XDG_RUNTIME_DIR", "")
    candidates = list(_SOCKET_CANDIDATES)
    if runtime:
        candidates.insert(0, os.path.join(runtime, ".ydotool_socket"))
    for path in candidates:
        if os.path.exists(path):
            env["YDOTOOL_SOCKET"] = path
            break
    return env


class Output:
    def __init__(self, cfg):
        self.cfg = cfg
        self._v1: bool | None = None

    def deliver(self, text: str):
        if not text:
            return
        if self.cfg.output_mode == "type":
            self._type(text)
        else:
            self._paste(text)

    def _paste_args(self) -> list[str]:
        if self._v1 is None:
            self._v1 = _ydotool_is_v1()
            log.info("ydotool cli=%s", "1.x keycodes" if self._v1 else "0.1 named keys")
        if self._v1:
            return ["ydotool", "key", *_V1_PASTE]
        return ["ydotool", "key", "ctrl+v"]

    def _run_ydotool(self, args: list[str]) -> bool:
        try:
            proc = subprocess.run(
                args, env=ydotool_env(), capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            log.error("ydotool is not installed; text is on the clipboard")
            return False
        except subprocess.TimeoutExpired:
            log.error("ydotool timed out; text is on the clipboard")
            return False
        if proc.returncode != 0:
            log.error("ydotool failed (%s): %s", proc.returncode,
                      (proc.stderr or proc.stdout or "").strip())
            return False
        if proc.stderr:
            log.info("ydotool: %s", proc.stderr.strip())
        return True

    def _paste(self, text: str):
        previous = ""
        if self.cfg.restore_clipboard:
            try:
                previous = pyperclip.paste()
            except Exception:
                previous = ""
        pyperclip.copy(text)
        # Let the clipboard settle. ydotool 0.1.8 also waits ~100ms itself.
        time.sleep(0.05)
        self._run_ydotool(self._paste_args())
        if self.cfg.restore_clipboard:
            time.sleep(0.25)
            try:
                pyperclip.copy(previous)
            except Exception:
                pass

    def _type(self, text: str):
        if not text.isascii():
            log.warning("Linux type mode is ASCII-only; pasting instead")
            self._paste(text)
            return
        self._run_ydotool(["ydotool", "type", text])
