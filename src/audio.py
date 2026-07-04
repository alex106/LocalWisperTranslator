"""Microphone capture via sounddevice.

Records 16 kHz mono float32 - exactly what Whisper expects, so no ffmpeg
and no resampling are needed. start() begins streaming into an in-memory
buffer; stop() closes the stream and returns the concatenated numpy array.
"""
from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1


class Recorder:
    def __init__(self, device: int | None = None, samplerate: int = SAMPLE_RATE):
        self.device = device
        self.samplerate = samplerate
        self._stream: sd.InputStream | None = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self.last_rms: float = 0.0  # live mic level for the waveform overlay

    @property
    def recording(self) -> bool:
        return self._recording

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        # Copy: sounddevice reuses the buffer after the callback returns.
        with self._lock:
            self._frames.append(indata.copy())
        self.last_rms = float(np.sqrt(np.mean(indata ** 2)))

    def start(self):
        if self._recording:
            return
        with self._lock:
            self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=CHANNELS,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        self._recording = True

    def stop(self) -> np.ndarray:
        """Stop recording and return mono float32 audio (empty array if none)."""
        if not self._recording:
            return np.zeros(0, dtype=np.float32)
        self._recording = False
        self.last_rms = 0.0
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(frames, axis=0)
        return audio.reshape(-1).astype(np.float32)  # flatten to mono 1-D


def list_input_devices() -> list[tuple[int, str]]:
    """Return (index, name) for available input-capable devices."""
    devices = sd.query_devices()
    out = []
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            out.append((idx, dev["name"]))
    return out
