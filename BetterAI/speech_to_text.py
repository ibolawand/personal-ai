"""
Speech to text with faster-whisper.

Against mishearing and phantom text:
  - voice activity detection (vad_filter): silence and noise are cut out before transcribing, which is where
    Whisper invents "Thanks for watching!" and friends
  - a word list (initial_prompt): Aria, MyNotion, app names and names Aria knows, so they come out right
  - known Whisper hallucinations are dropped when that's all that was "heard"
  - a confidence score per result (self.last_confidence, 0..1): main.py asks "did you say …?" when it's low

Speed (measured on the RTX 4070, Whisper medium): 0.2 s per sentence on the GPU against 2.6 s on the CPU, same text.
It runs on the GPU when it can (about 1.1 GB next to the chat model's 5.6 GB) and falls back to the CPU.
STT_DEVICE=cpu forces the CPU. The end of a sentence is SILENCE_S of quiet (it was 2 s: dead time on every turn).
"""

import os
import time

import math
import re

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

BASE_WORDS = ["Aria", "MyNotion", "Spotify", "PyCharm", "VS Code", "Packet Tracer", "Discord", "Chrome", "to-do list",
              "shopping list", "calendar", "remind me", "focus session", "Lina", "Sara"]
# what Whisper "hears" in silence or noise (from its YouTube-subtitle training data)
HALLUCINATIONS = re.compile(
    r"^\W*(thanks? (you )?for watching|thank you( so much)?( for watching)?|please subscribe|subscribe|"
    r"like and subscribe|see you (in the )?next (time|video)|bye\W*|you|so|\.+|music|applause|"
    r"subtitles by.*|amara\.org.*|www\..*|alright, have a great (week|day))\W*$", re.I)
LOW_CONFIDENCE = 0.45
SILENCE_S = 1.2           # seconds of quiet that end what you said (a short pause mid-sentence is fine)


class STTEngine:
    def __init__(self, model_size="medium", device=None):
        print("[STT] Loading Whisper model...")
        self.model, self.device = self._load(model_size, device or os.environ.get("STT_DEVICE", "auto"))
        print(f"[STT] Whisper {model_size} on the {self.device.upper()}")
        self.sample_rate = 16000
        self.silence_threshold = 0.01
        self.silence_duration = float(os.environ.get("STT_SILENCE_S", SILENCE_S))  # quiet that ends a sentence
        self.last_timing = {}        # {"transcribe": s} of the last listen(), for the speed log
        self.max_duration = 30.0     # max recording time
        self.on_level = None         # optional fn(volume: float) for UI meters
        self.vocabulary = lambda: [] # optional fn() -> extra words (names Aria knows), set by Aria
        self.last_confidence = 1.0

    @staticmethod
    def _load(model_size, device):
        if device in ("auto", "cuda"):
            try:
                import torch  # noqa: F401  (loads the CUDA libraries faster-whisper needs: libcublas)
                return WhisperModel(model_size, device="cuda", compute_type="int8_float16"), "gpu"
            except Exception as e:
                print(f"[STT] GPU not usable ({str(e)[:80]}), using the CPU")
        return WhisperModel(model_size, device="cpu", compute_type="int8"), "cpu"

    def _record(self, start_timeout=None):
        """Records until silence. Returns None if nobody starts speaking within start_timeout seconds."""
        print("[STT] Listening...")
        frames = []
        silent_frames = 0
        speaking = False
        frames_per_buffer = 1024
        silence_limit = int(self.silence_duration * self.sample_rate / frames_per_buffer)
        start_limit = int(start_timeout * self.sample_rate / frames_per_buffer) if start_timeout else None

        with sd.InputStream(samplerate=self.sample_rate, channels=1,
                           dtype='float32', blocksize=frames_per_buffer) as stream:
            while True:
                data, _ = stream.read(frames_per_buffer)
                frames.append(data.copy())
                volume = np.abs(data).mean()
                if self.on_level:
                    self.on_level(float(volume))

                if volume > self.silence_threshold:
                    speaking = True
                    silent_frames = 0
                elif speaking:
                    silent_frames += 1
                    if silent_frames >= silence_limit:
                        break

                if not speaking and start_limit and len(frames) >= start_limit:
                    return None

                # Hard cap
                if len(frames) > int(self.max_duration * self.sample_rate / frames_per_buffer):
                    break

        return np.concatenate(frames, axis=0).flatten()

    def _prompt(self) -> str:
        try:
            extra = [w for w in self.vocabulary() if w]
        except Exception:
            extra = []
        words = list(dict.fromkeys(BASE_WORDS + extra))[:60]
        return "Talking to Aria, my desk assistant. Words: " + ", ".join(words) + "."

    def transcribe(self, audio) -> tuple[str, float]:
        """(text, confidence 0..1). Empty text when only silence, noise or a known hallucination was heard."""
        segments, _ = self.model.transcribe(
            audio, language="en", vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            initial_prompt=self._prompt(), condition_on_previous_text=False)
        kept, probs = [], []
        for seg in segments:
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8:
                continue                          # Whisper itself thinks nobody spoke
            kept.append(seg.text)
            probs.append(math.exp(seg.avg_logprob))
        text = " ".join(t.strip() for t in kept).strip()
        if not text or HALLUCINATIONS.match(text):
            return "", 0.0
        return text, min(probs) if probs else 0.0

    def listen(self, start_timeout=None):
        audio = self._record(start_timeout)
        if audio is None:
            return None
        print("[STT] Transcribing...")
        t = time.time()
        text, self.last_confidence = self.transcribe(audio)
        self.last_timing = {"transcribe": time.time() - t, "silence_wait": self.silence_duration,
                            "audio_s": len(audio) / self.sample_rate}
        print(f"[STT] Heard: {text!r} (confidence {self.last_confidence:.2f})")
        return text or None

    def listen_short(self, timeout=0.5):
        """
        Quick listen — returns immediately if no speech detected within timeout.
        Used for interruption detection while Aria is speaking.
        """
        frames = []
        spoke = False
        frames_per_buffer = 1024
        max_frames = int(timeout * self.sample_rate / frames_per_buffer)

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1,
                                dtype='float32', blocksize=frames_per_buffer) as stream:
                for _ in range(max_frames):
                    data, _ = stream.read(frames_per_buffer)
                    frames.append(data.copy())
                    if np.abs(data).mean() > self.silence_threshold:
                        spoke = True
                        break

            if not spoke:
                return None

            # Capture the rest of what they're saying
            return self.listen()
        except Exception:
            return None