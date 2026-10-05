import re
import threading
import time

from redis.commands.search import result

from database import AssistantMemory


class ProactiveEngine:
    def __init__(self, voice, get_response_fn):
        self.voice = voice
        self.get_response = get_response_fn
        self.last_interaction = time.time()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def poke(self):
        self.last_interaction = time.time()

    def _loop(self):
        memory = AssistantMemory()
        history = memory.get_recent_history(limit=50)
        while self.running:
            idle_seconds = time.time() - self.last_interaction
            if idle_seconds > 120:  # 2 min idle
                prompt = "The user hasn't said anything in a while. Say something short to check in."
                msg = self.get_response(prompt,history)
                oki = re.sub(r'\*.*?\*', '', msg)
                self.voice.speak(oki)
                self.last_interaction = time.time()  # reset so it doesn't spam
            time.sleep(10)

    def stop(self):
        self.running = False