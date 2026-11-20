import re
import os
import queue
import string
import tempfile
import threading
import time

import numpy as np
import pyaudio
from scipy import signal
import soundfile as sf
from gradio_client import Client

from Engines import LipSync, VoiceStyle

# --- WHICH TTS ---
# kokoro (default): small and smooth, runs on the CPU so the whole GPU stays free for the LLM.
# chatterbox: clones Engines/ref_voice.wav, but takes ~4 GB of VRAM and pushes the LLM onto the CPU.
TTS_ENGINE = os.environ.get("TTS_ENGINE", "kokoro").lower()
# Her voice fits her avatar (a young, playful anime girl): a blend of af_heart (Kokoro's clearest voice) and the
# brighter af_bella, lifted VOICE_LIFT semitones (pitch and voice size together, as a younger, smaller speaker):
# ~230 Hz instead of af_heart's mature ~205 Hz. "name*weight+name*weight" blends; VOICE_LIFT=0 turns the lift off.
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart*0.5+af_bella*0.5")
VOICE_LIFT = float(os.environ.get("VOICE_LIFT", "2.0"))
KOKORO_DEVICE = os.environ.get("KOKORO_DEVICE", "cpu")
# Claude's voice when he talks with her (Engines/Duet.py): a calm male voice, so you hear who is who
CLAUDE_VOICE = os.environ.get("CLAUDE_VOICE", "am_michael")
CLAUDE_LIFT = float(os.environ.get("CLAUDE_LIFT", "0"))
KOKORO_SR = 24000

# --- CHATTERBOX CONFIG ---
AUDIO_PROMPT_PATH = "/home/lala/Desktop/school/personal/personal-ai/BetterAI/Engines/ref_voice.wav"   # relative to where you start the script   # e.g. "ref_voice.wav" (5-10 s clean clip) to steer voice + rhythm
CHATTERBOX_DEVICE = "cuda"

# --- RVC GRADIO CLIENT CONFIG ---
RVC_API_URL = "http://127.0.0.1:7865/"
RVC_INDEX_PATH = r"C:\RVC\RVC1006Nvidia\assets\weights\added_IVF2182_Flat_nprobe_1_egirl.index"
RVC_METHOD = "rmvpe"
RVC_ENABLED = os.environ.get("RVC_ENABLED") == "1"   # Windows RVC Gradio server; off unless set
RVC_INDEX_RATE = 0.5       # lower = keeps more of the original expressiveness

MIN_INTERRUPT_RMS = 500

NOISE_FILLERS = {
    "uh", "um", "mm", "hmm", "ah", "oh", "hm", "mhm",
    "cough", "throat", "laughter", "noise",
}
AI_NAMES = {"aria"}
INTERRUPT_MIN_CONFIDENCE = 0.5   # an unsure transcript while she talks is usually her own voice, or a guess
ECHO_OVERLAP = 0.6               # this share of the heard words in what she's saying = her own voice from the speakers
LEAD_HOOKS = (
    "stop", "wait", "hold on", "hang on", "actually",
    "no", "shut up", "listen", "sorry", "excuse me", "please",
)

# Calmer delivery: lower exaggeration = less dramatic, lower cfg = slower, more relaxed pace.
# (Was 0.5–1.0 exaggeration; "excited" at 1.0 was shouty.)
# speed is used by Kokoro (it has no emotion control); the rest by Chatterbox/RVC
MOOD_SETTINGS = {
    "neutral": {"exaggeration": 0.4,  "cfg": 0.4,  "pitch": 0,  "speed": 1.0},
    "happy":   {"exaggeration": 0.5,  "cfg": 0.4,  "pitch": 1,  "speed": 1.04},
    "sad":     {"exaggeration": 0.35, "cfg": 0.45, "pitch": -1, "speed": 0.92},
    "angry":   {"exaggeration": 0.55, "cfg": 0.35, "pitch": 0,  "speed": 0.98},
    "excited": {"exaggeration": 0.6,  "cfg": 0.35, "pitch": 2,  "speed": 1.06},
}

# --- EAR-FRIENDLY AUDIO ---
VOICE_GAIN = float(os.environ.get("VOICE_GAIN", "1.0"))   # overall loudness, set in Engines/.env
TARGET_RMS = 0.07          # every sentence normalised to this (≈ -23 dBFS): no loud/quiet jumps
LAUGH_WORD = "Hah!"         # how she laughs out loud ("haha", "lol", "*laughs*" in a reply): _synthesize_piece
PEAK_LIMIT = 0.6           # soft ceiling, so plosives and laughs never spike
# How each sentence is said (emotion, colour, pace, pauses, laughs) is decided in Engines/VoiceStyle.py.


