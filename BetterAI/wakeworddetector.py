import time
import pyaudio
import numpy as np
from openwakeword.model import Model
from openwakeword.utils import download_models


class WakeWordDetector:
    def __init__(self, threshold=0.7):
        download_models()  # once at init, not at import time
        # "hey_jarvis" is the closest built-in model until a custom "hey aria" is trained
        self.model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.threshold = threshold
        self.p = pyaudio.PyAudio()
        self.chunk_size = 1280      # 80 ms at 16 kHz
        self.sample_rate = 16000

    def listen_for_wake_word(self, stop_event=None, cooldown=3.0) -> bool:
        """Blocks until the wake word is heard (True) or stop_event is set (False)."""
        print("[Wake] Sleeping... say the wake word to activate.")
        self.model.reset()
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
                predictions = self.model.predict(np.frombuffer(audio, dtype=np.int16))
                for score in predictions.values():
                    if score > self.threshold:
                        print(f"[Wake] Wake word detected! ({score:.2f})")
                        self.model.reset()
                        return True
            return False
        finally:
            stream.stop_stream()
            stream.close()

    def close(self):
        self.p.terminate()