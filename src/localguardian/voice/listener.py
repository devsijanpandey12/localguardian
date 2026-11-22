"""Microphone capture for LocalGuardian push-to-talk prototype testing."""

from __future__ import annotations

import threading
from typing import List, Optional

from localguardian.config import LocalGuardianConfig


class PushToTalkListener:
    """Records 16 kHz mono audio from the default Windows mic on Enter press."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config

    def record_until_enter(self) -> Optional[object]:
        """Start recording immediately and stop when the user presses Enter."""
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore

        sr = self.config.voice.sample_rate
        chunks: List[np.ndarray] = []
        stop_event = threading.Event()

        def _callback(indata, _frames, _time_info, _status):
            if not stop_event.is_set():
                chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=sr,
            channels=1,
            dtype="float32",
            callback=_callback,
        ):
            input("  [Recording... speak your command, then press ENTER to stop] ")
            stop_event.set()

        if not chunks:
            return None
        audio = np.concatenate(chunks, axis=0).flatten()
        return audio