def blend_voice(pipeline, spec: str):
    """Kokoro voice pack for "af_heart" or a weighted blend "af_heart*0.5+af_bella*0.5" (the voice embeddings
    averaged, which is how Kokoro's own blended voices are made)."""
    parts = []
    for part in spec.split("+"):
        name, _, weight = part.strip().partition("*")
        parts.append((name.strip(), float(weight) if weight else 1.0))
    if len(parts) == 1:
        return parts[0][0]
    total = sum(w for _, w in parts)
    return sum(pipeline.load_single_voice(n) * (w / total) for n, w in parts)


def lift_rate(semitones: float) -> float:
    """How much faster `lift` plays the voice: Kokoro is asked for speech this much slower, so the pace stays."""
    return 2 ** (semitones / 12)


def lift(audio: np.ndarray, semitones: float) -> np.ndarray:
    """Raise the voice `semitones` by playing it faster (resampling): pitch and formants go up together, like a
    smaller vocal tract, which sounds younger and lighter rather than "pitch-shifted", and adds no artifacts.
    The audio gets shorter by the same factor."""
    if not semitones or audio is None or len(audio) == 0:
        return audio
    rate = lift_rate(semitones)
    return signal.resample_poly(audio, 1000, round(1000 * rate)).astype(np.float32)


def speech_span(audio: np.ndarray, sr: int) -> tuple[int, int]:
    """Where the speech in `audio` starts and ends (samples), with 40 ms of air kept each side: what polish_audio
    keeps. (Her mouth's timeline is moved back by the start, so it stays on the sound.)"""
    audio = np.asarray(audio, dtype=np.float32)
    if len(audio) < sr // 20:
        return 0, len(audio)
    env = np.abs(audio - float(np.mean(audio)))
    idx = np.where(env > max(0.01, 0.05 * float(np.max(env))))[0]
    if not len(idx):
        return 0, len(audio)
    pad = int(0.04 * sr)
    return max(0, int(idx[0]) - pad), min(len(audio), int(idx[-1]) + pad)


def polish_audio(audio: np.ndarray, sr: int) -> np.ndarray:
    """Make TTS output easier on the ears: trim, de-rumble, soften harsh highs,
    tame sibilance, level the volume, soft-limit peaks, and fade the edges (no clicks)."""
    if audio is None:
        return audio
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)
    if len(audio) < sr // 20:
        audio = np.clip(audio, -PEAK_LIMIT, PEAK_LIMIT).copy()
        edge = min(len(audio) // 2, int(0.01 * sr))
        if edge > 1:
            audio[:edge] *= np.linspace(0, 1, edge)
            audio[-edge:] *= np.linspace(1, 0, edge)
        return audio
    audio = audio - float(np.mean(audio))

    # trim silence / breath noise at the ends (keeps 40 ms of air)
    start, end = speech_span(audio, sr)
    audio = audio[start:end]

    nyq = sr / 2
    # rumble below 80 Hz
    audio = signal.sosfilt(signal.butter(2, 80 / nyq, "highpass", output="sos"), audio)
    # harshness: gentle roll-off above ~8.5 kHz
    if nyq > 9000:
        audio = signal.sosfilt(signal.butter(2, 8500 / nyq, "lowpass", output="sos"), audio)
    # de-esser: when the 5–9 kHz band gets loud, turn just that band down
    hi = min(9000, nyq * 0.95)
    if hi > 5000:
        band = signal.sosfilt(signal.butter(2, [5000 / nyq, hi / nyq], "bandpass", output="sos"), audio)
        win = max(1, int(0.005 * sr))
        band_env = np.sqrt(np.convolve(band ** 2, np.ones(win) / win, mode="same"))
        full_env = np.sqrt(np.convolve(audio ** 2, np.ones(win) / win, mode="same")) + 1e-6
        excess = np.clip(band_env / full_env - 0.35, 0, None)       # sibilant when band dominates
        audio = audio - band * np.clip(excess * 1.5, 0, 0.6)

    # level every sentence to the same loudness
    rms = float(np.sqrt(np.mean(audio ** 2)))
    if rms > 1e-4:
        audio = audio * (TARGET_RMS / rms) * VOICE_GAIN
    # soft limiter
    audio = PEAK_LIMIT * np.tanh(audio / PEAK_LIMIT)

    # fades: 15 ms in, 40 ms out
    fi, fo = int(0.015 * sr), int(0.04 * sr)
    if len(audio) > fi + fo:
        audio[:fi] *= np.linspace(0, 1, fi)
        audio[-fo:] *= np.linspace(1, 0, fo)
    return audio.astype(np.float32)

# --- TEXT CLEANING ---
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U0001F000-\U0001F2FF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000027BF"
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "]+",
    flags=re.UNICODE,
)
URL_RE = re.compile(r'https?://\S+|www\.\S+')
TIME_AMPM_RE = re.compile(r'\b(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?')
TIME24_RE = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[AaPp]\.?[Mm])')
DATE_ISO_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _spoken_time(hour: int, minute: int, is_pm: bool) -> str:
    if not is_pm:
        part = "in the morning"
    elif hour == 12 or hour < 6:
        part = "in the afternoon"
    else:
        part = "in the evening"
    if minute == 0:
        return f"{hour} {part}"
    if minute < 10:
        return f"{hour} oh {minute} {part}"
    return f"{hour} {minute} {part}"


