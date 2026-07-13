"""Configuration: defaults + load/save/merge of config.json.

The config file lives at the project root (next to this package's parent).
Missing keys are filled from DEFAULTS so older config files keep working.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Project root = parent of the src/ directory that holds this file.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    "hotkey": "ctrl+alt+space",   # held = push-to-talk
    "language": "auto",           # "auto" | "en" | "ru" | any Whisper code
    "model": "large-v3",          # "large-v3" | "medium" | ...
    "device": "cuda",             # "cuda" | "cpu"
    "compute_type": "int8_float16",  # fits large-v3 in ~2GB VRAM on 4GB GPUs
    "beam_size": 2,               # decoding beam width; 1=fastest, 5=most accurate
    "model_dir": None,            # local path for fully-offline weights; None = HF cache
    "local_files_only": False,    # True forces offline (no HF download)
    "output_mode": "paste",       # "paste" (clipboard+Ctrl+V) | "type" (keystrokes)
    "mic_device": None,           # sounddevice input index; None = system default
    "min_audio_seconds": 0.3,     # ignore shorter recordings
    "beep_on_record": True,
    "restore_clipboard": True,
    "show_overlay": True,         # waveform panel while recording
    "translate": False,           # translate transcript before pasting
    "translate_to": "en",         # target ISO code (see translator.ISO_TO_FLORES)
    "translator_dir": None,       # NLLB model dir; None = <root>/models/nllb-200-600m
}


class Config:
    """Dict-backed settings with attribute access, persisted to config.json."""

    def __init__(self, data: dict | None = None):
        merged = dict(DEFAULTS)
        if data:
            merged.update({k: v for k, v in data.items() if k in DEFAULTS})
        self._data = merged

    # --- attribute-style access -------------------------------------------
    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self.save()

    def as_dict(self) -> dict:
        return dict(self._data)

    # --- persistence ------------------------------------------------------
    def save(self, path: Path | None = None):
        path = path or CONFIG_PATH
        path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or CONFIG_PATH
        data = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = None
        cfg = cls(data)
        if not path.exists():
            cfg.save(path)  # materialise defaults on first run
        return cfg


def open_config_file():
    """Open config.json in the OS default editor (best-effort)."""
    try:
        os.startfile(CONFIG_PATH)  # type: ignore[attr-defined]  # Windows
    except Exception:
        pass
