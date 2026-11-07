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

# --- WHICH TTS ---
# kokoro (default): small and smooth, runs on the CPU so the whole GPU stays free for the LLM.
# chatterbox: clones Engines/ref_voice.wav, but takes ~4 GB of VRAM and pushes the LLM onto the CPU.
TTS_ENGINE = os.environ.get("TTS_ENGINE", "kokoro").lower()
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")
KOKORO_DEVICE = os.environ.get("KOKORO_DEVICE", "cpu")
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
PEAK_LIMIT = 0.6           # soft ceiling, so plosives and laughs never spike
SENTENCE_PAUSE_S = 0.35    # breathing room between sentences (was 0.15)

# Tone per sentence of Aria's reply (Kokoro has no emotion control, so: pace, loudness and pauses).
# Comforting sentences come slower and softer; playful ones a little quicker and brighter.
SOFT_RE = re.compile(r"\b(sorry|aw+|oh no|that sounds (?:rough|hard|tough|awful|annoying|frustrating|unfair)|"
                     r"i'?m here for you|take (?:it easy|care|a break|your time)|it'?s (?:okay|ok|alright)|"
                     r"you'?ll be (?:fine|okay)|get some rest|breathe|i'?m proud|that must)\b", re.I)
PLAYFUL_RE = re.compile(r"\b(haha+|hehe|lol|wow|yay|nice|awesome|rude|amazing|let'?s go|woo+|ooh)\b", re.I)
TONES = {
    "soft":    {"speed": 0.92, "gain": 0.85, "pause": 0.15},
    "playful": {"speed": 1.06, "gain": 1.05, "pause": -0.1},
    "neutral": {"speed": 1.0,  "gain": 1.0,  "pause": 0.0},
}


def sentence_tone(sentence: str) -> str:
    if SOFT_RE.search(sentence):
        return "soft"
    if PLAYFUL_RE.search(sentence) or sentence.rstrip().endswith("!"):
        return "playful"
    return "neutral"
COMMA_PAUSE_S = 0.12


def polish_audio(audio: np.ndarray, sr: int) -> np.ndarray:
    """Make TTS output easier on the ears: trim, de-rumble, soften harsh highs,
    tame sibilance, level the volume, soft-limit peaks, and fade the edges (no clicks)."""
    if audio is None or len(audio) < sr // 20:
        return audio
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio - float(np.mean(audio))

    # trim silence / breath noise at the ends (keeps 40 ms of air)
    env = np.abs(audio)
    thresh = max(0.01, 0.05 * float(np.max(env)))
    idx = np.where(env > thresh)[0]
    if len(idx):
        pad = int(0.04 * sr)
        audio = audio[max(0, idx[0] - pad): min(len(audio), idx[-1] + pad)]

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


def normalize_for_tts(text: str) -> str:
    for pattern, spoken in PRONOUNCE:
        text = re.sub(pattern, spoken, text)
    text = TIME_AMPM_RE.sub(_say_time_ampm, text)
    text = TIME24_RE.sub(_say_time24, text)
    text = DATE_ISO_RE.sub(_say_date, text)
    text = URL_RE.sub('', text)
    text = re.sub(r'\*[^*\n]{1,40}\*', '', text)          # *smiles* style actions
    text = EMOJI_RE.sub('', text)
    text = re.sub(r'[*_`#>~|]+', '', text)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-•]\s+', '', text, flags=re.M)
    text = text.replace('&', ' and ').replace('→', ' ').replace('…', '...')
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


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
        if TTS_ENGINE == "chatterbox":
            print("[VoiceEngine] Loading Chatterbox...")
            from chatterbox.tts import ChatterboxTTS
            self._tts = ChatterboxTTS.from_pretrained(device=CHATTERBOX_DEVICE)
            self._tts_sr = self._tts.sr
            print("[VoiceEngine] Chatterbox ready.")
        else:
            print(f"[VoiceEngine] Loading Kokoro ({KOKORO_VOICE} on {KOKORO_DEVICE})...")
            from kokoro import KPipeline
            self._kokoro = KPipeline(lang_code=KOKORO_VOICE[0], device=KOKORO_DEVICE, repo_id="hexgrad/Kokoro-82M")
            self._tts_sr = KOKORO_SR
            list(self._kokoro("Ready.", voice=KOKORO_VOICE))  # warm-up, so the first real sentence is quick
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
    def speak(self, text: str) -> str | None:
        if not text:
            return None
        text = normalize_for_tts(text)
        if not text:
            return None
        return self.speak_sentences(re.split(r'(?<=[.!?\n])\s+', text))

    def speak_sentences(self, sentences) -> str | None:
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

        for sentence in sentences:
            if self._interrupted:
                break
            sentence = normalize_for_tts(sentence or "").strip()
            if not sentence:
                continue
            self._spoken_words.update(_words(sentence))
            tone = TONES[sentence_tone(sentence)]
            audio_np, sr = self._synthesize(sentence, speed=self._speed * tone["speed"])
            if audio_np is not None and not self._interrupted:
                audio_np = np.clip(polish_audio(audio_np, sr) * tone["gain"], -1.0, 1.0)
                pause = SENTENCE_PAUSE_S if sentence[-1:] in ".!?" else COMMA_PAUSE_S
                pause = max(0.12, pause + tone["pause"])
                silence = np.zeros(int(sr * pause), dtype=np.float32)
                self.audio_queue.put((np.concatenate([audio_np, silence]), sr))
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
    def _synthesize(self, text: str, speed: float = None) -> tuple[np.ndarray | None, int]:
        try:
            if self._interrupted:
                return None, self._tts_sr

            if self._kokoro is not None:
                chunks = [r.audio.numpy() for r in self._kokoro(text, voice=KOKORO_VOICE, speed=speed or self._speed)
                          if r.audio is not None]
                if not chunks:
                    return None, KOKORO_SR
                return np.concatenate(chunks).astype(np.float32), KOKORO_SR

            wav = self._tts.generate(
                text,
                audio_prompt_path=AUDIO_PROMPT_PATH,
                exaggeration=self._exaggeration,
                cfg_weight=self._cfg,
            )
            raw_audio = wav.squeeze().cpu().numpy().astype(np.float32)
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
                            return converted_audio, new_sr
                except Exception as api_err:
                    print(f"[VoiceEngine] RVC conversion failed, using raw voice: {api_err}")
                finally:
                    if tmp_in_path and os.path.exists(tmp_in_path):
                        os.unlink(tmp_in_path)

            return raw_audio, sr
        except Exception as e:
            print(f"[VoiceEngine] Synthesis failure: {e}")
            return None, self._tts_sr

    # --------------------------------------------------------------- playback
    def _playback_worker(self):
        stream = None
        current_sr = self._tts_sr

        while True:
            try:
                audio_np, sr = self.audio_queue.get(timeout=0.1)
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

                chunk_size = 256
                for i in range(0, len(audio_np), chunk_size):
                    if self._interrupted:
                        break
                    chunk = audio_np[i: i + chunk_size]
                    if self.controller:
                        self.controller.feed_audio(chunk)
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