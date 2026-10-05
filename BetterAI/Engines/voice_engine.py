import re
import os
import queue
import threading
import time
import tempfile
import numpy as np
import pyaudio
import soundfile as sf
from gradio_client import Client

KOKORO_VOICE = "af_bella"
KOKORO_SPEED = 1.0

# --- RVC GRADIO CLIENT APP CONFIG ---
RVC_API_URL = "http://127.0.0.1:7865/"
RVC_INDEX_PATH = r"C:\RVC\RVC1006Nvidia\assets\weights\added_IVF2182_Flat_nprobe_1_egirl.index"
RVC_PITCH = 0
RVC_METHOD = "rmvpe"
RVC_ENABLED = True
import string  # stdlib, skip if already imported

MIN_INTERRUPT_RMS = 500  # tune against your mic - print raw levels for a bit to calibrate

NOISE_FILLERS = {
    "uh", "um", "mm", "hmm", "ah", "oh", "hm", "mhm",
    "cough", "throat", "laughter", "noise",
}

AI_NAMES = {"aria"}

# Only counts when the utterance OPENS with one of these
LEAD_HOOKS = (
    "stop", "wait", "hold on", "hang on", "actually",
    "no", "shut up", "listen", "sorry", "excuse me", "please",
)

MOOD_SETTINGS = {
    "neutral": {"speed": 1.0, "pitch": 0},
    "happy": {"speed": 1.1, "pitch": 2},
    "sad": {"speed": 0.9, "pitch": -2},
    "angry": {"speed": 1.15, "pitch": 0},
    "excited": {"speed": 1.2, "pitch": 3},
}


