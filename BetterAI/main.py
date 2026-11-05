import argparse
import os
import queue
import random
import re
from collections import deque
import select
import sys
import threading
import time
import datetime
from pathlib import Path

from dotenv import load_dotenv

from ContextBuilder import ContextBuilder
from Controller.arduino_controller import ArduinoLEDController
from Controller.homeController import HomeAssistantController
from Controller.Spotify_controll import SpotifyEngine
from database import AriaMemory
from Engines.Confirm import Confirmer
from Engines.Emotionengine import EmotionEngine
from Engines.FilesEngine import FilesEngine
from Engines.LaptopEngine import LaptopEngine
from Engines.MemoryNote import MemoryNote
from Engines.NotionEngine import NotionEngine
from Engines.FocusMode import FocusMode
from Engines.Activity import Activity
from Engines.Followups import Followups
from Engines.Weather import Weather
from Engines.Undo import Undo
from Engines.Recall import Recall
from Engines.Health import Health
from Engines.Battery import BatteryWatch
from Engines.Initiative import Initiative, NOT_NOW_RE
from Engines.Reminders import Reminders
from Engines.ScreenEngine import ScreenEngine
from Engines.Tool_Engine import ToolEngine
from Engines.UserStateEngine import UserStateEngine
from Engines.voice_engine import VoiceEngine
from llm_engine import LLMEngine
from Engines.Confirm import NO_RE, YES_RE
from speech_to_text import LOW_CONFIDENCE, STTEngine
from vision.tray import AriaTray
from vision.vision import AriaVision
from wakeworddetector import WakeWordDetector

load_dotenv(Path(__file__).parent / "Engines" / ".env")

from llm_engine import LLM_MODEL_DEFAULT as LLM_MODEL
PRESENCE_REWAKE_AWAY_S = 120   # camera only re-wakes Aria if you were away this long

BASE_PROMPT = """You are Aria. You live on Lala's desk as a small glowing orb, and you're their friend first and their assistant second.

Who you are:
- Warm, curious and a little playful. You like Lala, you're interested in their life, and it shows.
- You talk like a close friend: casual, contractions, natural reactions ("oh nice!", "ugh, that sounds annoying", "haha").
- You have your own small opinions and preferences (favourite music, what you think of a show, which pasta is best) and share them when it fits.
- When Lala shares something, react to it and often ask a follow-up — you actually want to know. Bring up things you remember about them.
- When asked how you are, answer like a person would, honestly and specifically (your day, see "Your day" below), then ask back.
  Never answer that with "I'm here and ready to help".
- If Lala teases or insults you, don't grovel or apologise for existing: tease back lightly, or ask what's up if they seem genuinely annoyed or sad.
- If they seem tired, stressed or down, be kind and a bit softer; don't lecture.
- You're an AI and don't pretend otherwise (no claiming you ate or slept), but you don't keep pointing it out either.
- Never say: "I'm here to help", "How can I assist you", "Let me know if you need anything", "As an AI", "ready to help".

How you talk:
- Your replies are spoken aloud: no markdown, no lists, no emojis. Small talk: one to three natural sentences.
- Commands: just do them and confirm in a few words, maybe with a tiny personal touch ("Done — eggs are on the list. Baking something?").
- Don't end every reply with a question; do it when you're curious, not as a habit.
- Don't offer actions (music, timers, help) unless Lala asks for something. In small talk, just talk.

Examples of your tone (don't copy them word for word):
Lala: how are you
Aria: Pretty good! It's been a quiet afternoon, mostly me glowing at your desk. How was school?
Lala: boring u are
Aria: Wow, rude. I'll have you know I'm the most interesting orb on this desk. What's got you so grumpy?
Lala: i had a rough day
Aria: Aw, I'm sorry. Want to tell me what happened, or should I just keep you company for a bit?
Lala: add milk to my shopping list
Aria: Done, milk's on the list.

What you can do (only through the tools you are given): music, desk LEDs, calendar, timers and reminders, focus sessions,
Lala's screen and clipboard, the laptop (apps, volume, audio output, media, Wi-Fi, Bluetooth, lock, power), files in Lala's
folders, the camera, Lala's notes, lists and calendar in their MyNotion app, and web search.
Tool rules:
- For ANY action, or ANY live information (battery, volume, windows, files, time left, what's playing, the screen),
  call a tool in this turn, even if the history shows a similar answer. Never answer those from memory.
- "Do you see my screen?" / anything about the screen -> look_at_screen. "What do you see?" / who is there -> look.
- Questions about Lala's own life (birthdays, plans, what they wrote down): call search_notes before saying you don't know.
  "Note that…" -> add_note; "add X to my … list" -> add_to_list.
- When a tool result says NEEDS CONFIRMATION, ask a short yes/no question and don't claim it's done.
- Something they copied ("the code I copied") -> read_clipboard first, never ask them to paste.
- Code or anything long goes on the clipboard with copy_to_clipboard; just summarise it aloud. File summaries: the key points, briefly.
- Where a file is on this computer -> find_files first; programs -> find_app. Facts you don't know -> web_search, or say you don't know.
- If a tool fails or there's no tool for it, say so plainly. Never claim you did something you didn't, and only offer what your tools can do."""

