"""
Speech to text with faster-whisper.

Against mishearing and phantom text:
  - voice activity detection (vad_filter): silence and noise are cut out before transcribing, which is where
    Whisper invents "Thanks for watching!" and friends
  - a word list (initial_prompt): Aria, MyNotion, app names and names Aria knows, so they come out right
  - known Whisper hallucinations are dropped when that's all that was "heard"
  - a confidence score per result (self.last_confidence, 0..1): main.py asks "did you say …?" when it's low

Knowing when you talk (_record): Silero voice detection (the one faster-whisper ships) decides when speech starts and
ends, not loudness. With a loudness threshold, a fan, music or a video kept the recording going for up to 30 s and
Whisper then wrote all of it out as if you'd said it. A third of a second before speech starts is kept, so the first
word isn't clipped. If the detector can't load, it falls back to loudness.

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

HINT_COPY = 0.6     # a segment this much made of hint words (and 4+ words long) is the hint read back
BASE_WORDS = ["Aria", "MyNotion", "Spotify", "PyCharm", "VS Code", "Packet Tracer", "Discord", "Chrome", "to-do list",
              "shopping list", "calendar", "remind me", "focus session", "Lina", "Sara"]
# what Whisper "hears" in silence or noise (from its YouTube-subtitle training data)
HALLUCINATIONS = re.compile(
    r"^\W*(thanks? (you )?for watching|thank you( so much)?( for watching)?|please subscribe|subscribe|"
    r"like and subscribe|see you (in the )?next (time|video)|bye\W*|you|so|\.+|music|applause|"
    r"subtitles by.*|amara\.org.*|www\..*|alright, have a great (week|day))\W*$", re.I)
LOW_CONFIDENCE = 0.45
SILENCE_S = 1.2           # seconds of quiet that end what you said (a short pause mid-sentence is fine)
SPEECH_ON = 0.5           # voice detector probability that counts as speech
SPEECH_OFF = 0.3          # ...and below this it's a pause (in between: keeps the current state)
SPEECH_START_BLOCKS = 2   # this many blocks in a row (~130 ms) before it counts as you starting to talk
PRE_ROLL_S = 0.35         # kept from before speech started, so the first word isn't cut off
VAD_WINDOW = 8192         # samples the detector looks at each block (0.5 s of context)
MAX_COMPRESSION = 2.4     # a segment that repeats itself this much is a Whisper loop, not speech
MIN_LOGPROB = -1.0        # a segment Whisper is this unsure about is dropped


def _load_vad():
    try:
        from faster_whisper.vad import get_vad_model
        model = get_vad_model()
        model(np.zeros(VAD_WINDOW, dtype=np.float32))
        return model
    except Exception as e:
        print(f"[STT] Voice detector unavailable ({str(e)[:80]}), using loudness")
        return None


class STTEngine:
    def __init__(self, model_size="medium", device=None):
        print("[STT] Loading Whisper model...")
        self.model_size = model_size
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
        self.last_level = 0.0              # loudness of the last speech (see _record)
        self.last_language = None          # (language, probability) of the last speech
        self.vad = _load_vad()

    def _on_any_device(self, work):
        """work(model) on the GPU model; when the graphics card is full ("CUDA failed with error out of memory",
        which used to shut Aria down), the same on a CPU copy: slower, but she still hears you."""
        try:
            return work(self.model)
        except RuntimeError as e:
            if "out of memory" not in str(e).lower():
                raise
            print("[STT] graphics card full, transcribing on the CPU this time")
            try:
                from Engines import Diagnostics
                Diagnostics.problem("stt_gpu_full")
            except Exception:
                pass
            if getattr(self, "_cpu_model", None) is None:
                self._cpu_model = WhisperModel(getattr(self, "model_size", "medium"), device="cpu", compute_type="int8")
            return work(self._cpu_model)

    @staticmethod
    def _load(model_size, device):
        if device in ("auto", "cuda"):
            try:
                import torch  # noqa: F401  (loads the CUDA libraries faster-whisper needs: libcublas)
                return WhisperModel(model_size, device="cuda", compute_type="int8_float16"), "gpu"
            except Exception as e:
                print(f"[STT] GPU not usable ({str(e)[:80]}), using the CPU")
        return WhisperModel(model_size, device="cpu", compute_type="int8"), "cpu"

    def _speech_prob(self, recent: np.ndarray) -> float:
        """How likely the newest block is speech (0..1). Without the detector: loudness."""
        if self.vad is None:
            return 1.0 if np.abs(recent[-1024:]).mean() > self.silence_threshold else 0.0
        window = recent[-VAD_WINDOW:]
        if len(window) < VAD_WINDOW:
            window = np.concatenate([np.zeros(VAD_WINDOW - len(window), dtype=np.float32), window])
        out = np.asarray(self.vad(window)).ravel()
        return float(out[-2:].max())         # the last two 32 ms frames = this block

    def has_voice(self, audio) -> bool:
        """Is anyone speaking anywhere in this clip? Real "hey Aria"s score 0.98+, static, hum and clicks at most 0.36."""
        if self.vad is None:
            return True
        audio = np.asarray(audio, dtype=np.float32)
        audio = np.concatenate([audio, np.zeros((-len(audio)) % 512, dtype=np.float32)])
        return float(np.max(np.asarray(self.vad(audio)))) >= SPEECH_ON

    def _record(self, start_timeout=None, max_duration=None, stop=None):
        """Records one utterance: from when speech starts until silence_duration without speech.
        Returns None if nobody starts speaking within start_timeout seconds, or `stop()` turns true before that."""
        print("[STT] Listening...")
        block = 1024
        rate = self.sample_rate
        silence_limit = int(self.silence_duration * rate / block)
        start_limit = int(start_timeout * rate / block) if start_timeout else None
        max_blocks = int((max_duration or self.max_duration) * rate / block)
        pre_roll = max(1, int(PRE_ROLL_S * rate / block))
        recent = np.zeros(0, dtype=np.float32)     # rolling audio for the detector
        frames, waited, voiced, silent = [], 0, 0, 0
        speaking = False
        levels = []                                 # loudness of the blocks that are speech

        with sd.InputStream(samplerate=rate, channels=1, dtype='float32', blocksize=block) as stream:
            while True:
                data, _ = stream.read(block)
                data = data[:, 0].copy()
                if self.on_level:
                    self.on_level(float(np.abs(data).mean()))
                recent = np.concatenate([recent, data])[-VAD_WINDOW:]
                prob = self._speech_prob(recent)
                frames.append(data)

                if prob >= SPEECH_ON:
                    levels.append(float(np.abs(data).mean()))
                if not speaking:
                    voiced = voiced + 1 if prob >= SPEECH_ON else 0
                    if voiced >= SPEECH_START_BLOCKS:
                        speaking = True
                        frames = frames[-(pre_roll + voiced):]
                        silent = 0
                        continue
                    frames = frames[-(pre_roll + SPEECH_START_BLOCKS):]
                    waited += 1
                    if (start_limit and waited >= start_limit) or (stop and not voiced and stop()):
                        return None
                    continue

                if prob < SPEECH_OFF:
                    silent += 1
                    if silent >= silence_limit:
                        break
                elif prob >= SPEECH_ON:
                    silent = 0
                if len(frames) >= max_blocks:
                    break

        # how loud the speech was: someone right at the mic is much louder than a person across the room or a video
        self.last_level = float(np.median(levels)) if levels else 0.0
        return np.concatenate(frames)

    def _prompt(self) -> str:
        try:
            extra = [w for w in self.vocabulary() if w]
        except Exception:
            extra = []
        words = list(dict.fromkeys(BASE_WORDS + extra))[:60]
        return "Talking to Aria, my desk assistant. Words: " + ", ".join(words) + "."

    @staticmethod
    def _words(text) -> list:
        return re.findall(r"[a-z0-9#+']+", (text or "").lower())

    def _reads_back(self, text, hint_words) -> bool:
        """Is this segment Whisper copying the word hint ("aria, mynotion, spotify, pycharm, …") instead of speech?"""
        words = self._words(text)
        return len(words) >= 4 and sum(w in hint_words for w in words) >= HINT_COPY * len(words)

    def transcribe(self, audio) -> tuple[str, float]:
        """(text, confidence 0..1). Empty text when only silence, noise or a known hallucination was heard."""
        prompt = self._prompt()
        hint_words = set(self._words(prompt.split("Words:", 1)[-1]))
        segments = self._on_any_device(lambda model: list(model.transcribe(
            audio, language="en", vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            initial_prompt=prompt, condition_on_previous_text=False)[0]))
        kept, probs = [], []
        for seg in segments:
            if self._reads_back(seg.text, hint_words):
                continue                          # the word hint read back, nobody said it
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -0.8:
                continue                          # Whisper itself thinks nobody spoke
            if seg.compression_ratio > MAX_COMPRESSION or seg.avg_logprob < MIN_LOGPROB:
                continue                          # a repeating loop, or a guess
            if any(seg.text.strip().lower() == k.strip().lower() for k in kept):
                continue                          # the same sentence again
            kept.append(seg.text)
            probs.append(math.exp(seg.avg_logprob))
        text = " ".join(t.strip() for t in kept).strip()
        if not text or HALLUCINATIONS.match(text):
            return "", 0.0
        return text, min(probs) if probs else 0.0

    def transcribe_short(self, audio) -> str:
        """A 2-3 s clip (the wake word check): no noise filter or confidence cut-offs, which can drop a short
        "hey Aria" entirely. Only the known phantom phrases are removed."""
        segments = self._on_any_device(lambda model: list(model.transcribe(
            audio, language="en", vad_filter=False, initial_prompt="Hey Aria.", condition_on_previous_text=False)[0]))
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return "" if HALLUCINATIONS.match(text) else text

    def listen(self, start_timeout=None, max_duration=None, stop=None):
        audio = self._record(start_timeout, max_duration, stop)
        if audio is None:
            return None
        print("[STT] Transcribing...")
        t = time.time()
        text, self.last_confidence = self.transcribe(audio)
        self.last_language = None
        if text:
            try:                            # which language it really was (the transcript is forced to English)
                lang, prob, _ = self._on_any_device(lambda model: model.detect_language(audio))
                self.last_language = (lang, float(prob))
            except Exception:
                pass
        self.last_timing = {"transcribe": time.time() - t, "silence_wait": self.silence_duration,
                            "audio_s": len(audio) / self.sample_rate}
        print(f"[STT] Heard: {text!r} (confidence {self.last_confidence:.2f})")
        return text or None

    def listen_short(self, timeout=0.5, stop=None):
        """While Aria is speaking: waits up to `timeout` for speech, then records it (at most 10 s).
        `stop()` ends the wait early (she finished talking), but never cuts off someone mid-sentence."""
        try:
            return self.listen(start_timeout=timeout, max_duration=10.0, stop=stop)
        except Exception:
            return None
