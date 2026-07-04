"""faster-whisper wrapper.

Loads the model once (GPU int8_float16 by default so large-v3 fits in ~2GB
VRAM) and transcribes a mono float32 @16 kHz numpy array. Language "auto"
maps to Whisper auto-detection.
"""
from __future__ import annotations

import numpy as np

import cuda_setup  # noqa: F401  # registers NVIDIA DLL dirs before ct2 loads
from faster_whisper import WhisperModel

from config import Config


class Transcriber:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.model: WhisperModel | None = None
        self._loaded_key: tuple | None = None
        self.load()

    def _model_source(self) -> str:
        # A local directory of CT2 weights takes precedence over the model id.
        return self.cfg.model_dir or self.cfg.model

    def _key(self) -> tuple:
        return (self._model_source(), self.cfg.device, self.cfg.compute_type)

    def load(self):
        """(Re)load the model if the relevant config changed."""
        if self.model is not None and self._key() == self._loaded_key:
            return
        self.model = WhisperModel(
            self._model_source(),
            device=self.cfg.device,
            compute_type=self.cfg.compute_type,
            local_files_only=self.cfg.local_files_only,
        )
        self._loaded_key = self._key()

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        """Return (text, detected_language_iso). Empty text if too short."""
        if self.model is None:
            self.load()
        if audio is None or audio.size == 0:
            return "", ""
        duration = audio.size / 16000.0
        if duration < self.cfg.min_audio_seconds:
            return "", ""

        language = None if self.cfg.language == "auto" else self.cfg.language
        segments, info = self.model.transcribe(
            audio,
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text, info.language
