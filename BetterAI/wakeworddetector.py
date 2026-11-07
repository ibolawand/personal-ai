"""
Wake word, in two steps:
  1. a small openWakeWord model listens all the time: "hey Aria" (models/hey_aria.onnx, trained with
     tools/train_wakeword.py), or the built-in "hey Jarvis" when that file is missing or WAKE_WORD=jarvis;
  2. when it fires, Whisper transcribes the last 2.5 seconds and only a real "Aria" wakes her (verify callback from
     main.py), or nothing at all when the model was fairly sure (Whisper often makes out no words in a quiet clip). The model is trained on synthetic voices, so on its own it would wake up for TV or YouTube now and then;
     Whisper on the GPU checks in ~0.2 s. Rejected detections go to the problem log.
"""

import os
import time
from collections import deque
from pathlib import Path

import numpy as np
import pyaudio
from openwakeword.model import Model
from openwakeword.utils import download_models

ARIA_MODEL = Path(__file__).resolve().parent / "models" / "hey_aria.onnx"
VERIFY_SECONDS = 2.5
# the model fired but Whisper made out no words at all (a quiet or clipped "hey Aria"): wake anyway above this.
# Whisper hearing *other* words (a video, someone talking) still means no.
HEARD_NOTHING_WAKE = 0.6


def wake_model_path():
    """(path or built-in name, label for messages)."""
    if os.environ.get("WAKE_WORD", "aria").lower() != "jarvis" and ARIA_MODEL.exists():
        return str(ARIA_MODEL), "hey Aria"
    return "hey_jarvis", "hey Jarvis"


class WakeWordDetector:
    def __init__(self, threshold=None, verify=None):
        """verify: optional fn(audio float32 16 kHz) -> (ok: bool, heard: str), called before waking."""
        download_models()  # once at init, not at import time
        model, self.phrase = wake_model_path()
        self.model = Model(wakeword_models=[model], inference_framework="onnx")
        self.verify = verify if self.phrase == "hey Aria" else None     # Whisper checks for "Aria", not "Jarvis"
        # Measured on 4 voices it never trained on: every "hey Aria" scores above 0.98; ordinary sentences fire it
        # 4 in 120 times at 0.5 and 2 in 120 at 0.9. With Whisper confirming, the lower bar is safer for a real voice
        # (the model only heard synthetic ones); without it, the stricter one.
        default = (0.5 if self.verify else 0.9) if self.phrase == "hey Aria" else 0.7
        self.threshold = float(os.environ.get("WAKE_THRESHOLD", threshold or default))
        self.p = pyaudio.PyAudio()
        self.chunk_size = 1280      # 80 ms at 16 kHz
        self.sample_rate = 16000
        self._recent = deque(maxlen=int(VERIFY_SECONDS * self.sample_rate / self.chunk_size))
        print(f"[Wake] Wake word: {self.phrase} (threshold {self.threshold}"
              f"{', confirmed by Whisper' if verify else ''})")

    def _confirmed(self, score) -> bool:
        if not self.verify:
            return True
        audio = np.frombuffer(b"".join(self._recent), dtype=np.int16).astype(np.float32) / 32768
        try:
            ok, heard = self.verify(audio)
        except Exception as e:
            print(f"[Wake] verification failed ({e}), waking anyway")
            return True
        if not ok and not (heard or "").strip() and score >= HEARD_NOTHING_WAKE:
            print(f"[Wake] {score:.2f}, Whisper heard nothing clear: waking")
            return True
        if not ok:
            print(f"[Wake] {score:.2f} but Whisper heard {heard!r}: not waking")
            try:
                from Engines import Diagnostics
                Diagnostics.problem("wake_unconfirmed", f"{score:.2f}: {heard}")
            except Exception:
                pass
        return ok

    def listen_for_wake_word(self, stop_event=None, cooldown=3.0) -> bool:
        """Blocks until the wake word is heard (True) or stop_event is set (False)."""
        print("[Wake] Sleeping... say the wake word to activate.")
        self.model.reset()
        self._recent.clear()
        stream = self.p.open(
            format=pyaudio.paInt16, channels=1, rate=self.sample_rate,
            input=True, frames_per_buffer=self.chunk_size,
        )
        try:
            # Drain the mic so Aria's own voice / leftover noise isn't scored
            end = time.time() + cooldown
            while time.time() < end:
                if stop_event and stop_event.is_set():
                    return False
                stream.read(self.chunk_size, exception_on_overflow=False)

            print("[Wake] Ready and listening for wake word.")
            while not (stop_event and stop_event.is_set()):
                audio = stream.read(self.chunk_size, exception_on_overflow=False)
                self._recent.append(audio)
                predictions = self.model.predict(np.frombuffer(audio, dtype=np.int16))
                score = max(predictions.values())
                if score > self.threshold:
                    # let the word finish (a few more chunks), then check what was actually said
                    for _ in range(4):
                        self._recent.append(stream.read(self.chunk_size, exception_on_overflow=False))
                    self.model.reset()
                    if self._confirmed(score):
                        print(f"[Wake] Wake word detected! ({score:.2f})")
                        return True
                    self._recent.clear()
            return False
        finally:
            stream.stop_stream()
            stream.close()

    def close(self):
        self.p.terminate()
