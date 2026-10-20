"""Version text and the git check for the tray menu.

The check fetches origin/main and reports how this checkout compares.
It does not pull. Startup runs it quietly; the menu item also shows
the result as a notification.
"""
from __future__ import annotations

import os
import re
import subprocess
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

VERSION = "1.0.1"
UPDATE_ORANGE = "#d66012"

# The Linux tray menu reads this when it paints "Check for updates".
menu_update_alert = False

_about_window: tk.Toplevel | None = None
_VERSION_RE = re.compile(r'(?m)^VERSION\s*=\s*["\']([^"\']+)["\']')


def loaded_label(device: str, compute_type: str | None) -> str:
    name = {"cpu": "CPU", "cuda": "GPU"}.get((device or "").lower(), (device or "unknown").upper())
    if compute_type:
        return f"{name} ({compute_type})"
    return name


@dataclass(frozen=True)
class UpdateStatus:
    behind: int = 0
    ahead: int = 0
    latest_version: str = ""
    latest_date: str = ""
    error: str = ""
    not_git: bool = False

    @property
    def update_available(self) -> bool:
        return not self.error and not self.not_git and self.behind > 0


def about_lines(cfg) -> str:
    translation = cfg.translate_to if cfg.translate else "off"
    return "\n".join([
        f"Version {VERSION}",
        f"Model: {cfg.model}",
        f"Loaded: {loaded_label(cfg.device, cfg.compute_type)}",
        f"Hotkey: {cfg.hotkey}",
        f"Language: {cfg.language}",
        f"Translation: {translation}",
    ])


def about_note(status: UpdateStatus | None) -> str:
    if status is None:
        return "Latest version: checking..."
    if status.not_git:
        return "Latest version: this copy is not a git checkout."
    if status.error:
        return "Latest version: could not be checked."
    lines = [
        f"Latest version: {status.latest_version or 'unknown'}",
        f"Last update: {status.latest_date or 'unknown'}",
    ]
    if status.update_available:
        lines.append("A newer version is available.")
    return "\n".join(lines)


def updates_menu_label(status: UpdateStatus | None) -> str:
    if status is not None and status.update_available:
        return "Check for updates — new version"
    return "Check for updates..."


def show_about(root: tk.Misc, text: str, note: str = "", alert: bool = False) -> None:
    """Open one About window on the Tk thread. A second call refreshes it."""
    global _about_window
    if _about_window is not None:
        try:
            if _about_window.winfo_exists():
                _about_window.destroy()
        except tk.TclError:
            pass
        _about_window = None

    win = tk.Toplevel(root)
    win.title("About Wisper")
    win.resizable(False, False)
    win.configure(bg="#1e1f24")
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass

    tk.Label(
        win, text="Wisper", bg="#1e1f24", fg="#f2f2f2",
        font=("DejaVu Sans", 14, "bold"),
    ).pack(anchor="w", padx=22, pady=(18, 4))
    tk.Label(
        win, text=text, justify="left", anchor="w",
        bg="#1e1f24", fg="#d7d7dc", font=("DejaVu Sans", 11),
    ).pack(anchor="w", padx=22, pady=(0, 8))
    if note:
        tk.Label(
            win, text=note, justify="left", anchor="w",
            bg="#1e1f24", fg=UPDATE_ORANGE if alert else "#d7d7dc",
            font=("DejaVu Sans", 11),
        ).pack(anchor="w", padx=22, pady=(0, 8))
    tk.Button(
        win, text="Close", command=win.destroy,
        bg="#2c2e36", fg="#f2f2f2", activebackground="#3a3c44",
        activeforeground="#f2f2f2", relief="flat", padx=14, pady=4,
    ).pack(anchor="e", padx=18, pady=(4, 16))

    win.update_idletasks()
    width, height = win.winfo_reqwidth(), win.winfo_reqheight()
    screen_w, screen_h = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{width}x{height}+{(screen_w - width) // 2}+{(screen_h - height) // 2}")
    win.focus_force()
    _about_window = win


def check_main_branch(root: Path) -> UpdateStatus:
    """Fetch origin/main and compare it with this checkout."""
    if not (root / ".git").is_dir():
        return UpdateStatus(not_git=True)

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    fetch = subprocess.run(
        ["git", "fetch", "origin", "main"],
        cwd=root, capture_output=True, text=True, timeout=60, env=env,
    )
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout or "git fetch failed").strip()
        last = detail.splitlines()[-1] if detail else "git fetch failed"
        return UpdateStatus(error=last)

    behind = _rev_count(root, "HEAD..origin/main")
    version = _remote_version(root)
    if not version:
        version = _short_sha(root) if behind else VERSION
    return UpdateStatus(
        behind=behind,
        ahead=_rev_count(root, "origin/main..HEAD"),
        latest_version=version,
        latest_date=_remote_date(root),
    )


def describe_update(status: UpdateStatus) -> str:
    if status.not_git:
        return "This copy is not a git checkout, so there is nothing to compare."
    if status.error:
        return f"Could not reach the repository.\n{status.error}"
    if status.behind == 0 and status.ahead == 0:
        return "Wisper is up to date with main."
    lines = ["Updates found on main." if status.behind else "This checkout differs from main."]
    if status.behind:
        lines.append(f"{status.behind} new commit(s) on main.")
        if status.latest_version:
            lines.append(f"Latest version: {status.latest_version}")
        if status.latest_date:
            lines.append(f"Last update: {status.latest_date}")
    if status.ahead:
        lines.append(f"{status.ahead} local commit(s) are not on main.")
    return "\n".join(lines)


def _rev_count(root: Path, revision_range: str) -> int:
    proc = subprocess.run(
        ["git", "rev-list", "--count", revision_range],
        cwd=root, capture_output=True, text=True, timeout=30, check=True,
    )
    return int((proc.stdout or "0").strip() or "0")


def _remote_version(root: Path) -> str:
    shown = subprocess.run(
        ["git", "show", "origin/main:src/app_info.py"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    if shown.returncode == 0:
        match = _VERSION_RE.search(shown.stdout or "")
        if match:
            return match.group(1)
    return ""


def _short_sha(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "origin/main"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    return (proc.stdout or "").strip()


def _remote_date(root: Path) -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "origin/main"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return raw[:10]