def _say_time_ampm(m: re.Match) -> str:
    return _spoken_time(int(m.group(1)), int(m.group(2)), m.group(3).lower() == "p")


def _say_time24(m: re.Match) -> str:
    hour, minute = int(m.group(1)), int(m.group(2))
    is_pm = hour >= 12
    return _spoken_time(hour % 12 or 12, minute, is_pm)


def _say_date(m: re.Match) -> str:
    return f"{MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}"


# Things Kokoro says wrong (checked via its phonemes): "C#" lost its "#", "MyNotion" was "mi-NO-tion",
# "VS Code" was "viz code", "km" was "K M", "e.g." was "ee-gee".
PRONOUNCE = [
    (r"\bC#", "C sharp"), (r"\bF#", "F sharp"), (r"\bMyNotion\b", "My Notion"), (r"\bVS ?Code\b", "V S Code"),
    (r"\be\.g\.", "for example"), (r"\bi\.e\.", "that is"), (r"\bvs\.?(?=\s)", "versus"),
    (r"(\d)\s?°C\b", r"\1 degrees Celsius"), (r"(\d)\s?°F\b", r"\1 degrees Fahrenheit"), (r"(\d)\s?°", r"\1 degrees"),
    (r"(\d)\s?km/h\b", r"\1 kilometers per hour"), (r"(\d)\s?km\b", r"\1 kilometers"),
    (r"(\d)\s?kg\b", r"\1 kilos"), (r"(\d)\s?cm\b", r"\1 centimeters"), (r"(\d)\s?ml\b", r"\1 milliliters"),
    (r"(\d)\s?GB\b", r"\1 gigabytes"), (r"(\d)\s?MB\b", r"\1 megabytes"),
    (r"\b1\s?h\b", "1 hour"), (r"\b1\s?min\b", "1 minute"),
    (r"(\d)\s?h\b", r"\1 hours"), (r"(\d)\s?min\b", r"\1 minutes"),
    (r"€\s?(\d+(?:[.,]\d+)?)", r"\1 euros"), (r"(\d+(?:[.,]\d+)?)\s?€", r"\1 euros"),
]


# Chat shorthand she writes in her bubbles (and the model sometimes does): Kokoro spells it out letter by letter
# ("btw" was "B T W"). Said as the words it stands for; the bubble keeps the short form.
CHAT_WORDS = {
    "btw": "by the way", "tbh": "to be honest", "idk": "I don't know", "imo": "in my opinion", "ngl": "not gonna lie",
    "rn": "right now", "brb": "be right back", "omg": "oh my god", "pls": "please", "plz": "please", "thx": "thanks",
    "tmrw": "tomorrow", "lol": "haha", "w/o": "without", "w/": "with",
}
CHAT_RE = re.compile(r"(?<![\w/])(" + "|".join(re.escape(w) for w in CHAT_WORDS) + r")(?![\w/])", re.I)


