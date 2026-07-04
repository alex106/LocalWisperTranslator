"""One-time download of the NLLB-200 translation model (CTranslate2 format).

Run once while online; afterwards translation works fully offline.
The float32 model.bin (~2.4 GB on disk) is quantized to int8 at load time
(~600 MB in memory).

Usage:
    python scripts/download_nllb.py
"""
from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models" / "nllb-200-600m"
REPO = "entai2965/nllb-200-distilled-600M-ctranslate2"


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {REPO} -> {TARGET} ...")
    snapshot_download(repo_id=REPO, local_dir=str(TARGET))
    print("Done. Translation model ready for offline use.")


if __name__ == "__main__":
    main()
