import sys
import threading
import time
import re

from ContextBuilder import ContextBuilder
from Controller.homeController import HomeAssistantController
from Engines.Emotionengine import EmotionEngine
from Controller.Spotify_controll import SpotifyEngine
from Engines.Tool_Engine import ToolEngine
from Controller.arduino_controller import ArduinoLEDController
from Engines.UserStateEngine import UserStateEngine
from Engines.voice_engine import VoiceEngine
from database import AriaMemory
from llm_engine import LLMEngine
from speech_to_text import STTEngine
from vision.setupface import add_face
from vision.tray import AriaTray
from vision.vision import AriaVision
from wakeworddetector import WakeWordDetector

# ── Live2D ────────────────────────────────────────────────────────────────────


BASE_PROMPT = """You are Aria, Lala's personal desk AI assistant. You are efficient, intelligent, and direct.
You have a dry wit and speak like a competent person, not a customer service bot.
You get things done — you answer questions, control devices, play music, search the web, and control the TV.
Keep responses short and to the point — one or two sentences unless more is needed.
If you don't know something, say so and offer to search for it.
You have a camera — when asked what you see or who is there, always use the look tool.
When asked anything about the TV (on, off, volume), always use the TV tools. Never say you can't do it.
You can also check Lala's phone battery/location and send notifications to it via Home Assistant."""

SLEEP_PHRASES = ["go to sleep", "sleep", "goodbye", "see you later", "that's all", "shut up"]
SHUTDOWN_PHRASES = ["exit", "quit", "shutdown"]
SLEEP_TIMEOUT = 30


