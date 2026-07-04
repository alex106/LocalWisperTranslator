"""Check for (and download) model updates from Hugging Face.

Compares the remote repo revision against the locally recorded one
(.revision file in each model dir) and re-downloads only when they differ.
snapshot_download is incremental, so unchanged files are not re-fetched.

This is the ONLY intentionally-online code path of Wisper, and it runs only
when explicitly invoked (tray menu "Check for model updates" or manually).

Output (parsed by the app): one line per model
    <name>: up-to-date | updated | error <message>
Exit code 0 if all checks succeeded (regardless of updates), 1 on any error.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# This script is explicitly allowed online: undo the app's offline lockdown
# in case the environment was inherited from it.
for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
    os.environ.pop(var, None)

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parent.parent
MODELS = {
    "whisper-large-v3": (ROOT / "models" / "large-v3",
                         "Systran/faster-whisper-large-v3"),
    "nllb-200-600m": (ROOT / "models" / "nllb-200-600m",
                      "entai2965/nllb-200-distilled-600M-ctranslate2"),
}


def check_one(name: str, model_dir: Path, repo: str) -> str:
    if not model_dir.exists():
        return f"{name}: error local dir missing ({model_dir})"
    rev_file = model_dir / ".revision"
    local_sha = rev_file.read_text().strip() if rev_file.exists() else None
    remote_sha = HfApi().model_info(repo).sha
    if local_sha == remote_sha:
        return f"{name}: up-to-date"
    # New revision (or first check): sync the snapshot, then record it.
    snapshot_download(repo_id=repo, local_dir=str(model_dir))
    rev_file.write_text(remote_sha)
    # "updated" only when we had a baseline to compare against.
    return f"{name}: {'updated' if local_sha else 'up-to-date'}"


def main():
    failed = False
    for name, (model_dir, repo) in MODELS.items():
        try:
            print(check_one(name, model_dir, repo), flush=True)
        except Exception as exc:  # network down, repo gone, etc.
            failed = True
            print(f"{name}: error {type(exc).__name__}: {exc}", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