def normalize_for_tts(text: str) -> str:
    text = CHAT_RE.sub(lambda m: CHAT_WORDS[m.group(1).lower()], text)
    for pattern, spoken in PRONOUNCE:
        text = re.sub(pattern, spoken, text)
    text = TIME_AMPM_RE.sub(_say_time_ampm, text)
    text = TIME24_RE.sub(_say_time24, text)
    text = DATE_ISO_RE.sub(_say_date, text)
    text = URL_RE.sub('', text)
    text = re.sub(r'\*laughs\*', 'haha', text, flags=re.I)
    text = re.sub(r'\*[^*\n]{1,40}\*', '', text)          # *smiles* style actions
    text = EMOJI_RE.sub('', text)
    text = re.sub(r'[*_`#>~|]+', '', text)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-•]\s+', '', text, flags=re.M)
    text = text.replace('&', ' and ').replace('→', ' ').replace('…', '...')
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


FIRST_CHUNK_MIN = 60     # a first sentence longer than this starts playing after its first clause


def first_chunks(sentence: str) -> list:
    """The first sentence, split after its first comma/dash when it's long: the voice is made on the CPU (~1 s for a
    long sentence), so speaking can start after the first clause while the rest is being made."""
    if len(sentence) <= FIRST_CHUNK_MIN:
        return [sentence]
    m = re.search(r"[,;:—–] ", sentence[15:])
    if not m or len(sentence) - (15 + m.end()) < 12:
        return [sentence]
    cut = 15 + m.end()
    return [sentence[:cut].strip(), sentence[cut:].strip()]


def split_first(piece) -> list:
    """The first piece of a reply, in two parts when it's long (first_chunks), said with the same feeling."""
    parts = first_chunks(piece.text)
    if len(parts) == 1:
        return [piece]
    head = VoiceStyle.Piece(parts[0], piece.style, piece.speed, piece.lift, piece.gain, piece.pause_before,
                            VoiceStyle.COMMA_PAUSE_S)
    tail = VoiceStyle.Piece(parts[1], piece.style, piece.speed, piece.lift, piece.gain, 0.0, piece.pause_after)
    return [head, tail]


def style_voices(pipeline, base, max_share=1.0) -> dict:
    """Her voice per emotion: her own voice with a little of another Kokoro voice mixed in (VoiceStyle.STYLES).
    Made once at start. A voice that can't be loaded leaves that emotion with her own voice."""
    if isinstance(base, str):
        base = pipeline.load_single_voice(base)
    out = {}
    for name, style in VoiceStyle.STYLES.items():
        if not style["accent"]:
            continue
        accent, share = style["accent"]
        share = min(share, max_share)
        try:
            out[name] = base * (1 - share) + pipeline.load_single_voice(accent) * share
        except Exception as e:
            print(f"[VoiceEngine] {name} voice without {accent}: {e}")
    return out


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z']+", (text or "").lower()) if len(w) > 1}