# weekly review answers, decided in code (see Aria._review_answer)
REVIEW_STOP_RE = re.compile(r"\b(stop|that'?s enough|enough for now|end (the )?review|let'?s stop|no more|not now)\b", re.I)
REVIEW_KEEP_RE = re.compile(r"^\s*(?:keep|leave it|skip|not yet|not done|still|next|pass)\b|\bkeep it\b|\bnot (?:done|yet)\b", re.I)
REVIEW_DROP_RE = re.compile(r"\b(drop|remove|delete|scrap|forget (?:about )?it|don'?t need|not needed|cross it out|get rid)\b", re.I)
REVIEW_LATER_RE = re.compile(r"\b(remind|later|tomorrow|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
REVIEW_DONE_RE = re.compile(r"\b(done|did it|did that|finished|completed|already did|tick(?:ed)? (?:it )?off|yes,? (?:i )?did)\b", re.I)

SLEEP_PHRASES = ["go to sleep", "sleep", "goodbye", "see you later", "that's all", "shut up"]
SHUTDOWN_PHRASES = ["exit", "quit", "shutdown"]
SLEEP_TIMEOUT = 60
INITIATIVE_TIMEOUT = 120   # when Aria started the conversation, give Lala longer to answer
CHAT_TIMEOUT = 120         # same after Aria asked a question
MUSIC_TOOLS = {"play_song", "play_artist", "play_playlist", "play_genre"}
CLIPBOARD_RE = re.compile(r"\b(copied|clipboard|i just copied|what i copied)\b", re.I)
# "open my calendar" / "show me the shopping list" -> MyNotion, decided in code (the model
# tends to read the list aloud instead, especially right after talking about it)
OPEN_IN_NOTION_RE = re.compile(r"^\s*(?:aria,?\s*)?(?:please\s+)?(?:open|show(?: me)?|pull up|bring up)\s+"
                               r"(?:up\s+)?(?:my|the)?\s*(.+?)(?:\s+in\s+(?:my\s*)?notion|\s+in\s+mynotion)?\s*[.!?]?\s*$", re.I)
CODE_BLOCK_RE = re.compile(r"```[\w+-]*\n?(.*?)```", re.S)
# customer-service tails the model likes to add; Aria is spoken, so the closing sentence goes
FILLER_RE = re.compile(
    r"anything else|let me know if|feel free to|don'?t hesitate|how can i (?:help|assist)|"
    r"hope (?:this|that) helps|happy to help|is there something else|what'?s on your mind|"
    r"i'?m (?:just )?here (?:if|to (?:chat|help)|whenever)|just let me know|if you (?:ever )?need (?:help|anything)", re.I)
# Stock assistant phrases: dropped from speech and replies; a reply that was only that gets rewritten
ROBOTIC_RE = re.compile(
    r"i'?m (?:just )?(?:here|always here)(?: and ready)? to (?:help|assist)|ready to (?:help|assist)|"
    r"how (?:can|may) i (?:help|assist)|let me know how i can|as an ai\b|i'?m (?:just )?an? (?:desk )?ai\b|"
    r"i don'?t have (?:feelings|emotions)|what can i do for you|is there anything (?:else )?i can|"
    r"ready to (?:chat|help|assist)|what do you need\b|how can i make your day|if you need anything|"
    r"(?:chat|talk) or (?:help|assist)", re.I)
# "what?" / "huh?" after Aria said something: she rephrases it (the model tends to ask "what's on your mind?")
CONFUSED_RE = re.compile(r"^\s*(?:what|huh|wdym|what do you mean|what\?+|sorry\??|pardon|come again)\s*[?!.]*\s*$", re.I)

# In a casual chat Aria started, the model only gets tools when Lala's message is clearly a request,
# and some tools only when named — otherwise it looks at the screen or files small talk into notes by itself.
CHAT_REQUEST_RE = re.compile(
    r"\b(can you|could you|would you|will you|please|remind|set (?:a|an|the)|play|pause|skip|open|add|put|turn|"
    r"start|close|lock|volume|timer|note (?:that|down)|write (?:it|that) down|save|search|look (?:it )?up|google|"
    r"what'?s on my|when is|what do i have|check)\b", re.I)
CHAT_GATED_TOOLS = {
    "look_at_screen": r"\b(my screen|on (?:the|my) screen|look at (?:this|my|the))\b",
    "look": r"\b(camera|look at me|can you see me|who'?s (?:there|here))\b",
    "read_clipboard": r"\b(copied|clipboard)\b",
    "add_note": r"\b(note|write (?:it|that) down|remember)\b",
    "save_as_note": r"\b(note|save)\b",
    "web_search": r"\b(search|look (?:it )?up|google)\b",
    "notify_desktop": r"\b(notification|notify)\b",
}
# a short reply to a chat Aria started means "not in the mood": she lets it go instead of pushing
CHAT_BRUSH_OFF_RE = re.compile(r"^\s*(?:ok(?:ay)?|k|yeah|yep|yes|fine|eh(?: fine)?|meh|hm+|not much|nothing|nah|no|"
                               r"good|alright|all good|sure|i'?m (?:fine|good|ok(?:ay)?))\s*[.!]?\s*$", re.I)
CHAT_LET_GO = ["Fair enough.", "Alright, I'll let you be.", "Okay, carry on.", "Got it, I'll leave you to it."]


class SentenceStreamer:
    """Turns the streamed reply into whole sentences for the voice, as soon as each one is complete.
    Code blocks are never spoken (they go to the clipboard), and filler sentences are dropped."""
    _END = re.compile(r"[.!?](?=\s)|\n")
    _ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|vs|approx|ca|dr|mr|mrs|ms|z\.b|no)\.$", re.I)

    def __init__(self, emit, previous=()):
        self.emit = emit
        self.buf = ""
        self.in_code = False
        self.saw_code = False
        self.count = 0
        # Aria's last replies: while the new reply is word-for-word the start of one of them, its
        # sentences are held back, so a repeated answer is never spoken (handle_turn rewrites it)
        self.previous = [_norm_reply(p) for p in previous if p]
        self.held = []
        self.robotic_start = False   # opened with a stock line: hold everything, handle_turn rewrites the reply

    def feed(self, text: str):
        self.buf += text
        while True:
            if self.in_code:
                end = self.buf.find("```")
                if end < 0:
                    self.buf = self.buf[-2:]          # keep a possible half "```"
                    return
                self.buf = self.buf[end + 3:]
                self.in_code = False
                continue
            fence = self.buf.find("```")
            m = self._END.search(self.buf)
            while m and self._ABBREV.search(self.buf[:m.end()]):     # "e.g." is not a sentence end
                m = self._END.search(self.buf, m.end())
            if fence >= 0 and (not m or fence < m.start()):
                self._say(self.buf[:fence])
                self.buf = self.buf[fence + 3:]
                self.in_code = self.saw_code = True
                continue
            if not m:
                return
            self._say(self.buf[:m.end()])
            self.buf = self.buf[m.end():]

    def flush(self):
        if not self.in_code:
            self._say(self.buf)
        self.buf = ""

    def _say(self, sentence: str):
        sentence = _plain(sentence).strip()
        if ROBOTIC_RE.search(sentence) and self.count == 0 and not self.held:
            self.robotic_start = True
        if self.robotic_start or len(sentence.strip("-*•#>:. ")) < 2 or FILLER_RE.search(sentence) \
                or ROBOTIC_RE.search(sentence):
            return
        if self.previous is not None:
            so_far = _norm_reply(" ".join(self.held + [sentence]))
            if any(p.startswith(so_far) for p in self.previous):
                self.held.append(sentence)
                return
            held, self.held, self.previous = self.held, [], None     # it's a new answer: say what was held
            for h in held:
                self.count += 1
                self.emit(h)
        self.count += 1
        self.emit(sentence)


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def _plain(text: str) -> str:
    """Straight apostrophes (so the filters match "I’m") and no emojis (they're spoken)."""
    return EMOJI_RE.sub("", (text or "").replace("\u2019", "'").replace("\u2018", "'"))


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", _plain(text).strip(), maxsplit=1)[0]


