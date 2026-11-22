"""Offline Speech-to-Text on CPU supporting both `faster-whisper` and `cactus-whistle`.

- `faster-whisper` (`base.en`, CPU `int8`): strong general English accuracy (~250 MB RAM, 0 VRAM).
- `cactus-whistle` (`cactus.Whistle`): ultra-light ~16.9 MB on-device ASR from `cactus-compute` (0 VRAM).
"""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path

from localguardian.config import LocalGuardianConfig


def _write_16khz_wav(audio_float32, sample_rate: int = 16000) -> str:
    import numpy as np  # type: ignore

    clipped = np.clip(audio_float32, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return path


class LocalTranscriber:
    """Lazy-loading offline STT supporting `faster-whisper` and `cactus-whistle`."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config
        self._whisper_model = None
        self._whistle_model = None

    @property
    def backend(self) -> str:
        return self.config.voice.stt_backend.strip().lower()

    def _load_whisper(self):
        if self._whisper_model is None:
            from faster_whisper import WhisperModel  # type: ignore

            self._whisper_model = WhisperModel(
                self.config.voice.stt_model,
                device=self.config.voice.stt_device,
                compute_type=self.config.voice.stt_compute_type,
            )
        return self._whisper_model

    def _load_whistle(self):
        if self._whistle_model is None:
            if self.config.needle.disable_telemetry:
                os.environ.setdefault("CACTUS_TELEMETRY", "0")
            import cactus  # type: ignore

            self._whistle_model = cactus.Whistle()
        return self._whistle_model

    def transcribe_array(self, audio_float32) -> str:
        """Transcribe a 16 kHz mono float32 numpy array into plain text."""
        if self.backend in {"cactus-whistle", "whistle"}:
            wav_path = _write_16khz_wav(audio_float32, self.config.voice.sample_rate)
            try:
                return self.transcribe_file(wav_path)
            finally:
                try:
                    Path(wav_path).unlink(missing_ok=True)
                except Exception:
                    pass

        model = self._load_whisper()
        segments, _info = model.transcribe(audio_float32, beam_size=3, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text.strip()

    def transcribe_file(self, wav_path: str) -> str:
        if self.backend in {"cactus-whistle", "whistle"}:
            whistle = self._load_whistle()
            res = whistle.transcribe(wav_path)
            if isinstance(res, dict):
                return str(res.get("text") or "").strip()
            return str(res or "").strip()

        model = self._load_whisper()
        segments, _info = model.transcribe(wav_path, beam_size=3, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text.strip()