class VoiceEngine:
    def __init__(self, live2d_controller=None, stt_engine=None):
        self.controller = live2d_controller
        self.stt = stt_engine
        self.p = pyaudio.PyAudio()

        self._stop_interrupt_listener = False
        self._interrupted = False
        self._interrupted_text = None

        self.audio_queue = queue.Queue()
        self.is_playing = False

        self._kokoro = None
        self._tts = None
        self._style_voices = {}
        self._expressive_voices = {}
        self._claude_voice = None
        self._mouth = True               # her mouth moves with the sound (not while Claude talks)
        if TTS_ENGINE == "chatterbox":
            print("[VoiceEngine] Loading Chatterbox...")
            from chatterbox.tts import ChatterboxTTS
            self._tts = ChatterboxTTS.from_pretrained(device=CHATTERBOX_DEVICE)
            self._tts_sr = self._tts.sr
            print("[VoiceEngine] Chatterbox ready.")
        else:
            print(f"[VoiceEngine] Loading Kokoro ({KOKORO_VOICE} on {KOKORO_DEVICE})...")
            from kokoro import KPipeline
            self._kokoro = KPipeline(lang_code=KOKORO_VOICE.strip()[0], device=KOKORO_DEVICE, repo_id="hexgrad/Kokoro-82M")
            self._tts_sr = KOKORO_SR
            self._voice = blend_voice(self._kokoro, KOKORO_VOICE)
            self._style_voices = style_voices(self._kokoro, self._voice)
            self._expressive_voices = style_voices(self._kokoro, self._voice, max_share=0.22)
            list(self._kokoro("Ready.", voice=self._voice))  # warm-up, so the first real sentence is quick
            print("[VoiceEngine] Kokoro ready.")

        self.rvc_client = None
        if RVC_ENABLED:
            try:
                self.rvc_client = Client(RVC_API_URL, timeout=3)
                print("[VoiceEngine] Connected successfully to RVC Gradio Server!")
            except Exception as e:
                print(f"[VoiceEngine] Could not link to Gradio server: {e}. Using native voice.")

        self._current_mood = "neutral"
        self._exaggeration = MOOD_SETTINGS["neutral"]["exaggeration"]
        self._cfg = MOOD_SETTINGS["neutral"]["cfg"]
        self._pitch = MOOD_SETTINGS["neutral"]["pitch"]
        self._speed = MOOD_SETTINGS["neutral"]["speed"]

        self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.playback_thread.start()

    # ------------------------------------------------------------------ speak
    def speak(self, text: str, speaker: str = "aria") -> str | None:
        if not text or not normalize_for_tts(text):
            return None
        # split before cleaning: each sentence keeps its emojis until VoiceStyle has read its feeling from them
        return self.speak_sentences(re.split(r'(?<=[.!?\n])\s+', text), speaker=speaker)

    def _voice_for(self, speaker, style, profile=None):
        """(voice pack, base lift) for a sentence. Claude has one voice: the emotion's pace and pitch still apply,
        but her voice mixes (female voices) don't."""
        if speaker == "claude" and self._kokoro is not None:
            if self._claude_voice is None:
                try:
                    self._claude_voice = blend_voice(self._kokoro, CLAUDE_VOICE)
                except Exception as e:
                    print(f"[VoiceEngine] Claude's voice {CLAUDE_VOICE} didn't load: {e}")
                    self._claude_voice = self._voice
            return self._claude_voice, CLAUDE_LIFT
        voices = getattr(self, "_expressive_voices", self._style_voices) if profile == "expressive" else self._style_voices
        return voices.get(style) if self._kokoro else None, VOICE_LIFT

    def speak_sentences(self, sentences, speaker: str = "aria") -> str | None:
        """Speak sentences as they arrive. `sentences` can be a generator fed by the LLM stream:
        sentence 1 is synthesized and playing while later ones are still being written."""
        self._interrupted = False
        self._interrupted_text = None
        self._stop_interrupt_listener = False
        self._flush_audio_queue()
        self._spoken_words = set()       # what she's saying this time, to recognise her own voice (echo)
        self.first_audio_at = None       # when the first sentence started playing (speed log)

        interrupt_thread = threading.Thread(target=self._listen_for_interrupt, daemon=True)
        interrupt_thread.start()

        delivery = VoiceStyle.Delivery(self._current_mood, profile="natural" if speaker == "claude" else None)
        self._mouth = speaker != "claude"

        def pieces():
            first = True
            for raw in sentences:
                sentence = normalize_for_tts(raw or "").strip()
                if not sentence:
                    continue
                for piece in delivery.pieces(sentence, raw):
                    yield from (split_first(piece) if first else [piece])
                first = False

        for piece in pieces():
            if self._interrupted:
                break
            self._spoken_words.update(_words(piece.text))
            voice, base_lift = self._voice_for(speaker, piece.style, delivery.profile)
            audio_np, sr, mouth = self._synthesize_piece(piece, voice, base_lift)
            if audio_np is not None and not self._interrupted:
                trimmed = speech_span(audio_np, sr)[0] if mouth else 0
                audio_np = np.clip(polish_audio(audio_np, sr) * piece.gain, -1.0, 1.0)
                before = np.zeros(int(sr * piece.pause_before), dtype=np.float32)
                after = np.zeros(int(sr * piece.pause_after), dtype=np.float32)
                # her mouth's timeline, moved to where the speech now sits in what is played
                if mouth:
                    shift = len(before) / sr - trimmed / sr
                    mouth = LipSync.shift_timeline(mouth, shift)
                self.audio_queue.put((np.concatenate([before, audio_np, after]), sr, mouth))
                if self.first_audio_at is None:
                    self.first_audio_at = time.time()

        while self.audio_queue.unfinished_tasks and not self._interrupted:
            time.sleep(0.05)

        self._stop_interrupt_listener = True
        # if someone started talking just as she finished, let that recording end (10 s at most), so it
        # never runs at the same time as the next normal listen
        interrupt_thread.join(timeout=12.0)

        if self.controller:
            self.controller.stop_talking()

        return self._interrupted_text

    # ------------------------------------------------------------- synthesize
    def _synthesize_piece(self, piece, voice=None, base_lift=None):
        if piece.style != "laugh":
            return self._synthesize(piece.text, speed=piece.speed, voice=voice,
                                    lift_by=piece.lift, base_lift=base_lift)
        # A laugh is one short "Hah!" in her laughing voice. (Lala picked it by ear from six versions; a chuckle
        # spliced from copies of one vowel sounded creepy, and Kokoro reading "Ha ha!" sounded spelled out.) Its
        # vowel is marked as a laugh in her mouth's timeline, so her shoulders bounce on it (logic.mjs laughMotion).
        audio, sr, mouth = self._synthesize(LAUGH_WORD, speed=piece.speed, voice=voice,
                                            lift_by=piece.lift, base_lift=base_lift)
        if audio is None:
            return audio, sr, None
        mouth = [list(s[:5]) + ["laugh"] if s[2] else list(s) for s in mouth] if mouth else \
            [[0.0, round(len(audio) / sr, 3), "aa", 0.85, 0, "laugh"]]
        return audio, sr, mouth

    def _synthesize(self, text: str, speed: float = None, voice=None, lift_by: float = 0.0, base_lift: float = None
                    ) -> tuple[np.ndarray | None, int, list | None]:
        """The audio for `text`, its sample rate, and her mouth's timeline for it (Engines/LipSync.py; None
        when the engine doesn't say which sounds it made)."""
        try:
            if self._interrupted:
                return None, self._tts_sr, None

            if self._kokoro is not None:
                semitones = (VOICE_LIFT if base_lift is None else base_lift) + lift_by
                pace = (speed or self._speed) / lift_rate(semitones)
                results = [r for r in self._kokoro(text, voice=voice if voice is not None else self._voice, speed=pace)
                           if r.audio is not None]
                if not results:
                    return None, KOKORO_SR, None
                audio = lift(np.concatenate([r.audio.numpy() for r in results]).astype(np.float32), semitones)
                return audio, KOKORO_SR, self._mouth_timeline(results, semitones)

            wav = self._tts.generate(
                text,
                audio_prompt_path=AUDIO_PROMPT_PATH,
                exaggeration=self._exaggeration,
                cfg_weight=self._cfg,
            )
            raw_audio = wav.squeeze().cpu().numpy().astype(np.float32)
            # (no phonemes from this engine: her mouth follows the loudness alone)
            sr = self._tts_sr

            if self.rvc_client:
                tmp_in_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
                        tmp_in_path = tmp_in.name
                    sf.write(tmp_in_path, raw_audio, sr)

                    result = self.rvc_client.predict(
                        0,                  # speaker ID
                        tmp_in_path,        # source audio
                        self._pitch,        # transpose (mood-controlled)
                        None,               # f0 curve file
                        RVC_METHOD,
                        "",                 # feature index text override
                        RVC_INDEX_PATH,
                        RVC_INDEX_RATE,     # index ratio
                        3,                  # median filter radius
                        0,                  # resample
                        0.25,               # volume envelope
                        0.33,               # protect
                        api_name="/infer_convert",
                    )

                    if result and isinstance(result, (list, tuple)):
                        converted_path = next(
                            (i for i in result if isinstance(i, str) and i.endswith(".wav")), None)
                        if converted_path and os.path.exists(converted_path):
                            converted_audio, new_sr = sf.read(converted_path, dtype="float32")
                            return converted_audio, new_sr, None
                except Exception as api_err:
                    print(f"[VoiceEngine] RVC conversion failed, using raw voice: {api_err}")
                finally:
                    if tmp_in_path and os.path.exists(tmp_in_path):
                        os.unlink(tmp_in_path)

            return raw_audio, sr, None
        except Exception as e:
            print(f"[VoiceEngine] Synthesis failure: {e}")
            return None, self._tts_sr, None

    @staticmethod
    def _mouth_timeline(results, semitones):
        """Her mouth through Kokoro's results (phonemes and their durations), or None if they don't say."""
        try:
            chunks = [(r.phonemes, r.pred_dur.tolist()) for r in results]
            if any(not p or d is None for p, d in chunks):
                return None
            return LipSync.timeline(chunks, rate=lift_rate(semitones) if semitones else 1.0)
        except Exception as e:                      # never lose her voice over her mouth
            print(f"[VoiceEngine] No mouth timeline: {e}")
            return None

    # --------------------------------------------------------------- playback
    def _playback_worker(self):
        stream = None
        current_sr = self._tts_sr

        while True:
            try:
                audio_np, sr, *rest = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                self.is_playing = False
                time.sleep(0.02)
                continue

            try:
                self.is_playing = True

                if stream is None or sr != current_sr:
                    if stream:
                        stream.stop_stream()
                        stream.close()
                    current_sr = sr
                    stream = self.p.open(
                        format=pyaudio.paFloat32,
                        channels=1,
                        rate=current_sr,
                        output=True,
                        frames_per_buffer=256,
                    )

                # her mouth plays this piece's timeline on its own clock, from now
                if rest and rest[0] and self.controller and self._mouth and hasattr(self.controller, "speech"):
                    self.controller.speech(rest[0])
                chunk_size = 256
                for i in range(0, len(audio_np), chunk_size):
                    if self._interrupted:
                        break
                    chunk = audio_np[i: i + chunk_size]
                    if self.controller and self._mouth:
                        self.controller.feed_audio(chunk)
                    elif self.controller and hasattr(self.controller, "feed_claude_audio"):
                        self.controller.feed_claude_audio(chunk)      # his figure's mouth
                    stream.write(chunk.tobytes())
            except Exception as e:
                print(f"[VoiceEngine] Playback error: {e}")
            finally:
                self.audio_queue.task_done()

    # -------------------------------------------------------------- interrupt
    def _listen_for_interrupt(self):
        if not self.stt:
            return
        try:
            time.sleep(0.3)
            while not self._interrupted and not self._stop_interrupt_listener:
                heard = self.stt.listen_short(timeout=0.5, stop=lambda: self._stop_interrupt_listener)
                if not heard:
                    continue

                text, level = heard if isinstance(heard, tuple) else (heard, None)
                cleaned = text.strip().lower()
                confidence = getattr(self.stt, "last_confidence", 1.0)
                if confidence < INTERRUPT_MIN_CONFIDENCE:
                    print(f"[VoiceEngine] Shielded (unsure, {confidence:.2f}): '{cleaned}'")
                    continue
                if self._is_echo(cleaned):
                    print(f"[VoiceEngine] Shielded (her own voice): '{cleaned}'")
                    continue

                if not self._is_real_interrupt(cleaned, level):
                    continue

                print(f"[VoiceEngine] Intent Verified: User interrupted with '{cleaned}'")
                self._interrupted_text = cleaned
                self._interrupted = True
                self._flush_audio_queue()
                break
        except Exception as e:
            print(f"[VoiceEngine] Interrupt monitoring error: {e}")

    def _is_echo(self, cleaned: str) -> bool:
        words = _words(cleaned)
        mine = getattr(self, "_spoken_words", set())
        return bool(words) and len(words & mine) / len(words) >= ECHO_OVERLAP

    def _is_real_interrupt(self, cleaned, level=None):
        words = [w.strip(string.punctuation) for w in cleaned.split()]
        words = [w for w in words if w]
        if not words:
            return False

        if level is not None and level < MIN_INTERRUPT_RMS:
            print(f"[VoiceEngine] Shielded (too quiet/far): '{cleaned}' ({level:.0f})")
            return False

        if all(w in NOISE_FILLERS for w in words):
            return False

        if any(w in AI_NAMES for w in words):
            return True

        trimmed = list(words)
        while trimmed and trimmed[0] in NOISE_FILLERS:
            trimmed.pop(0)
        lead = " ".join(trimmed[:3])

        if any(lead.startswith(hook) for hook in LEAD_HOOKS):
            return True

        print(f"[VoiceEngine] Shielded: background chatter -> '{cleaned}'")
        return False

    def _flush_audio_queue(self):
        while True:
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.task_done()
            except queue.Empty:
                break

    # ------------------------------------------------------------------- misc
    def set_mood(self, mood: str):
        self._current_mood = mood
        s = MOOD_SETTINGS.get(mood, MOOD_SETTINGS["neutral"])
        self._exaggeration = s["exaggeration"]
        self._cfg = s["cfg"]
        self._pitch = s["pitch"]
        self._speed = s["speed"]

    def close(self):
        self.p.terminate()