class Aria:
    def __init__(self):
        self.memory = AriaMemory()
        self.context = ContextBuilder(self.memory)
        self.llm = LLMEngine(model="qwen3:8b")
        self.stt = STTEngine()
        self.emotions = EmotionEngine()
        self.wake = WakeWordDetector()
        self.is_user_known = False

        self._vision_triggered = threading.Event()
        self._vision_user = [None]
        self._vision_cooldown = [False]
        self._unknown_in_progress = False

        # Audio lock to prevent background threads and main thread from fighting over mic input

        self.vision = AriaVision(
            on_known_user=self._on_known_user,
            on_unknown_user=self._on_unknown_user,
            on_user_gone=self._on_user_gone,
            memory=self.memory,
        )
        self.vision.start()

        self.state_engine = UserStateEngine(vision=self.vision, llm_model="qwen2.5:7b")

        self.tray = AriaTray(
            on_show=lambda: print("[Tray] Show clicked"),
            on_quit=self.shutdown,
        )
        self.tray.start()

        try:
            self.ha = HomeAssistantController()
        except Exception as e:
            print(f"Warning: Home Assistant unavailable: {e}")
            self.ha = None

        try:
            self.spotify = SpotifyEngine(client_id="xx", client_secret="xx")
        except Exception as e:
            print(f"Warning: Spotify unavailable: {e}")
            self.spotify = None

        try:
            self.arduino = ArduinoLEDController()
        except Exception as e:
            print(f"Warning: Arduino unavailable: {e}")
            self.arduino = None

        try:
            self.voice = VoiceEngine(stt_engine=self.stt)
        except Exception as e:
            print(f"Warning: Voice unavailable: {e}")
            self.voice = None

        self.tools = ToolEngine(
            spotify=self.spotify,
            arduino=self.arduino,
            vision=self.vision,
            ha=self.ha,
        )

        self.session_id = self.memory.start_session()
        self.session_msgs = 0

    # ── Vision callbacks ──────────────────────────────────────────────────────

    def _on_known_user(self, name: str):
        if self._vision_cooldown[0]:
            return
        print(f"[Vision] Known user: {name}")
        self.memory.save_memory(f"User's name is {name}")
        self._vision_user[0] = [name]
        self._vision_triggered.set()
        self.is_user_known = True

    def _on_unknown_user(self):
        if self._vision_cooldown[0]:
            return
        if self._unknown_in_progress:
            return

        print("[Vision] Unknown person detected")
        self._vision_user[0] = None
        self.is_user_known = False
        self._unknown_in_progress = True

        threading.Thread(target=self._handle_unknown_person, daemon=True).start()

    def _handle_unknown_person(self):
        # Acquire mic lock so main wake loops pause tracking until complete

        try:
            self.speak("I don't think we've met. What's your name?")
            user_input = self.stt.listen()

            if not user_input:
                self.speak("Didn't catch that, never mind.")
                return

            name = self.llm.chat(
                f"Extract only the person's name from this sentence, respond with just the name and nothing else: '{user_input}'",
                [], BASE_PROMPT
            ).strip()

            if not name or len(name) > 30:
                self.speak("Sorry, I didn't get a clear name. We can try again later.")
                return

            self.speak(f"Nice to meet you, {name}. Give me a moment to remember your face.")
            self.vision.learn_face(name, samples=40)
            self.is_user_known = True
            self._vision_user[0] = [name]
            self.speak(f"Got it, {name}. I'll remember you next time.")

        except Exception as e:
            print(f"[Vision] Unknown person handling failed: {e}")
        finally:
            self._unknown_in_progress = False

    def _on_user_gone(self):
        print("[Vision] User left")
        self._vision_triggered.clear()
        self._vision_cooldown[0] = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def speak(self, text: str):
        if not text or not self.voice:
            return None
        if self.arduino:
            self.arduino.send_command()
        interrupted_text = self.voice.speak(text)
        if self.arduino:
            self.arduino.stop_talking()
        return interrupted_text

    def process_text_input(self, user_input: str) -> str:
        if not user_input:
            return "Ich habe nichts empfangen."

        if user_input.lower().startswith("say "):
            text_to_say = user_input[4:].strip()

            return f" Lawand is saying {text_to_say}"

        self.emotions.process(user_input)
        self.memory.log_mood(self.emotions.get_mood_label())
        if self.voice:
            self.voice.set_mood(self.emotions.get_mood_label())

        tool_result = self.tools.handle(user_input, self.llm.model)
        history = self.memory.load_history(limit=10)
        system_prompt = self.context.build_system_prompt(BASE_PROMPT)

        if tool_result:
            response = self.llm.chat(
                f"{user_input}\n[Action result: {tool_result}]",
                history, system_prompt
            )
        else:
            response = self.llm.chat(user_input, history, system_prompt)

        self.memory.save_message("user", user_input)
        self.memory.save_message("assistant", response)
        self.session_msgs += 2

        return response

    def shutdown(self):
        print("\nShutting down...")
        self.memory.end_session(self.session_id, self.session_msgs)
        self.vision.stop()
        self.tray.stop()
        if self.arduino: self.arduino.shutdown(); self.arduino.close()
        if self.voice: self.voice.close()
        self.wake.close()
        sys.exit(0)

    # ── Main loop ────────────────────────────────────────────────────────────

    def run(self):
        try:
            while True:

                self._vision_triggered.clear()
                wake_thread = threading.Thread(target=self.wake.listen_for_wake_word, daemon=True)
                wake_thread.start()

                while wake_thread.is_alive() and not self._vision_triggered.is_set():
                    time.sleep(0.1)

                if self._vision_triggered.is_set():
                    self.wake.muted = True
                    time.sleep(0.5)
                    self.wake.muted = False

                    if self.arduino:
                        self.arduino.startup_animation()

                    opening = self.llm.chat(
                        self.context.greeting_prompt(known_user=self._vision_user[0]),
                        [], BASE_PROMPT
                    )
                    self.speak(opening)

                    last_interaction = time.time()
                    pending_input = None  # Cache slot for preserving interruptions

                    # ── Conversation loop ──────────────────────────────────────────
                    while True:
                        if time.time() - last_interaction > SLEEP_TIMEOUT:
                            print("[Wake] Going back to sleep.")
                            self.speak("Going to sleep.")
                            if self.arduino: self.arduino.sleep_mode()
                            break

                        # Fix: If an interruption happened, read the cached string instead of calling listen()
                        if pending_input:
                            user_input = pending_input
                            pending_input = None
                        else:
                            user_input = self.stt.listen()

                        if not user_input:
                            continue

                        print(f"You: {user_input}")

                        if any(p in user_input.lower() for p in SLEEP_PHRASES):
                            self.speak("Alright, going to sleep.")
                            if self.arduino: self.arduino.sleep_mode()
                            self._vision_cooldown[0] = True
                            break

                        if any(p in user_input.lower() for p in SHUTDOWN_PHRASES):
                            self.speak("Shutting down.")
                            self.shutdown()
                            return

                        last_interaction = time.time()

                        self.emotions.process(user_input)
                        self.memory.log_mood(self.emotions.get_mood_label())
                        if self.voice:
                            self.voice.set_mood(self.emotions.get_mood_label())

                        state_result = self.state_engine.check(user_input)
                        tool_result = self.tools.handle(user_input, self.llm.model)
                        history = self.memory.load_history(limit=10)
                        system_prompt = self.context.build_system_prompt(BASE_PROMPT)

                        if tool_result and any(x in tool_result.lower() for x in ["playing", "playlist"]):
                            response = self.llm.chat(
                                f"{user_input}\n[Action result: {tool_result}. Confirm in one short sentence.]",
                                history, system_prompt
                            )
                            print(f"Aria: {response}")
                            self.memory.save_message("user", user_input)
                            self.memory.save_message("assistant", response)
                            self.session_msgs += 2

                            interrupted = self.speak(response)
                            if self.arduino: self.arduino.sleep_mode()
                            if interrupted:
                                pending_input = interrupted  # Cache the interruption phrase
                                last_interaction = time.time()
                                continue
                            break
                        else:
                            if tool_result:
                                response = self.llm.chat(
                                    f"{user_input}\n[Action result: {tool_result}]",
                                    history, system_prompt
                                )
                            elif state_result.should_ask:
                                response = self.llm.chat(
                                    f"{user_input}\n[Note: the user seems {state_result.reason}. "
                                    f"After answering normally, naturally and briefly ask something like: "
                                    f"\"{state_result.suggested_question}\" — keep it casual.]",
                                    history, system_prompt
                                )
                            else:
                                response = self.llm.chat(user_input, history, system_prompt)

                            print(f"Aria: {response}")
                            self.memory.save_message("user", user_input)
                            self.memory.save_message("assistant", response)
                            self.session_msgs += 2

                            interrupted = self.speak(response)
                            if interrupted:
                                print(f"You (interrupted): {interrupted}")
                                pending_input = interrupted  # Cache the interruption phrase
                                last_interaction = time.time()
                                continue

        except KeyboardInterrupt:
            print("\nExiting...")
        finally:
            self.memory.end_session(self.session_id, self.session_msgs)
            self.vision.stop()
            self.tray.stop()
            if self.arduino: self.arduino.off(); self.arduino.close()
            if self.voice: self.voice.close()
            self.wake.close()


if __name__ == "__main__":
    aria = Aria()
    aria.run()