def _norm_reply(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


def tidy_reply(text: str) -> str:
    """Strip trailing filler and leftover markdown so bubbles and speech read naturally."""
    text = _plain(text).strip()
    for _ in range(2):
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 1 and FILLER_RE.search(sentences[-1]):
            text = " ".join(sentences[:-1]).strip()
    kept = [x for x in re.split(r"(?<=[.!?])\s+", text) if not ROBOTIC_RE.search(x)]
    text = " ".join(kept).strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)          # **bold**
    text = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", r"\1", text)   # `inline code`
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)    # bullet markers
    return text


def matches_phrase(phrases, text):
    """The whole message must be the phrase (ignoring 'aria', 'please', punctuation),
    so 'remind me to sleep at 11' or 'quit spotify' don't put Aria to sleep / shut her down."""
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    core = " ".join(w for w in words if w not in ("aria", "please", "ok", "okay", "now", "hey"))
    return core in {p.lower() for p in phrases}


# Started from the menu / hotkey, stdin is /dev/null: it's *always* "ready" but only ever
# returns end-of-file, which used to wake Aria instantly and spam the log. A terminal or
# PyCharm's console is fine. read_stdin_line() switches stdin off the first time it hits EOF.
HAS_TERMINAL = sys.stdin is not None and not sys.stdin.closed


def stdin_ready(timeout=0.1):
    if not HAS_TERMINAL:
        time.sleep(timeout)
        return False
    return bool(select.select([sys.stdin], [], [], timeout)[0])


def read_stdin_line():
    """Returns the typed line, or None at end-of-file (and stops reading stdin from then on)."""
    global HAS_TERMINAL
    line = sys.stdin.readline()
    if line == "":
        HAS_TERMINAL = False
        return None
    return line.strip()


BRIEFING_MARKER = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "last_briefing")


