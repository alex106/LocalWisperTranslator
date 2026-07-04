"""Language tables, loaded from a human-editable languages.json at the
project root. The file is created with defaults on first run.

Structure of languages.json:
{
  "spoken":            [ {"label": "...", "code": "<whisper ISO code|auto>"} ],
  "translate_targets": [ {"label": "...", "code": "<ISO code>"} ],
  "flores_codes":      { "<ISO code>": "<FLORES-200 code for NLLB>" }
}

- "spoken" fills the tray Language menu (what you speak).
- "translate_targets" fills the tray Translation menu (what gets pasted).
- "flores_codes" maps ISO codes to NLLB/FLORES-200 codes; a translation
  target only works if its code is present here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("wisper")

ROOT = Path(__file__).resolve().parent.parent
LANGUAGES_PATH = ROOT / "languages.json"

_DEFAULTS = {
    "spoken": [
        {"label": "Auto-detect", "code": "auto"},
        {"label": "English", "code": "en"},
        {"label": "Russian", "code": "ru"},
        {"label": "Hebrew", "code": "he"},
        {"label": "German", "code": "de"},
        {"label": "French", "code": "fr"},
        {"label": "Spanish", "code": "es"},
    ],
    "translate_targets": [
        {"label": "English", "code": "en"},
        {"label": "Russian", "code": "ru"},
        {"label": "Hebrew", "code": "he"},
        {"label": "German", "code": "de"},
        {"label": "French", "code": "fr"},
        {"label": "Spanish", "code": "es"},
        {"label": "Ukrainian", "code": "uk"},
    ],
    "flores_codes": {
        "en": "eng_Latn",
        "ru": "rus_Cyrl",
        "he": "heb_Hebr",
        "de": "deu_Latn",
        "fr": "fra_Latn",
        "es": "spa_Latn",
        "it": "ita_Latn",
        "pt": "por_Latn",
        "pl": "pol_Latn",
        "uk": "ukr_Cyrl",
        "nl": "nld_Latn",
        "tr": "tur_Latn",
        "ar": "arb_Arab",
        "zh": "zho_Hans",
        "ja": "jpn_Jpan",
        "ko": "kor_Hang",
        "cs": "ces_Latn",
        "sv": "swe_Latn",
    },
}


def _load() -> dict:
    if LANGUAGES_PATH.exists():
        try:
            data = json.loads(LANGUAGES_PATH.read_text(encoding="utf-8"))
            # Merge: any missing section falls back to defaults.
            return {key: data.get(key, default)
                    for key, default in _DEFAULTS.items()}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("languages.json invalid (%s); using defaults", exc)
            return dict(_DEFAULTS)
    LANGUAGES_PATH.write_text(
        json.dumps(_DEFAULTS, indent=2, ensure_ascii=False), encoding="utf-8")
    return dict(_DEFAULTS)


_data = _load()

# (label, code) tuples for the tray menus.
LANGUAGES: list[tuple[str, str]] = [
    (e["label"], e["code"]) for e in _data["spoken"]]
TRANSLATE_TARGETS: list[tuple[str, str]] = [
    (e["label"], e["code"]) for e in _data["translate_targets"]]
# ISO-639-1 -> FLORES-200 for the NLLB translator.
ISO_TO_FLORES: dict[str, str] = dict(_data["flores_codes"])