class VoiceEngine:
    def __init__(self, live2d_controller=None, stt_engine=None):
        self.controller = live2d_controller
        self.stt = stt_engine
        self.p = pyaudio.PyAudio()
        self._stop_interrupt_listener = False

        self.sample_rate = 24000
        self._interrupted = False
        self._interrupted_text = None

        self.audio_queue = queue.Queue()
        self.is_playing = False

        print("[VoiceEngine] Loading Kokoro...")
        from kokoro import KPipeline
        self._kokoro = KPipeline(lang_code='a')
        print("[VoiceEngine] Kokoro ready.")

        # Establish connection directly to the live Gradio server instance
        self.rvc_client = None
        if RVC_ENABLED:
            try:
                self.rvc_client = Client(RVC_API_URL, timeout=3)
                print("[VoiceEngine] Connected successfully to RVC Gradio Server!")
            except Exception as e:
                print(f"[VoiceEngine] Could not link to Gradio server: {e}. Using native voice.")

        self._speed = KOKORO_SPEED
        self._current_mood = "neutral"

        # Audio rendering worker thread
        self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.playback_thread.start()

    def speak(self, text: str) -> str | None:
        if not text:
            return None

        self._interrupted = False
        self._interrupted_text = None
        self._stop_interrupt_listener = False  # add this flag

        # flush queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        interrupt_thread = threading.Thread(target=self._listen_for_interrupt, daemon=True)
        interrupt_thread.start()

        sentences = re.split(r'(?<=[.!?,\n])\s+', text.strip())
        for sentence in sentences:
            if self._interrupted:
                break
            sentence = sentence.strip()
            if not sentence:
                continue
            audio_np, sr = self._synthesize(sentence)
            if audio_np is not None:
                silence = np.zeros(int(sr * 0.15), dtype=np.float32)
                self.audio_queue.put((np.concatenate([audio_np, silence]), sr))

        while self.is_playing and not self._interrupted:
            time.sleep(0.05)

        self._stop_interrupt_listener = True  # kill the listener thread
        interrupt_thread.join(timeout=1.0)  # wait for it to actually stop

        if self.controller:
            self.controller.stop_talking()

        return self._interrupted_text

    def _synthesize(self, text: str) -> tuple[np.ndarray | None, int]:
        try:
            chunks = []
            for _, _, audio in self._kokoro(text, voice=KOKORO_VOICE, speed=self._speed, split_pattern=None):
                if self._interrupted:
                    return None, 24000
                if audio is not None:
                    chunks.append(audio)

            if not chunks:
                return None, 24000

            raw_audio = np.concatenate(chunks).astype(np.float32)

            # --- Ultra-Fast Gradio API Conversion Execution ---
            if self.rvc_client:
                try:
                    # Write the raw float frames to a lightning-fast temporary file structure
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
                        sf.write(tmp_in.name, raw_audio, 24000)
                        tmp_in_path = tmp_in.name

                    # Hit the exact internal Gradio inference layout directly in memory
                    result = self.rvc_client.predict(
                        0,  # Speaker ID
                        tmp_in_path,  # Source audio path
                        RVC_PITCH,  # Transpose/Pitch modification
                        None,  # F0 curve override file
                        RVC_METHOD,  # Pitch extraction (e.g. rmvpe)
                        "",  # Feature index text override
                        RVC_INDEX_PATH,  # Explicit structural Index file path
                        0.75,  # Search feature index ratio
                        3,  # Median filtering radius
                        0,  # Resample post-processing configuration
                        0.25,  # Volume envelope alignment scaling
                        0.33,  # Consonant protection ratio
                        api_name="/infer_convert"
                    )

                    # Clean up the input file asset right away
                    if os.path.exists(tmp_in_path):
                        os.unlink(tmp_in_path)

                    # Extract converted file out of the Gradio pipeline output wrapper
                    if result and isinstance(result, (list, tuple)):
                        # Gradio commonly returns a success note string and output path tuple
                        converted_path = next(
                            (item for item in result if isinstance(item, str) and item.endswith(".wav")), None)
                        if converted_path and os.path.exists(converted_path):
                            converted_audio, new_sr = sf.read(converted_path, dtype='float32')
                            return converted_audio, new_sr

                except Exception as api_err:
                    print(f"[VoiceEngine] Gradio Engine Pipeline conversion fallback notice: {api_err}")

            return raw_audio, 24000
        except Exception as e:
            print(f"[VoiceEngine] General synthesis array block failure: {e}")
            return None, 24000

    def _playback_worker(self):
        """Monitors system queue arrays and pushes them to hardware channels instantly."""
        stream = None
        current_sr = 24000

        while True:
            try:
                audio_np, sr = self.audio_queue.get(timeout=0.1)
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
                        frames_per_buffer=256
                    )

                chunk_size = 256
                for i in range(0, len(audio_np), chunk_size):
                    if self._interrupted:
                        break
                    chunk = audio_np[i: i + chunk_size]
                    if self.controller:
                        self.controller.feed_audio(chunk)
                    stream.write(chunk.tobytes())

                self.audio_queue.task_done()
            except queue.Empty:
                self.is_playing = False
                time.sleep(0.02)

    def _listen_for_interrupt(self):
        if not self.stt:
            return
        try:
            time.sleep(0.3)  # let Aria actually start talking before listening for interrupts
            while not self._interrupted and not self._stop_interrupt_listener:
                heard = self.stt.listen_short(timeout=0.2)
                if not heard:
                    continue

                # listen_short can keep returning plain text like today, or
                # (text, rms) once you wire up amplitude reporting - see below
                text, level = heard if isinstance(heard, tuple) else (heard, None)
                cleaned = text.strip().lower()

                if not self._is_real_interrupt(cleaned, level):
                    continue

                print(f"[VoiceEngine] Intent Verified: User interrupted with '{cleaned}'")
                self._interrupted_text = cleaned
                self._interrupted = True
                self._flush_audio_queue()
                break

        except Exception as e:
            print(f"[VoiceEngine] Interrupt monitoring error: {e}")

    def _is_real_interrupt(self, cleaned, level=None):
        words = [w.strip(string.punctuation) for w in cleaned.split()]
        words = [w for w in words if w]
        if not words:
            return False

        # --- LAYER 1: VOLUME GATE (near-field vs. background) -----------
        if level is not None and level < MIN_INTERRUPT_RMS:
            print(f"[VoiceEngine] Shielded (too quiet/far): '{cleaned}' ({level:.0f})")
            return False

        # --- LAYER 2: PHYSICAL NOISE FILTER ------------------------------
        if all(w in NOISE_FILLERS for w in words):
            return False

        # --- LAYER 3: IS THIS ACTUALLY AIMED AT ARIA? --------------------
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
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break



    def set_mood(self, mood: str):
        self._current_mood = mood
        settings = MOOD_SETTINGS.get(mood, MOOD_SETTINGS["neutral"])
        self._speed = settings["speed"]
        self._pitch = settings["pitch"]

    def close(self):
        self.p.terminate()