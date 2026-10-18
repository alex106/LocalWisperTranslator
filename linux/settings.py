"""Linux settings file, separate from the Windows config.json.

Config.set() always writes config.json. This subclass sends every save to
config.linux.json so a tray-menu change cannot overwrite the Windows file.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import DEFAULTS, Config  # noqa: E402

log = logging.getLogger("wisper")

CONFIG_LINUX_PATH = ROOT / "config.linux.json"


def nvidia_present() -> bool:
    return shutil.which("nvidia-smi") is not None


def platform_overrides() -> dict:
    """Device and model defaults for this machine. CUDA keeps the Windows pair."""
    cuda = nvidia_present()
    model = "large-v3" if cuda else "small"
    return {
        "device": "cuda" if cuda else "cpu",
        "compute_type": "int8_float16" if cuda else "int8",
        "model": model,
        "model_dir": str(ROOT / "models" / model),
        "translator_dir": str(ROOT / "models" / "nllb-200-600m"),
        "local_files_only": True,
    }


def write_fresh_config(path: Path | None = None) -> Path:
    """Write config.linux.json from Windows defaults plus Linux overrides."""
    path = path or CONFIG_LINUX_PATH
    data = dict(DEFAULTS)
    data.update(platform_overrides())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def nvidia_lib_dirs() -> list[Path]:
    """pip nvidia-cublas / nvidia-cudnn wheel lib directories, if installed."""
    candidates: list[str] = []
    try:
        import site
        candidates.extend(site.getsitepackages())
    except Exception:
        pass
    ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates.append(str(Path(sys.prefix) / "lib" / ver / "site-packages"))
    found: list[Path] = []
    seen: set[str] = set()
    for sp in candidates:
        nvidia = Path(sp) / "nvidia"
        if not nvidia.is_dir():
            continue
        for lib in nvidia.glob("*/lib"):
            key = str(lib)
            if lib.is_dir() and key not in seen:
                seen.add(key)
                found.append(lib)
    return found


def prepare_cuda_libraries() -> None:
    """Expose pip NVIDIA wheels to ctranslate2.

    The dynamic linker reads LD_LIBRARY_PATH at process start, so the desktop
    entry sets it too. Preloading the libraries by absolute path covers a
    direct `python linux/app.py` launch in the same process.
    """
    lib_dirs = nvidia_lib_dirs()
    if not lib_dirs:
        return
    prefix = os.pathsep.join(str(p) for p in lib_dirs)
    current = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = prefix if not current else prefix + os.pathsep + current
    import ctypes
    for lib in lib_dirs:
        for so in sorted(lib.glob("lib*.so*")):
            if so.is_symlink():
                continue
            try:
                ctypes.CDLL(str(so), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                log.info("could not preload %s", so)


class LinuxConfig(Config):
    """Config that persists to config.linux.json."""

    def save(self, path: Path | None = None):
        super().save(path or CONFIG_LINUX_PATH)

    def apply_platform_defaults(self):
        for key, value in platform_overrides().items():
            self.set(key, value)

    @classmethod
    def load(cls) -> "LinuxConfig":
        fresh = not CONFIG_LINUX_PATH.exists()
        cfg = super().load(CONFIG_LINUX_PATH)
        if fresh:
            cfg.apply_platform_defaults()
        return cfg


def open_linux_config():
    """Open config.linux.json in the desktop's default editor."""
    try:
        subprocess.Popen(["xdg-open", str(CONFIG_LINUX_PATH)])
    except Exception:
        log.exception("could not open %s", CONFIG_LINUX_PATH)
