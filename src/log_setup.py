"""One log file, deleted and started again at 100 MB.

The standard size handler on this Python keeps the old file when no
backups are requested. This one removes it and opens a new file.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_LIMIT_BYTES = 100 * 1024 * 1024


class ResettingFileHandler(RotatingFileHandler):
    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        if os.path.exists(self.baseFilename):
            os.remove(self.baseFilename)
        if not self.delay:
            self.stream = self._open()


def configure_log(path: Path) -> logging.Logger:
    if path.exists() and path.stat().st_size >= LOG_LIMIT_BYTES:
        path.unlink()
    handler = ResettingFileHandler(
        path,
        maxBytes=LOG_LIMIT_BYTES,
        backupCount=0,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return logging.getLogger("wisper")