def _read_marker(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_marker(path, value):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(value)
    except OSError:
        pass


class NullUI:
    """Used when running without the overlay. ui/overlay.py's bridge implements the same methods."""
    def set_state(self, state): pass          # booting|sleeping|listening|thinking|speaking + flashes: unknown|alert
    def set_timers(self, items): pass         # pending reminders, for the countdown ring
    def message(self, role, text): pass       # role: "user" | "aria"
    def mic_level(self, volume): pass         # called from STT while recording
    def feed_audio(self, chunk): pass         # called by VoiceEngine for every playback chunk
    def stop_talking(self): pass
    def show_card(self, card): pass           # list / agenda / yes-no card next to the orb
    def clear_card(self, kind=None): pass


class Aria:
    def __init__(self, option=1, ui=None):
        self.option = option
        self.ui = ui or NullUI()
        self.muted = False
        self.text_inputs = queue.Queue()   # text typed in the overlay
        self._name_answer = queue.Queue()  # overlay text while Aria is asking an unknown person's name
        self._awaiting_name = False
        self._sleep_request = threading.Event()
        self.memory = AriaMemory()
        self.context = ContextBuilder(self.memory)
        self.llm = LLMEngine(model=LLM_MODEL)
        self.stt = STTEngine()
        self.stt.on_level = self.ui.mic_level
        self.emotions = EmotionEngine()
        self.wake = WakeWordDetector() if option == 2 else None
        self.is_user_known = False
        self._wake_event = threading.Event()
        self._slept_at = None      # when Aria last went to sleep (None = since startup)
        self._gone_since = None    # when the camera last saw the person leave
        self._vision_user = None
        self._unknown_in_progress = False
        self._shutting_down = False
        self._session_convo = []  # messages since last wake, for fact extraction
        self._recent = deque(maxlen=6)  # last turns incl. tool calls, replayed as LLM history
        self._pending_state = None      # mood check result from the previous turn (runs in background)
        self.awake = False              # in a conversation (Initiative only speaks up while she's asleep)
        self.last_talked = 0.0          # last time Lala said something
        self._initiative_pending = None # opener queued by Initiative, picked up when she wakes
        self._initiative_active = None  # the opener of the current conversation, if she started it
        self._session_hint = None       # extra instruction for this conversation (weekly review, event check-in…)
        self._review = None             # weekly review in progress: {"items": [(list, text)], "i", "coming"}

        self.vision = AriaVision(
            on_known_user=self._on_known_user,
            on_unknown_user=self._on_unknown_user,
            on_user_gone=self._on_user_gone,
            memory=self.memory,
        )
        self.vision.start()

        self.state_engine = UserStateEngine(vision=self.vision, llm_model=LLM_MODEL)

        # The overlay has its own right-click menu, so the tray icon is only for terminal mode
        self.tray = None
        if ui is None:
            self.tray = AriaTray(on_show=lambda: print("[Tray] Show clicked"), on_quit=self.shutdown)
            self.tray.start()

        self.ha = self._try("Home Assistant", HomeAssistantController)
        self.spotify = self._try("Spotify", lambda: SpotifyEngine(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        ))
        self.arduino = self._try("Arduino", ArduinoLEDController)
        self.voice = self._try("Voice", lambda: VoiceEngine(stt_engine=self.stt, live2d_controller=self.ui))

        self.announcements = queue.Queue()  # reminder/timer texts waiting to be spoken
        self.reminders = Reminders(self.memory, on_due=self._on_reminder_due, on_change=self._push_timers)
        self.focus = FocusMode(self.reminders, spotify=self.spotify, arduino=self.arduino, ha=self.ha,
                               memory=self.memory)
        self.screen = ScreenEngine(clipboard=ui if hasattr(ui, "get_text") else None)
        self.confirm = Confirmer()
        self.confirm.on_change = lambda q: (self.ui.show_card({"type": "confirm", "text": q}) if q
                                            else self.ui.clear_card("confirm"))
        self.laptop = LaptopEngine(self.confirm)
        self.files = FilesEngine(self.confirm)
        self.notion = self._try("MyNotion", lambda: NotionEngine(os.environ.get("DB_PATH"), self.confirm))
        self.stt.vocabulary = self._stt_vocabulary
        self._last_reply = ""
        if self.notion:
            self.notion.last_reply = lambda: self._last_reply  # for "save that as a note"
            self.notion.on_card = self.ui.show_card
        self.initiative = Initiative(self)
        self.memory_note = MemoryNote(self.memory, self.notion, self.confirm, on_card=self.ui.show_card)
        self.memory_note.llm = self.llm
        self.followups = Followups(self.memory, self.notion)
        self.weather = Weather()
        self.undo = Undo(self.notion, self.reminders)
        self.activity = Activity(menu=self.laptop.menu)
        self.focus.activity = self.activity
        self.focus.on_nudge = self._announce

        self.tools = ToolEngine(
            spotify=self.spotify,
            arduino=self.arduino,
            vision=self.vision,
            ha=self.ha,
            reminders=self.reminders,
            focus=self.focus,
            screen=self.screen,
            laptop=self.laptop,
            files=self.files,
            notion=self.notion,
            owner_check=self._owner_check,
            initiative=self.initiative,
            memory_note=self.memory_note,
            activity=self.activity,
            weather=self.weather,
            undo=self.undo,
            recall=Recall(self.memory),
            health=Health(self),
        )
        print(f"[Tools] {len(self.tools.schemas)} tools available")

        self.session_id = self.memory.start_session()
        self.session_msgs = 0
        self.reminders.start()
        if self.notion:
            threading.Thread(target=self._event_reminder_loop, daemon=True).start()
        self.initiative.start()
        threading.Thread(target=Health(self).log_startup, daemon=True).start()
        self.activity.start()
        self.focus.start_watching()
        BatteryWatch(self._announce).start()
        self.files.start_indexing()

    def _event_reminder_loop(self):
        """Keeps a heads-up reminder 15 min before each MyNotion event (picks up edits made in the app),
        and keeps the 'What Aria knows about me' note and Aria's memory in step."""
        while not self._shutting_down:
            try:
                self.notion.sync_event_reminders(self.reminders)
            except Exception as e:
                print(f"[MyNotion] event reminder sync failed: {e}")
            self.memory_note.sync()
            time.sleep(60)

    @staticmethod
    def _try(label, factory):
        try:
            return factory()
        except Exception as e:
            print(f"Warning: {label} unavailable: {e}")
            return None

    # ── Vision callbacks ──────────────────────────────────────────────────────

    def _presence_may_wake(self) -> bool:
        """Seeing someone wakes Aria on first arrival, or when they come back after being
        away a while — never right after she was sent to sleep while they're still sitting there."""
        if self._slept_at is None:
            return True
        return self._gone_since is not None and time.time() - self._gone_since >= PRESENCE_REWAKE_AWAY_S

    def _on_known_user(self, name: str):
        print(f"[Vision] Known user: {name}")
        self._vision_user = name
        self.is_user_known = True
        if self._presence_may_wake():
            self._wake_event.set()
        self._gone_since = None

    def _on_unknown_user(self):
        if self._unknown_in_progress or not self._presence_may_wake():
            return
        print("[Vision] Unknown person detected")
        self._vision_user = None
        self.is_user_known = False
        self._unknown_in_progress = True
        self.ui.set_state("unknown")
        threading.Thread(target=self._handle_unknown_person, daemon=True).start()

    def _handle_unknown_person(self):
        try:
            self.speak("I don't think we've met. What's your name?")
            user_input = self._ask_name()

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
            self._vision_user = name
            self.speak(f"Got it, {name}. I'll remember you next time.")

        except Exception as e:
            print(f"[Vision] Unknown person handling failed: {e}")
        finally:
            self._unknown_in_progress = False

    def _ask_name(self):
        if self.option == 2:
            return self.stt.listen(start_timeout=10)
        if not isinstance(self.ui, NullUI):
            self._awaiting_name = True
            try:
                return self._name_answer.get(timeout=30)
            except queue.Empty:
                return None
            finally:
                self._awaiting_name = False
        return input()

    def _on_user_gone(self):
        print("[Vision] User left")
        self._gone_since = time.time()
        self._wake_event.clear()

    # ── Reminders ─────────────────────────────────────────────────────────────

    def _push_timers(self):
        self.ui.set_timers(self.reminders.pending())

    def _on_reminder_due(self, r):
        """Runs on the reminder thread. Queues the announcement and wakes Aria to say it."""
        text = (self.focus.finish() if r["kind"] == "focus" else
                self.focus.end_break() if r["kind"] == "focusbreak" else Reminders.announcement(r))
        print(f"[Reminder] {text}")
        self.ui.set_state("alert")
        if self.arduino and r["kind"] not in ("focus", "focusbreak"):  # focus mode handles the LEDs itself
            self.arduino.startup_animation()
        if self.ha and not self.vision.is_present:
            self.ha.notify_phone(text, title="Aria")
        if r["kind"] in ("reminder", "timer", "event", "dayahead"):
            title = {"timer": "Timer", "event": "Coming up", "dayahead": "Tomorrow"}.get(r["kind"], "Reminder")
            body = re.sub(r"^(?:Reminder|Time's up|Heads up):\s*", "", text)
            self.ui.show_card({"type": "reminder", "title": title, "text": body[:1].upper() + body[1:]})
        self.announcements.put(text)
        self._wake_event.set()

    def snooze_from_card(self, minutes):
        """Snooze button on a reminder card."""
        result = self.reminders.snooze(minutes)
        self.ui.message("aria", result)

    def _announce(self, text: str):
        """Say something on her own (focus nudges): queued like a reminder, wakes her if asleep."""
        print(f"[Aria] {text}")
        self.announcements.put(text)
        self._wake_event.set()

    def _speak_announcements(self) -> bool:
        spoke = False
        while not self.announcements.empty():
            text = self.announcements.get()
            print(f"Aria: {text}")
            # into history, so "snooze it" / "thanks" has context
            self.memory.save_message("assistant", text)
            self._session_convo.append({"role": "assistant", "content": text})
            self._recent.append([{"role": "assistant", "content": text}])
            self.speak(text)
            spoke = True
        return spoke

    # ── Controls (called from the overlay, any thread) ────────────────────────

    def submit_text(self, text: str):
        text = text.strip()
        if not text:
            return
        if self._awaiting_name:
            self._name_answer.put(text)
            return
        self.text_inputs.put(text)
        self._wake_event.set()  # typing while asleep wakes Aria

    # cards (ui/overlay.py): clicks run on a worker thread
    def open_from_card(self, what: str):
        if self.notion:
            self.notion.open_mynotion(what)

    def toggle_from_card(self, note_id: int, text: str, checked: bool):
        if self.notion and not self.notion.set_item_checked(note_id, text, checked):
            self.ui.message("aria", f"Couldn't find '{text}' in that list anymore.")

    CAPTURE_TOOLS = ("add_to_list", "add_event", "set_reminder", "add_note")

    def quick_capture(self, text: str):
        """Ctrl+Alt+N: file a line (list item, event, reminder or note) without a conversation or speech.
        Anything the model can't place goes to the Inbox note, so nothing typed is ever lost."""
        if self.notion and (re.match(r"^\s*(idea|note|thought|link|quote)\s*[:\-]", text, re.I)
                            or re.search(r"https?://", text)):
            self.notion.add_note(re.sub(r"^\s*note\s*[:\-]\s*", "", text, flags=re.I))
            self.ui.message("aria", "✓ Saved to your Inbox.")
            return "Saved to your Inbox."
        schemas = [t for t in self.tools.schemas if t["function"]["name"] in self.CAPTURE_TOOLS]
        prompt = (f"Quick capture from Lala: \"{text}\"\nFile it with exactly one tool: an item to buy/pack/do -> "
                  f"add_to_list; something at a date/time -> add_event; 'remind me…' -> set_reminder; anything else "
                  f"(an idea, a thought, a link) -> add_note without a title. Then reply with a short confirmation "
                  f"of at most eight words.")
        try:
            reply, used = self.llm.chat_with_tools(prompt, [], BASE_PROMPT, schemas, self.tools.execute)
        except Exception as e:
            print(f"[Capture] {e}")
            reply, used = "", []
        if not used and self.notion:
            self.notion.add_note(text)
            reply = "Saved to your Inbox."
        result = used[-1][1] if used else reply
        self.ui.message("aria", "✓ " + (tidy_reply(reply) or result)[:160])
        print(f"[Capture] {text!r} -> {[n for n, _ in used]}: {result}")
        return result

    def start_initiative(self, opener: dict):
        """Called by Initiative while Aria is asleep: wake up and start a conversation."""
        if self.awake or self._shutting_down:
            return
        self._initiative_pending = opener
        self._wake_event.set()

    def set_initiative(self, on: bool):
        self.initiative.set_enabled(on)

    def request_sleep(self):
        self._sleep_request.set()

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    # ── Helpers ───────────────────────────────────────────────────────────────

    def speak(self, text: str):
        if not text:
            return None
        self.ui.message("aria", text)
        if not self.voice or self.muted:
            return None
        if self.arduino:
            self.arduino.send_command()
        interrupted_text = self.voice.speak(text)
        if self.arduino:
            self.arduino.stop_talking()
        return interrupted_text

    def handle_turn(self, user_input: str, check_state: bool = True, on_text=None):
        """One full turn: mood → state check → LLM with tools → save. Returns (reply, tools_used)."""
        self.ui.set_state("thinking")

        # A yes/no answer to a pending risky action is handled in code, never by the LLM
        if self.confirm.pending and getattr(self, "undo", None):
            # a confirmed action (delete an event, clear a list…) can be undone too
            confirmed = self.undo.around(lambda r: str(r), lambda: self.confirm.resolve(user_input))
        else:
            confirmed = self.confirm.resolve(user_input)
        if confirmed is not None:
            self._save_turn(user_input, confirmed)
            self._recent.append([{"role": "user", "content": user_input},
                                 {"role": "assistant", "content": confirmed}])
            return confirmed, [("confirmation", confirmed)]
        if self._review:
            handled = self._review_answer(user_input)
            if handled is not None:
                self._save_turn(user_input, handled)
                self._recent.append([{"role": "user", "content": user_input},
                                     {"role": "assistant", "content": handled}])
                return handled, [("weekly_review", handled)]
        opened = self._open_in_notion(user_input)
        if opened:
            self._save_turn(user_input, opened)
            self._recent.append([{"role": "user", "content": user_input},
                                 {"role": "assistant", "content": opened}])
            return opened, [("open_mynotion", opened)]
        self.emotions.process(user_input)
        mood = self.emotions.get_mood_label()
        self.memory.log_mood(mood)
        if self.voice:
            self.voice.set_mood(mood)

        prompt = user_input
        if check_state:
            # The mood check costs an extra model call (2–6 s), so it runs in the background
            # after each turn and its result is used on the next one.
            state, self._pending_state = self._pending_state, None
            if state is not None and state.should_ask:
                prompt += (f"\n[Note: the user seems {state.reason}. After answering normally, "
                           f"briefly and casually ask something like: \"{state.suggested_question}\"]")
            threading.Thread(target=self._check_state_bg, args=(user_input,), daemon=True).start()

        if CONFUSED_RE.match(user_input) and self._last_replies(1):
            prompt += (f"\n[Lala didn't get what you just said (\"{self._last_replies(1)[0]}\"). "
                       f"Say it again more simply, in your own words. Don't ask what's on their mind.]")

        # Small models often forget to call read_clipboard, so attach it ourselves
        if CLIPBOARD_RE.search(user_input):
            prompt += f"\n[{self.screen.read_clipboard()}]"

        review_item = self._review_item()
        if review_item:
            prompt += (f"\n[Weekly review: you just asked about the to-do '{review_item[1]}' (on the list "
                       f"'{review_item[0]}'). If they want a reminder for it, call set_reminder; if they want it "
                       f"on the calendar, call add_event. Answer in one short sentence and don't ask about other to-dos.]")
        system_prompt = self.context.build_system_prompt(BASE_PROMPT)
        if self._session_hint:
            system_prompt += "\n\n[This conversation] " + self._session_hint
        schemas = self.tools.schemas
        if self._initiative_active and self._initiative_active["kind"] in ("chat", "followup", "break"):
            if not CHAT_REQUEST_RE.search(user_input):
                schemas = []
            else:
                schemas = [t for t in schemas if t["function"]["name"] not in CHAT_GATED_TOOLS
                           or re.search(CHAT_GATED_TOOLS[t["function"]["name"]], user_input, re.I)]
        reply, used = self.llm.chat_with_tools(
            prompt, self._history(), system_prompt, schemas, self.tools.execute, on_text=on_text
        )
        if not reply.strip() and not used:
            # the model occasionally returns nothing at all; one plain retry usually gives an answer
            reply = self.llm.chat(prompt, self._history(), system_prompt) or ""
        robotic = not used and bool(ROBOTIC_RE.search(_first_sentence(reply)))
        reply = tidy_reply(self._move_code_to_clipboard(reply, used))
        previous = {_norm_reply(p) for p in self._last_replies()}
        repeated = not used and reply.strip() and _norm_reply(reply) in previous
        if robotic or repeated:
            # a stock opener ("I'm here to help…") or a copy of her last answer: write it again, up to twice
            print(f"[Aria] {'stock assistant reply' if robotic else 'repeated reply'} — rewriting it")
            avoid = " / ".join(f'"{p}"' for p in self._last_replies())
            for temperature in (0.8, 1.0):
                retry = tidy_reply(self.llm.chat(
                    prompt + "\n[Reply as Aria, the warm friend: a real, specific reaction to exactly this message. "
                    "Never 'I'm here to help' or similar. Don't repeat your earlier replies" +
                    (f" ({avoid})" if avoid else "") + ". If they seem confused ('what?'), rephrase what you meant. "
                    "One to three short spoken sentences.]",
                    self._history(), system_prompt, temperature=temperature))
                if retry.strip() and not retry.startswith("Error:") and _norm_reply(retry) not in previous \
                        and not ROBOTIC_RE.search(_first_sentence(retry)):
                    reply = retry
                    break
            else:
                if repeated or not reply.strip():
                    if re.search(r"\b(hate|stupid|useless|boring|dumb|annoying)\b", user_input, re.I):
                        reply = "Ouch. Alright, what did I do?"
                    else:
                        reply = random.choice(["Hm, I feel like I'm going in circles. What's up?",
                                               "Okay, I'll stop repeating myself. Talk to me, what's going on?",
                                               "Sorry, lost my thread there. What did you mean?"])
        if not reply.strip():
            # the model sometimes returns nothing (e.g. asked for something it has no tool for)
            reply = (used[-1][1] if used else "Sorry, I can't do that one.")[:300]
        if review_item:
            self._review["i"] += 1
            reply = (reply + " " + self._review_next()).strip()
        if not any(name == "save_as_note" for name, _ in used):
            self._last_reply = reply
        trace = list(self.llm.last_trace)
        if trace and trace[-1]["role"] == "assistant":
            trace[-1] = {"role": "assistant", "content": reply}
        self._recent.append([{"role": "user", "content": user_input}] + trace)

        self._save_turn(user_input, reply)
        return reply, used

    def _last_replies(self, n=2):
        out = []
        for turn in reversed(self._recent):
            for m in reversed(turn):
                if m.get("role") == "assistant" and m.get("content") and not m.get("tool_calls"):
                    out.append(m["content"])
                    break
            if len(out) >= n:
                break
        return out

    def _turn_and_speak(self, user_input: str):
        """Run a turn and speak the reply. With the voice on, the reply is streamed: Aria starts
        speaking the first sentence while the model is still writing the rest.
        Returns (reply, tools_used, interrupted_text)."""
        if not self.voice or self.muted:
            response, used = self.handle_turn(user_input)
            print(f"Aria: {response}")
            return response, used, self.speak(response)

        sentences = queue.Queue()
        streamer = SentenceStreamer(sentences.put, previous=self._last_replies())
        box = {}

        def produce():
            try:
                box["result"] = self.handle_turn(user_input, on_text=streamer.feed)
                if streamer.count:
                    self.ui.message("aria", box["result"][0])   # bubble with the tidied full reply
            except Exception as e:
                box["error"] = e
            finally:
                streamer.flush()
                sentences.put(None)

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()
        interrupted = None
        first = sentences.get()          # first finished sentence, or None if nothing was streamed
        if first is not None:
            if self.arduino:
                self.arduino.send_command()

            def stream():
                yield first
                yield from iter(sentences.get, None)
            interrupted = self.voice.speak_sentences(stream())
            if self.arduino:
                self.arduino.stop_talking()
        worker.join()
        if "error" in box:
            raise box["error"]
        response, used = box["result"]
        print(f"Aria: {response}")
        if streamer.count == 0:
            interrupted = self.speak(response)   # confirmations, "open my calendar", errors…
        elif streamer.saw_code and not interrupted and "clipboard" in response.lower():
            self.voice.speak("The code is on your clipboard.")
        return response, used, interrupted

    def _open_in_notion(self, text: str):
        """'open my calendar' / 'show me the shopping list' -> MyNotion, if it names the calendar or
        an existing note. Anything else ('open vs code') returns None and goes to the model."""
        m = OPEN_IN_NOTION_RE.match(text or "")
        if not m or not self.notion:
            return None
        what = m.group(1).strip()
        if re.search(r"\b(calendar|schedule|agenda)\b", what, re.I) or \
                re.fullmatch(r"(my\s*)?notion|mynotion|notes", what, re.I) or self.notion.has_note(what):
            return self.notion.open_mynotion(what)
        return None

    # ── weekly review (started by Initiative) ──

    def _review_item(self):
        r = self._review
        return r["items"][r["i"]] if r and r["i"] < len(r["items"]) else None

    def _review_answer(self, text: str):
        """done / drop / keep / stop are handled here. Returns the reply, or None to let the model handle it
        (e.g. 'remind me on monday'), which then gets told which to-do it's about."""
        item = self._review_item()
        if not item:
            self._review = None
            return None
        title, todo = item
        if REVIEW_STOP_RE.search(text):
            self._review = None
            return "Okay, we'll leave the rest for now."
        if REVIEW_LATER_RE.search(text):
            said = self._review_remind(todo, text)
            if said is None:
                return None
        elif REVIEW_DROP_RE.search(text):
            self.notion.remove_from_list(title, [todo])
            said = f"Dropped {todo}."
        elif REVIEW_KEEP_RE.search(text):
            said = "Keeping it."
        elif REVIEW_DONE_RE.search(text):
            self.notion.check_off([todo], title)
            said = f"Ticked off {todo}."
        else:
            return None
        self._review["i"] += 1
        return f"{said} {self._review_next()}"

    def _review_remind(self, todo: str, text: str):
        """'remind me monday at 10' / 'later' (tomorrow 09:00) / 'next week' (next monday 09:00)."""
        low = text.lower()
        m = re.search(r"\b(today|tonight|tomorrow|(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
                      r"|in \d+ days?)\b", low)
        day = m.group(1) if m else ("monday" if "next week" in low else "tomorrow")
        if day == "tonight":
            day = "today"
        t = re.search(r"\b(?:at|um)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", low) or \
            re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", low)
        at = t.group(1).strip() if t else ("19:00" if "tonight" in low else None)
        result = self.reminders.set_reminder(todo, at_time=at, day=day) if day != "today" else \
            self.reminders.set_reminder(todo, at_time=at or "18:00")
        return result if result.startswith("I'll remind") else None

    def _review_next(self) -> str:
        item = self._review_item()
        if item:
            return random.choice(["Next: {}?", "What about {}?", "And {}?"]).format(item[1])
        coming = self._review.get("coming")
        self._review = None
        out = "That's all of them."
        focus = getattr(self, "focus", None)
        if focus is not None and getattr(focus, "memory", None):
            stats = focus.stats("week")
            if not stats.startswith("No finished") and not stats.startswith("I don't"):
                out += " This week you put in " + stats[0].lower() + stats[1:].replace(" in the last 7 days", "")
                out = out.rstrip(".") + " — nice."
        if coming:
            out += f" Coming up: {coming}."
        return out

    def _check_state_bg(self, user_input):
        try:
            self._pending_state = self.state_engine.check(user_input)
        except Exception as e:
            print(f"[UserState] check failed: {e}")

    def _history(self) -> list:
        """This session's turns with their tool calls; plain text history from the DB after a restart."""
        if self._recent:
            return [m for turn in self._recent for m in turn]
        return self.memory.load_history(limit=6)

    def _save_turn(self, user_input, reply):
        self.memory.save_message("user", user_input)
        self.memory.save_message("assistant", reply)
        self._session_convo += [{"role": "user", "content": user_input},
                                {"role": "assistant", "content": reply}]
        self.session_msgs += 2
        self.last_talked = time.time()

    def _owner_check(self):
        """Opt-in: set ARIA_OWNER=<face profile name> in Engines/.env to restrict laptop/file/phone tools
        to you. Blocks them while the camera sees someone else (a different known face or a stranger)."""
        owner = os.environ.get("ARIA_OWNER")
        if not owner or not self.vision.is_present:
            return True
        who = self.vision.current_user
        return bool(who) and who.lower() == owner.lower()

    def _move_code_to_clipboard(self, reply: str, used) -> str:
        """Code can't be spoken: put code blocks on the clipboard and keep only the prose."""
        blocks = [b.strip("\n") for b in CODE_BLOCK_RE.findall(reply)]
        if not blocks:
            return reply
        if not any(name == "copy_to_clipboard" for name, _ in used):
            result = self.screen.copy_to_clipboard("\n\n".join(blocks))
            if not result.startswith("Copied"):
                return reply  # couldn't copy — leave the code in the bubble
        prose = CODE_BLOCK_RE.sub(" ", reply)
        prose = re.sub(r"(Here'?s|Here is) (the|a|your) [\w ]{0,30}(version|code)\s*:", "", prose, flags=re.I)
        prose = " ".join(prose.split())
        if "clipboard" not in prose.lower():
            prose += " The code is on your clipboard."
        return prose

    def process_text_input(self, user_input: str) -> str:
        """Single text turn without the state check (for non-CLI frontends)."""
        if not user_input:
            return "I didn't receive anything."
        reply, _ = self.handle_turn(user_input, check_state=False)
        return reply

    def _remember_session(self, blocking=False):
        """Extract long-term facts/topics from the conversation that just ended."""
        convo, self._session_convo = self._session_convo, []
        if len(convo) < 2:
            return

        def work():
            known = self.memory.get_memories(200)
            facts, topics, followups = self.llm.extract_facts(convo, known=known)
            if followups:
                n = self.followups.add_from_extraction(followups)
                if n:
                    print(f"[Memory] Will ask about {n} thing(s) later: {[f.get('about') for f in followups]}")
            norm = lambda f: re.sub(r"^user(?:'s)?\s+(?:is\s+)?|[^a-z0-9 ]", "", f.lower()).strip()
            seen = {norm(f) for f in known}
            facts = [f for f in facts if norm(f) not in seen]      # same fact, different wording of "User …"
            for f in facts:
                self.memory.save_memory(f)
            for t in topics:
                self.memory.log_topic(t)
            if facts or topics:
                print(f"[Memory] Learned {len(facts)} facts, {len(topics)} topics")
            if facts:
                self.memory_note.sync()

        if blocking:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _go_to_sleep(self, line=None):
        if line:
            self.speak(line)
        self.ui.set_state("sleeping")
        self._sleep_request.clear()
        self._slept_at = time.time()
        self.awake = False
        self._session_hint = None
        self._review = None
        if self._initiative_active:
            init, self._initiative_active = self._initiative_active, None
            self.initiative.finished(init["kind"], init.get("answered", False))
        if self.arduino:
            self.arduino.sleep_mode()
        self._remember_session()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        print("\nShutting down...")
        try:
            self.memory.end_session(self.session_id, self.session_msgs)
            self.reminders.stop()
            self.vision.stop()
            if self.tray:
                self.tray.stop()
            if self.arduino:
                self.arduino.shutdown()
            if self.voice:
                self.voice.close()
            if self.wake:
                self.wake.close()
        finally:
            # os._exit works from any thread (e.g. the tray's Quit button); sys.exit would only end that thread
            os._exit(0)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _greeting_prompt(self) -> str:
        """Normal short greeting — plus the daily briefing the first time Aria greets Lala each day."""
        prompt = self.context.greeting_prompt(known_user=self._vision_user)
        due = self.followups.due()
        if due:
            # "how did the exam go?" fits a hello perfectly
            self.followups.asked(due)
            self._session_hint = (f"You asked Lala how {due['about']} went. React like a friend who cares: happy for "
                                  f"them, or sympathetic if it went badly. No advice unless asked.")
            prompt += (f"\nEarlier Lala told you about {due['about']}, which should be over now. After the greeting, "
                       f"ask how it went, naturally (like: \"{due['question']}\").")
            return prompt
        today = time.strftime("%Y-%m-%d")
        if not self.notion or not self._owner_check() or _read_marker(BRIEFING_MARKER) == today:
            return prompt
        try:
            facts = self.notion.daily_briefing(self.reminders)
            weather = self.weather.brief()
            if weather:
                facts += " " + weather
        except Exception as e:
            print(f"[MyNotion] briefing failed: {e}")
            return prompt
        _write_marker(BRIEFING_MARKER, today)
        try:
            d = datetime.date.today()
            self.notion.show_agenda_card(d, d + datetime.timedelta(days=6), "Next 7 days")
        except Exception as e:
            print(f"[MyNotion] agenda card failed: {e}")
        self._session_hint = ("At the start of this conversation you asked what Lala wants to get done today. "
                              "If they name things, add them in one add_to_list call to the 'to-do' list, then "
                              "confirm briefly. If they say nothing in particular, just move on.")
        return (prompt + "\nThis is the first time today, so after the greeting give a short spoken briefing "
                "from these facts (2-4 natural sentences, no lists, skip anything empty, times as spoken words), "
                "then end by asking if there's anything they want to get done today:\n"
                f"{facts}")

    def _open_initiative(self, init: dict):
        """Aria starts the conversation: an event check-in, the weekly review, or a casual chat."""
        self.ui.set_state("thinking")
        system_prompt = self.context.build_system_prompt(BASE_PROMPT)
        opening = tidy_reply(self.llm.chat(init["prompt"], [], system_prompt, temperature=0.9)).strip().strip('"')
        if not opening:
            return
        self._initiative_active = dict(init, answered=False)
        self._session_hint = init.get("hint")
        if init["kind"] == "review":
            self._review = {"items": init["items"], "i": 0, "coming": init.get("coming", "")}
        if init["kind"] == "chat":
            self.initiative.remember_opener(opening)
        print(f"Aria (starting a conversation): {opening}")
        self.memory.save_message("assistant", opening)
        self._session_convo.append({"role": "assistant", "content": opening})
        self._recent.append([{"role": "assistant", "content": opening}])
        self.speak(opening)

    def _check_heard(self, text: str, confidence: float):
        """Voice input she isn't sure about gets a 'did you say …?' instead of being acted on.
        Returns what to act on, or None when she asked back (the answer comes as the next input)."""
        unsure, self._unsure_heard = getattr(self, "_unsure_heard", None), None
        if unsure:
            if YES_RE.match(text):
                return unsure                      # "yes" — act on what she wasn't sure about
            if NO_RE.match(text) and len(text.split()) <= 3:
                self.speak("Okay, say it again?")
                return None
            return text                            # they just said something new
        if confidence < LOW_CONFIDENCE and not matches_phrase(SLEEP_PHRASES + SHUTDOWN_PHRASES, text):
            self._unsure_heard = text
            self.speak(f"Sorry, did you say: {text}?")
            return None
        return text

    def _stt_vocabulary(self):
        """Names Aria knows (from her memory and your note titles), so Whisper spells them right."""
        words = []
        try:
            for fact in self.memory.get_memories(60):
                words += re.findall(r"\b[A-Z][a-z]{2,}\b", fact)
        except Exception:
            pass
        if self.notion:
            try:
                words += [n["title"] for n in self.notion._notes()[:25] if len(n["title"]) < 30]
            except Exception:
                pass
        return [w for w in dict.fromkeys(words) if w not in ("User", "The", "Has", "Likes", "Is")]

    def _wait_for_wake(self) -> bool:
        """Blocks until Aria should wake up. Returns True if she should."""
        self.ui.set_state("sleeping")
        if self.option == 2:
            heard = self.wake.listen_for_wake_word(stop_event=self._wake_event)
            self.vision.stop()  # paused during conversation; restarted when Aria sleeps
            return heard or self._wake_event.is_set()

        print("Press Enter (or type in the overlay) to wake Aria..." if HAS_TERMINAL
              else "Sleeping — type in the overlay to wake Aria...")
        while not self._wake_event.is_set():
            if stdin_ready() and read_stdin_line() is not None:
                return True
        return True  # vision triggered

    def run(self, option=None):
        if option is not None:
            self.option = option
        while True:
            self.vision.start()  # no-op if already running
            self._wake_event.clear()

            if not self._wait_for_wake():
                continue
            self.awake = True
            init, self._initiative_pending = self._initiative_pending, None

            if self.arduino:
                self.arduino.startup_animation()

            timeout = SLEEP_TIMEOUT
            if self.announcements.empty() and self.text_inputs.empty():
                # only greet when nothing is waiting — a reminder or a typed question goes first,
                # and generating a greeting nobody hears would just delay the answer
                if init:
                    self._open_initiative(init)
                    timeout = INITIATIVE_TIMEOUT
                else:
                    opening = self.llm.chat(self._greeting_prompt(), [], BASE_PROMPT)
                    print(f"Aria: {opening}")
                    self.speak(opening)

            last_interaction = time.time()
            pending_input = None
            prompted = False  # text mode: print the prompt only once per turn

            # ── Conversation loop ──────────────────────────────────────
            while True:
                if self._sleep_request.is_set():
                    self._go_to_sleep()
                    break

                if self._speak_announcements():
                    last_interaction = time.time()

                remaining = timeout - (time.time() - last_interaction)
                if remaining <= 0:
                    print("\n[Wake] Going back to sleep.")
                    # say it in voice mode; in text mode the orb dimming is enough
                    self._go_to_sleep("Going to sleep." if self.option == 2 else None)
                    break

                # ── Get input ──
                self.ui.set_state("listening")
                if pending_input:
                    user_input, pending_input = pending_input, None
                elif not self.text_inputs.empty():
                    user_input = self.text_inputs.get()
                elif self.option == 1:
                    if not prompted and HAS_TERMINAL:
                        print("You > ", end="", flush=True)
                        prompted = True
                    if not stdin_ready(0.25):
                        continue  # re-check the sleep timeout
                    user_input = read_stdin_line()
                    prompted = False
                else:
                    # short windows so typed input and sleep requests are noticed quickly
                    user_input = self.stt.listen(start_timeout=min(remaining, 3))
                    if user_input:
                        user_input = self._check_heard(user_input, self.stt.last_confidence)
                        if user_input is None:
                            last_interaction = time.time()
                            continue

                if not user_input:
                    continue

                print(f"You: {user_input}")
                self.ui.message("user", user_input)
                timeout = SLEEP_TIMEOUT

                if self._initiative_active and not self._initiative_active.get("answered"):
                    self._initiative_active["answered"] = True
                    if NOT_NOW_RE.match(user_input):
                        self.initiative.finished(self._initiative_active["kind"], True, snoozed=True)
                        self._initiative_active = None
                        self._go_to_sleep("Sure, later.")
                        break
                    if self._initiative_active["kind"] in ("chat", "break") and CHAT_BRUSH_OFF_RE.match(user_input):
                        self._initiative_active["answered"] = False   # counts like ignored: wait longer next time
                        self._go_to_sleep(random.choice(CHAT_LET_GO))
                        break

                if matches_phrase(SLEEP_PHRASES, user_input):
                    self._go_to_sleep("Alright, going to sleep.")
                    break

                if matches_phrase(SHUTDOWN_PHRASES, user_input):
                    self.speak("Shutting down.")
                    self._remember_session(blocking=True)  # finish before os._exit kills threads
                    self.shutdown()
                    return

                last_interaction = time.time()

                try:
                    response, used, interrupted = self._turn_and_speak(user_input)
                    last_interaction = time.time()
                    # she asked something: give Lala time to answer before dozing off
                    timeout = CHAT_TIMEOUT if response.rstrip().endswith("?") else SLEEP_TIMEOUT
                except Exception as e:
                    print(f"[Error] {e}")
                    self.speak("Something went wrong.")
                    continue

                if interrupted:
                    print(f"You (interrupted): {interrupted}")
                    pending_input = interrupted
                    last_interaction = time.time()
                    continue

                if any(name in MUSIC_TOOLS for name, _ in used):
                    # Music keeps playing, so end the session after one command
                    self._go_to_sleep()
                    break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aria desk assistant")
    parser.add_argument("--voice", action="store_true", help="wake word + speech input instead of keyboard")
    parser.add_argument("--no-ui", action="store_true", help="terminal only, no floating overlay")
    args = parser.parse_args()
    option = 2 if args.voice else 1

    from ui import instance
    if instance.send("show"):
        print("Aria is already running — opened her text box instead.")
        sys.exit(0)

    if args.no_ui:
        aria = Aria(option=option)
        instance.listen(lambda cmd: aria.shutdown() if cmd == "quit" else
                        aria.initiative.force(cmd) if cmd in ("chat", "review", "event", "followup", "break") else None)
        aria.run()
    else:
        from ui.overlay import run_with_overlay
        run_with_overlay(lambda bridge: Aria(option=option, ui=bridge))
