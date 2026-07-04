"""Local text translation via NLLB-200 (CTranslate2).

Runs on CPU with int8 quantization (~600 MB RAM) so it never competes with
Whisper for the 4 GB of GPU VRAM. Loaded lazily on first use; dictation
utterances are short, so CPU latency is negligible (tens of ms).

NLLB uses FLORES-200 language codes (e.g. eng_Latn, rus_Cyrl); Whisper
reports ISO-639-1 codes, mapped below.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import ctranslate2
from transformers import AutoTokenizer

# ISO-639-1 -> FLORES-200 mapping lives in the editable languages.json.
from languages import ISO_TO_FLORES

log = logging.getLogger("wisper")


class Translator:
    """Lazy-loading NLLB translator. translate() is thread-safe."""

    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        self._translator: ctranslate2.Translator | None = None
        self._tokenizer = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return (self.model_dir / "model.bin").exists()

    def _ensure_loaded(self):
        if self._translator is not None:
            return
        log.info("loading NLLB translator from %s (cpu/int8)", self.model_dir)
        self._translator = ctranslate2.Translator(
            str(self.model_dir), device="cpu", compute_type="int8"
        )
        self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
        log.info("NLLB translator loaded")

    def translate(self, text: str, src_iso: str, tgt_iso: str) -> str:
        """Translate text; returns input unchanged if languages are unmapped
        or source == target."""
        if not text or src_iso == tgt_iso:
            return text
        src = ISO_TO_FLORES.get(src_iso)
        tgt = ISO_TO_FLORES.get(tgt_iso)
        if src is None or tgt is None:
            log.warning("no FLORES mapping for %s->%s; skipping translation",
                        src_iso, tgt_iso)
            return text

        with self._lock:
            self._ensure_loaded()
            tok = self._tokenizer
            tok.src_lang = src
            tokens = tok.convert_ids_to_tokens(tok.encode(text))
            results = self._translator.translate_batch(
                [tokens], target_prefix=[[tgt]], beam_size=4
            )
            out_tokens = results[0].hypotheses[0]
            if out_tokens and out_tokens[0] == tgt:
                out_tokens = out_tokens[1:]  # drop the language prefix token
            out = tok.decode(
                tok.convert_tokens_to_ids(out_tokens), skip_special_tokens=True
            )
        return out.strip()
