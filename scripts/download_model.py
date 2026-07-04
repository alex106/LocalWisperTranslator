"""One-time model download for fully-offline use.

Run this ONCE while online. It fetches the CTranslate2 Whisper weights into a
local ./models directory so the app can then run with local_files_only=True
and never touch the internet.

Usage:
    python scripts/download_model.py                 # default: large-v3
    python scripts/download_model.py medium          # a different size
"""
from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

# Systran hosts the CT2-converted faster-whisper weights.
REPOS = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    "base": "Systran/faster-whisper-base",
}


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "large-v3"
    if model not in REPOS:
        print(f"Unknown model '{model}'. Choose from: {', '.join(REPOS)}")
        sys.exit(1)

    repo = REPOS[model]
    target = MODELS_DIR / model
    target.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {repo} -> {target} ...")
    snapshot_download(repo_id=repo, local_dir=str(target))
    print("\nDone. To run fully offline, set in config.json:")
    print(f'  "model_dir": {str(target)!r},')
    print('  "local_files_only": true')


if __name__ == "__main__":
    main()
