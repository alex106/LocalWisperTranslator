"""Make the pip-installed NVIDIA CUDA DLLs discoverable on Windows.

CTranslate2 (the engine behind faster-whisper) needs cuBLAS and cuDNN DLLs
at runtime (e.g. cublas64_12.dll). The `nvidia-cublas-cu12` and
`nvidia-cudnn-cu12` wheels drop these under site-packages/nvidia/*/bin, but
that directory is not on the Windows DLL search path by default. Importing
this module (before faster_whisper) registers those bin folders so the app
works without a manual CUDA Toolkit install.

Safe no-op on non-Windows or when the wheels are absent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _register():
    if not sys.platform.startswith("win"):
        return
    if not hasattr(os, "add_dll_directory"):
        return
    site_nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not site_nvidia.exists():
        return
    for bin_dir in site_nvidia.glob("*/bin"):
        try:
            os.add_dll_directory(str(bin_dir))
            # Also prepend to PATH for libraries that resolve via PATH.
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        except OSError:
            pass


_register()
