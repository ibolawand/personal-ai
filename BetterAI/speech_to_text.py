import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

class STTEngine:
    def __init__(self, model_size="medium", device="cpu", compute_type="int8"):
        print("[STT] Loading Whisper model...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.sample_rate = 16000
        self.silence_threshold = 0.01
        self.silence_duration = 2.0  # seconds of silence before stopping
        self.max_duration = 30.0     # max recording time
        self.on_level = None         # optional fn(volume: float) for UI meters

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

    def listen(self, start_timeout=None):
        audio = self._record(start_timeout)
        if audio is None:
            return None
        print("[STT] Transcribing...")
        segments, _ = self.model.transcribe(audio, language="en")
        text = " ".join(s.text for s in segments).strip()
        print(f"[STT] Heard: {text}")
        return text

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