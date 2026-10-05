import pyaudio
import numpy as np
from openwakeword.model import Model


class WakeWordDetector:
    def __init__(self, wake_word="hey_aria", threshold=0.7):
        # openwakeword has built-in models, closest to "hey aria" is "hey_jarvis"
        # or use a custom one — we'll use alexa as placeholder until custom trained
        self.model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        self.threshold = threshold
        self.p = pyaudio.PyAudio()
        self.chunk_size = 1280
        self.sample_rate = 16000

    def listen_for_wake_word(self, cooldown=3.0):
        """Blocks until wake word detected, explicitly discarding noise during cooldown."""
        import time
        print("[Wake] Sleeping... say the wake word to activate.")

        # 1. Open the stream immediately so we can actively capture and drop audio
        self.model.reset()
        stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size
        )

        # 2. Actively drain the mic buffer for the duration of the cooldown period
        print(f"[Wake] Flushing ambient noise for {cooldown} seconds...")
        start_cooldown = time.time()
        try:
            while time.time() - start_cooldown < cooldown:
                # Read chunks and throw them away to keep the stream fresh
                stream.read(self.chunk_size, exception_on_overflow=False)
        except Exception as e:
            print(f"[Wake] Cooldown flush encountered a minor error (ignored): {e}")

        # 3. Now enter the real listening loop with a totally clean slate
        print("[Wake] Ready and listening for wake word.")
        try:
            while True:
                audio = stream.read(self.chunk_size, exception_on_overflow=False)
                audio_np = np.frombuffer(audio, dtype=np.int16)
                predictions = self.model.predict(audio_np)

                for model_name, score in predictions.items():
                    if score > self.threshold:
                        print(f"[Wake] Wake word detected! ({score:.2f})")
                        self.model.reset()  # clear post-detection state
                        return
        finally:
            stream.stop_stream()
            stream.close()

    def close(self):
        self.p.terminate()