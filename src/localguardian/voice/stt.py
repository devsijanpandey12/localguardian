"""Offline Speech-to-Text running on CPU (`faster-whisper`, int8).

Keeping STT on the Ryzen 7 CPU leaves 100% of GPU VRAM free for Ollama.
"""

from __future__ import annotations

from typing import Optional

from localguardian.config import LocalGuardianConfig


class LocalTranscriber:
    """Lazy-loading offline faster-whisper transcriber."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore

            self._model = WhisperModel(
                self.config.voice.stt_model,
                device=self.config.voice.stt_device,
                compute_type=self.config.voice.stt_compute_type,
            )
        return self._model

    def transcribe_array(self, audio_float32) -> str:
        """Transcribe a 16 kHz mono float32 numpy array into plain text."""
        model = self._load()
        segments, _info = model.transcribe(audio_float32, beam_size=3, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text.strip()

    def transcribe_file(self, wav_path: str) -> str:
        model = self._load()
        segments, _info = model.transcribe(wav_path, beam_size=3, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        return text.strip()
