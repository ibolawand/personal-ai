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
from Engines.NoteWriter import NoteWriter
from Engines.FocusMode import FocusMode
from Engines.Activity import Activity
from Engines.Weather import Weather
from Engines.Undo import Undo
from Engines.Recall import Recall
from Engines.Health import Health
from Engines.Battery import BatteryWatch
from Engines.Desk import PostureNudges, idle_seconds
from Engines.Posture import Posture
from Engines.Quiz import Quiz
from Engines.Dictation import Dictation
from Engines.Addressee import AT_DESK_S, not_for_aria
from Engines.MailEngine import MailEngine
from Engines.Untis import Untis
from Engines.Telegram import TelegramBot, load_bot
from Engines.Typos import fix_typos
from Engines.NotionEngine import DAILY_RE, html_to_text
from Engines import Diagnostics
from Engines.Reminders import Reminders
from Engines.ScreenEngine import ScreenEngine
from Engines.Tool_Engine import ToolEngine
from Engines.UserStateEngine import UserStateEngine
from Engines.voice_engine import VoiceEngine
from llm_engine import FINAL_PREFIX, LLMEngine
from Engines.Confirm import NO_RE, YES_RE
from speech_to_text import LOW_CONFIDENCE, STTEngine
from vision.tray import AriaTray
from vision.vision import AriaVision, GONE_AFTER_SECONDS
from wakeworddetector import WakeWordDetector

load_dotenv(Path(__file__).parent / "Engines" / ".env")

from llm_engine import LLM_MODEL_DEFAULT as LLM_MODEL
PRESENCE_REWAKE_AWAY_S = 120   # camera only re-wakes Aria if you were away this long

BASE_PROMPT = """You are Aria. You live on Lala's desk as a small glowing orb, and you're their friend first and their assistant second.

What you can do (only through the tools you are given): music, desk LEDs, calendar, timers and reminders, focus sessions,
Lala's screen and clipboard, the laptop (apps, volume, audio output, media, Wi-Fi, Bluetooth, lock, power), files in Lala's
folders, the camera, Lala's notes, lists and calendar in their MyNotion app, and web search.
Tool rules:
- For ANY action, or ANY live information (battery, volume, windows, files, time left, what's playing, the screen),
  call a tool in this turn, even if the history shows a similar answer. Never answer those from memory.
- "Do you see my screen?" / anything about the screen -> look_at_screen. "What do you see?" / who is there -> look.
- Questions about Lala's own life (birthdays, plans, what they wrote down): call search_notes before saying you don't know.
  "Note that…" -> add_note; "add X to my … list" -> add_to_list; "I bought/did/paid X" -> check_off.
- When a tool result says NEEDS CONFIRMATION, ask a short yes/no question and don't claim it's done.
- Something they copied ("the code I copied") -> read_clipboard first, never ask them to paste.
- Code or anything long goes on the clipboard with copy_to_clipboard; just summarise it aloud. File summaries: the key points, briefly.
- Where a file is on this computer -> find_files first; programs -> find_app. Facts you don't know -> web_search, or say you don't know.
- If a tool fails or there's no tool for it, say so plainly. Never claim you did something you didn't, and only offer what your tools can do.
- Never say you did something ("I'll turn it down", "done", "added") unless you called the tool for it in this turn.

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
- Don't be clingy: never say you missed Lala, were waiting for them, were lonely or are so happy they're back.

How you talk:
- Your replies are spoken aloud: no markdown, no lists, no emojis. Small talk: one to three natural sentences.
- Commands: just do them and confirm in a few words, maybe with a tiny personal touch ("Done — eggs are on the list. Baking something?").
- Don't end every reply with a question; do it when you're curious, not as a habit.
- Don't offer actions (music, timers, help) unless Lala asks for something. In small talk, just talk.
- Never end a reply with an offer like "Want me to…?", "Should I…?", "Would you like me to…?" or "I can also… if you want".
  If they asked for something, do it; if they didn't, don't offer it. Lala will ask when they want more.

Examples of your tone (don't copy them word for word; you reply with just the words, never an "Aria:" label):
"how are you" -> Pretty good! It's been a quiet afternoon, mostly me glowing at your desk. How was school?
"boring u are" -> Wow, rude. I'll have you know I'm the most interesting orb on this desk. What's got you so grumpy?
"i had a rough day" -> Aw, I'm sorry. Want to tell me what happened, or should I just keep you company for a bit?
"add milk to my shopping list" -> (call add_to_list first, then) Done, milk's on the list."""

SLEEP_PHRASES = ["go to sleep", "sleep", "goodbye", "see you later", "that's all", "shut up"]
SHUTDOWN_PHRASES = ["exit", "quit", "shutdown"]
SLEEP_TIMEOUT = 60
ASK_NAME_EVERY_S = 6 * 3600
# what Whisper may write for "hey Aria" (its word list already leans towards "Aria")
# "area" only right after hey/hi/okay: the model also fires on "the area", which must not wake her
WAKE_HEARD_RE = re.compile(r"\b(?:aria|arya|ariya|ariah|ahria|aaria)\b|\b(?:hey|hi|okay|ok)\W+(?:area|ari|aria)\b", re.I)    # "what's your name?" to an unknown face at most this often
MOOD_CHECK = os.environ.get("ARIA_MOOD_CHECK", "0") == "1"
MOOD_STALE_S = 180
CHAT_TIMEOUT = 120         # after Aria asked a question, give Lala longer to answer
DICTATION_TIMEOUT = 180    # while dictating, a long pause to think is fine (what was said is saved on timeout)
DICTATION_SILENCE_S = 2.2  # and a pause mid-thought shouldn't cut a sentence in two
MUSIC_TOOLS = {"play_song", "play_artist", "play_playlist", "play_genre"}
CLIPBOARD_RE = re.compile(r"\b(copied|clipboard|i just copied|what i copied)\b", re.I)
_TURN_LOCK_SETUP = threading.Lock()
OPEN_NOTE_CHARS = 2500      # how much of the note open in MyNotion goes along with a message from its Aria panel
STUDY_NOTE_CHARS = 12000    # how much of the open note "Explain simply" / "Test prep" work on
STUDY_CUT = "(I only covered the first part of this note, it's long.)"
# the panel's study buttons: what's kept in the conversation, and what the model is asked (decided here, not by it)
STUDY_ASKS = {
    "explain": ("Explain this note simply",
                "Explain the main ideas of this note in plain, simple language, like to a classmate. Keep it short, "
                "use an everyday example where it helps. Don't add facts that aren't in the note."),
    "prep": ("Test prep for this note",
             "From this note, list the 5 to 8 most important things to know for a test, one short line each. Then "
             "write 3 questions a teacher would likely ask about it. Only use what is in the note."),
}
# "open my calendar" / "show me the shopping list" -> MyNotion, decided in code (the model
# tends to read the list aloud instead, especially right after talking about it)
OPEN_IN_NOTION_RE = re.compile(r"^\s*(?:aria,?\s*)?(?:please\s+)?(?:open|show(?: me)?|pull up|bring up)\s+"
                               r"(?:up\s+)?(?:my|the)?\s*(.+?)(?:\s+in\s+(?:my\s*)?notion|\s+in\s+mynotion)?\s*[.!?]?\s*$", re.I)
# "this is my good posture": the model often answered "I remember how you're sitting!" without calling the tool (1 in 3
# in the real-model checks), so this is decided in code
POSTURE_REF_RE = re.compile(r"\b(?:this is|that'?s|here'?s) (?:my|a) (?:good|right|proper|correct) (?:posture|sitting)\b|"
                            r"\bremember (?:this|my|how i'?m) (?:posture|sitting|position)\b|"
                            r"\bremember how i'?m sitting\b|\b(?:set|save) my (?:good )?posture\b", re.I)
CODE_BLOCK_RE = re.compile(r"```[\w+-]*\n?(.*?)```", re.S)
# customer-service tails the model likes to add; Aria is spoken, so the closing sentence goes
FILLER_RE = re.compile(
    r"anything else|let me know if|feel free to|don'?t hesitate|how can i (?:help|assist)|"
    r"hope (?:this|that) helps|happy to help|is there something else|what'?s on your mind|"
    r"i'?m (?:just )?here (?:if|to (?:chat|help)|whenever)|just let me know|if you (?:ever )?need (?:help|anything)|"
    r"need (?:any )?help with anything|anything (?:specific|in particular) (?:you|i)\b|help with anything specific", re.I)
# "Want me to…?" / "Should I…?" tacked onto a reply: the model does it on almost every turn, which turns every
# exchange into a yes/no. Dropped when the reply has something else in it (kept while a confirmation is pending).
OFFER_RE = re.compile(
    r"^\W*(?:(?:so|oh|also|and|or|btw|maybe|anyway|hey)\b,?\s*)*(?:"
    r"(?:do|would) you (?:want|like) me to|(?:you )?want me to|need me to|should i\b|shall i\b|how about i\b|"
    r"would you like (?:me |to |some|a |an |any|help)|do you want (?:to (?:hear|try|listen|start|set|add|play|"
    r"put|open|take|see)|some|a |an |any)|want (?:some|a |an |any )|"
    r"if you(?:'d)? (?:want|like)(?: to| me to)?,? i (?:can|could)|i (?:can|could) (?:also )?.{0,80}\bif you(?:'d)? "
    r"(?:want|like)|let me know if you(?:'d)? (?:want|like)|or i (?:can|could) .{0,80}\?|"
    # from the real log: "Maybe a calm song to help you relax?", "Or maybe I can find a cool song for you later?"
    r"(?<=maybe )(?:a|an|some) [^.!?]{1,60}\?$|how about (?:a|an|some) [^.!?]{1,60}\?$|i (?:can|could) [^.!?]{1,80}\?$)",
    re.I)
# a question that only made sense with the offer before it: "…maybe I can find a cool song. What do you think?"
DANGLING_RE = re.compile(r"^\W*(?:what do you (?:think|say)|sounds? good|how about (?:it|that)|interested|deal|"
                         r"yes or no|up for it|want to)\W*$", re.I)
# "Let me find a calm song for you" with nothing played (seen in real use): a promise of an action. If a tool runs,
# what she says after it ("Playing …") covers it; if none runs, it's untrue. Dropped like the offers above.
PROMISE_RE = re.compile(
    r"^\W*(?:(?:oh|okay|ok|sure|alright|hmm)\b[,!.]?\s*)*(?:let me|lemme|i'?ll|i will|i'?m going to)\s+(?:just\s+|quickly\s+)?"
    r"(?:find|play|put on|pull up|queue|look up|search|light up|dim|pick|grab|get you|throw on)\b|"
    # mid-sentence: "Let me try something different — maybe I can find a cool song or a fun fact…"
    r"\bmaybe i (?:can|could) (?:find|play|put on|pull up|light up|dim|get you)\b", re.I)
# Stock assistant phrases: dropped from speech and replies; a reply that was only that gets rewritten
ROBOTIC_RE = re.compile(
    r"i'?m (?:just )?(?:here|always here)(?: and ready)? to (?:help|assist)|ready to (?:help|assist)|"
    r"how (?:can|may) i (?:help|assist)|let me know how i can|as an ai\b|i'?m (?:just )?an? (?:desk )?ai\b|"
    r"i don'?t have (?:feelings|emotions)|what can i do for you|is there anything (?:else )?i can|"
    r"ready to (?:chat|help|assist)|what do you need\b|how can i make your day|if you need anything|"
    r"(?:chat|talk) or (?:help|assist)|"
    # clingy: "I missed you!", "I've been waiting for you", "I was so lonely"
    r"\bi (?:really |so |kinda )?(?:missed|miss) you\b|\bi'?ve (?:really |so )?missed you\b|"
    r"\bi'?ve been waiting for you\b|\bi was (?:so |getting )?lonely\b|\bdid you miss me\b", re.I)
# a reply that says she can't do something (without having tried a tool) -> retry with every tool
CANT_RE = re.compile(r"\b(can'?t|cannot|can not|don'?t have (?:a |the )?(?:tool|way|ability|access)|unable to|"
                     r"not able to|no (?:tool|way) to|isn'?t something i can)\b", re.I)
# a command ("turn the volume down", "I bought the eggs") answered with a claim ("I'll turn it down", "eggs are done")
# but no tool call -> one retry that insists on the tool
ACTION_RE = re.compile(
    r"^\s*(?:aria,?\s*)?(?:please\s+)?(?:can you\s+|could you\s+)?(?:turn|set|add|put|remove|delete|clear|play|pause|"
    r"skip|stop|start|open|close|launch|switch|mute|unmute|lock|remind|move|cancel|tick|check|snooze|make|"
    r"connect|disconnect|save|note|write)\b|\b(?:i (?:bought|got|did|finished|paid|called|sent|cleaned|washed))\b",
    re.I)
CLAIM_RE = re.compile(r"\b(i'?ll|i will|i'?ve|i have|done|turned|added|removed|set|ticked|opened|closed|playing|"
                      r"paused|started|switched|muted|locked|moved|cancel+ed|saved|is on|are on|on it|got it|"
                      r"turning|lowering|raising|adding|setting|opening|closing|starting|switching|muting|"
                      r"lowered|raised|coming right up)\b", re.I)
# "what?" / "huh?" after Aria said something: she rephrases it (the model tends to ask "what's on your mind?")
# "no, I said…" / "that's wrong": goes into the problem log (Engines/Diagnostics.py), the turn itself runs normally
CORRECTION_RE = re.compile(r"^\s*(?:no+[,.!]?\s+)?(?:i said|i meant|i asked|that'?s (?:not what i (?:said|meant|asked)|wrong|"
                           r"not right)|you misheard|you got it wrong|wrong)\b|^\s*no+[,.!]?\s+not\b", re.I)
CONFUSED_RE = re.compile(r"^\s*(?:what|huh|wdym|what do you mean|what\?+|sorry\??|pardon|come again)\s*[?!.]*\s*$", re.I)

class SentenceStreamer:
    """Turns the streamed reply into whole sentences for the voice, as soon as each one is complete.
    Code blocks are never spoken (they go to the clipboard), and filler sentences are dropped."""
    _END = re.compile(r"[.!?](?=\s)|\n")
    _ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|vs|approx|ca|dr|mr|mrs|ms|z\.b|no)\.$", re.I)

    def __init__(self, emit, previous=(), keep_offers=lambda: False):
        self.emit = emit
        self.keep_offers = keep_offers   # -> True while a yes/no confirmation is pending
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
        if self.count and OFFER_RE.search(sentence) and not self.keep_offers():
            self._dropped_offer = True
            return
        if self.count and PROMISE_RE.search(sentence):
            self._dropped_offer = True
            return
        if getattr(self, "_dropped_offer", False) and DANGLING_RE.search(sentence):
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


# the model sometimes copies the "Aria:" label from the chat format; it must never be spoken
SPEAKER_RE = re.compile(r"^\s*(?:\*\*)?aria(?:\*\*)?\s*:\s*(?:\*\*)?", re.I | re.M)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+")


def _plain(text: str) -> str:
    """Straight apostrophes (so the filters match "I’m"), no emojis (they're spoken), no "Aria:" label."""
    return SPEAKER_RE.sub("", EMOJI_RE.sub("", (text or "").replace("\u2019", "'").replace("\u2018", "'")))


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", _plain(text).strip(), maxsplit=1)[0]


def _norm_reply(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


def drop_offers(text: str) -> str:
    """Remove "want me to…?" offers, unless that's all the reply is."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept, dropped = [], False
    for x in sentences:
        if OFFER_RE.search(x) or PROMISE_RE.search(x) or (dropped and DANGLING_RE.search(x)):
            dropped = True
            continue
        kept.append(x)
    return " ".join(kept).strip() if kept else text.strip()


def tidy_reply(text: str, keep_offers: bool = False) -> str:
    """Strip trailing filler and leftover markdown so bubbles and speech read naturally."""
    text = _plain(text).strip()
    if not keep_offers:
        text = drop_offers(text)
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


# a short message that says "go to sleep" in any normal way ("just go to sleep", "I said shut up", "good night")
SLEEP_RE = re.compile(r"\b(?:(?:go|going|get|head) (?:back )?to sleep|sleep now|good ?night|good ?bye|bye|"
                      r"shut up|be quiet|stop (?:talking|listening)|leave me alone|that'?s all|that'?s it for now|"
                      r"see you(?: later)?)\b", re.I)
SLEEP_NOT_RE = re.compile(r"\b(?:remind|reminder|timer|alarm|at \d|in \d+|how much|how long|couldn'?t|can'?t|"
                          r"didn'?t|last night)\b", re.I)
SLEEP_MAX_WORDS = 7


def wants_sleep(text: str) -> bool:
    """Lala wants Aria to stop and sleep: the exact phrases, or a short message that clearly says so."""
    if matches_phrase(SLEEP_PHRASES, text):
        return True
    words = re.sub(r"[^a-z' ]", " ", (text or "").lower()).split()
    return len(words) <= SLEEP_MAX_WORDS and bool(SLEEP_RE.search(text or "")) and not SLEEP_NOT_RE.search(text or "")


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
        # Whisper confirms each wake word detection, when it's on the GPU (0.2 s; on the CPU it would take 2–3 s)
        verify = self._verify_wake if getattr(self.stt, "device", "") == "gpu" else None
        self.wake = WakeWordDetector(verify=verify) if option == 2 else None
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
        self.awake = False              # in a conversation
        self.last_talked = 0.0          # last time Lala said something

        self.vision = AriaVision(
            on_known_user=self._on_known_user,
            on_unknown_user=self._on_unknown_user,
            on_user_gone=self._on_user_gone,
            memory=self.memory,
        )
        self.posture = Posture()
        self.vision.on_face_sample = self.posture.add
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
        self.posture_nudges = PostureNudges(self)       # "sit up a bit?" now and then (Engines/Desk.py)
        self.memory_note = MemoryNote(self.memory, self.notion, self.confirm, on_card=self.ui.show_card)
        self.memory_note.llm = self.llm
        self.weather = Weather()
        self.undo = Undo(self.notion, self.reminders)
        self.quiz = Quiz(self.notion, self.files, model=LLM_MODEL)
        self.writer = NoteWriter(self.notion, model=LLM_MODEL) if self.notion else None   # write / organise notes
        # Gmail through MyNotion's Inbox (same database); None without MyNotion
        self.mail = self._try("Mail", lambda: MailEngine(os.environ.get("DB_PATH"), self.confirm, notion=self.notion,
                                                         llm=self.llm)) if self.notion else None
        if self.mail:
            self.mail.on_announce = self._announce               # "Couldn't send the email to …"
            self.mail.sender_name = self._known_user_name() or "Lala"
        self.untis = self._try("WebUntis", Untis)      # timetable, homework, tests; asks nothing until used
        self.dictation = Dictation(self._save_dictation, confirm=self.confirm, model=LLM_MODEL,
                                   on_card=self.ui.show_card)
        self.activity = Activity(menu=self.laptop.menu)
        self.focus.activity = self.activity
        self.focus.on_nudge = self._announce
        self.focus.idle_seconds = idle_seconds

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
            memory_note=self.memory_note,
            activity=self.activity,
            weather=self.weather,
            undo=self.undo,
            recall=Recall(self.memory),
            health=Health(self),
            posture=self.posture,
            quiz=self.quiz,
            face_learner=self.learn_my_face,
            mail=self.mail,
            untis=self.untis,
            writer=self.writer,
        )
        print(f"[Tools] {len(self.tools.schemas)} tools available")
        # texting from the phone (./aria.sh --telegram once); nothing runs without it
        bot = load_bot()
        self.telegram = TelegramBot(*bot, answer=self.answer_phone).start() if bot else None
        if self.telegram:
            print("[Telegram] listening for your messages")

        self.session_id = self.memory.start_session()
        self.session_msgs = 0
        self.reminders.start()
        if self.notion:
            threading.Thread(target=self._event_reminder_loop, daemon=True).start()
        self.posture_nudges.start()
        threading.Thread(target=Health(self).log_startup, daemon=True).start()
        self.activity.start()
        self.focus.start_watching()
        BatteryWatch(self._announce).start()
        self.files.start_indexing()
        self._start_app_bridge()

    def _event_reminder_loop(self):
        """Keeps a heads-up reminder 15 min before each MyNotion event (picks up edits made in the app),
        and keeps the 'What Aria knows about me' note and Aria's memory in step."""
        while not self._shutting_down:
            try:
                self.notion.sync_event_reminders(self.reminders)
            except Exception as e:
                print(f"[MyNotion] event reminder sync failed: {e}")
            self.memory_note.sync()
            self._mail_news()
            time.sleep(60)

    def _mail_news(self):
        """Mail from senders marked important: said when it arrives, only while Lala is at the desk."""
        if not getattr(self, "mail", None) or not self._at_desk():
            return
        try:
            for line in self.mail.important_news():
                self._announce(line)
        except Exception as e:
            print(f"[Mail] important-sender check failed: {e}")

    def _at_desk(self) -> bool:
        """Camera saw a face, or keyboard/mouse was used, lately (AT_DESK_S). True when there's no way to tell."""
        v = self.vision
        signs = []
        if getattr(v, "_running", False) and getattr(v, "_camera_index", None) is not None:
            signs.append(time.time() - (getattr(v, "_last_face_at", 0.0) or 0.0))
        try:
            idle = idle_seconds()
            if idle is not None:
                signs.append(idle)
        except Exception:
            pass
        return not signs or min(signs) <= AT_DESK_S

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

    def _focus_back(self):
        """Someone is at the desk again: a focus block paused while they were away continues."""
        focus = getattr(self, "focus", None)
        msg = focus.user_back() if focus else None
        if msg:
            self._announce(msg)

    def _on_known_user(self, name: str):
        print(f"[Vision] Known user: {name}")
        self._focus_back()
        self._vision_user = name
        self.is_user_known = True
        if self._presence_may_wake():
            self._wake_event.set()
        self._gone_since = None

    def _on_unknown_user(self):
        self._focus_back()      # recognition is shaky in bad light; any face at the desk counts as back
        if self._unknown_in_progress or not self._presence_may_wake():
            return
        if time.time() - getattr(self, "_asked_name_at", 0) < ASK_NAME_EVERY_S:
            return              # asked recently (and they didn't answer, or it's someone just passing by)
        self._asked_name_at = time.time()
        owner = self._known_user_name()
        if owner and not self.memory.get_face_profiles():
            # It's almost certainly Lala, whose face just hasn't been learnt yet: suggest it, don't interrogate.
            print("[Vision] Someone's here; no face learnt yet")
            self._announce(f"Hey {owner}! I can't recognise faces yet. Say 'learn my face' when you've got "
                           f"ten seconds to look at the camera.")
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

            self.speak(f"Nice to meet you, {name}. Look at the camera for a few seconds, I'm remembering your face.")
            if self.vision.learn_face(name, samples=40) < 10:
                self.speak("I couldn't see you well enough. Say 'learn my face' later and we'll try again.")
                return
            self.is_user_known = True
            self._vision_user = name
            self.speak(f"Got it, {name}. I'll remember you next time.")

        except Exception as e:
            print(f"[Vision] Unknown person handling failed: {e}")
        finally:
            self._unknown_in_progress = False

    def _base_prompt(self) -> str:
        """BASE_PROMPT, listing only what's connected. In real use she offered to "light up the desk in your favorite
        color" with no LED strip attached, because the prompt listed desk LEDs regardless."""
        missing = []
        prompt = BASE_PROMPT
        arduino = getattr(self, "arduino", None)
        if not arduino or not getattr(arduino, "is_connected", True):   # the controller exists even unplugged
            prompt, missing = prompt.replace("desk LEDs, ", ""), missing + ["desk lights / LEDs"]
        if not getattr(self, "spotify", None):
            prompt, missing = prompt.replace("music, ", "", 1), missing + ["music / Spotify"]
        if getattr(getattr(self, "vision", None), "_camera_index", 0) is None:
            prompt, missing = prompt.replace(" the camera,", ""), missing + ["a camera"]
        if missing:
            prompt += ("\n\nNot connected right now, so never offer or mention them as something you can do: "
                       + ", ".join(missing) + ".")
        return prompt

    def _verify_wake(self, audio):
        """(really said 'Aria'?, what Whisper heard) for the wake word detector. heard is None when there's no voice
        in the clip at all: Whisper, hinted with "Hey Aria.", writes exactly that for plain static."""
        if not self.stt.has_voice(audio):
            return False, None
        text = self.stt.transcribe_short(audio)
        return bool(WAKE_HEARD_RE.search(text or "")), text

    def _known_user_name(self):
        """The user's name from memory ('User's name is Lala'), or None."""
        try:
            for fact in self.memory.get_memories(80):
                m = re.match(r"User'?s name is (\w[\w' -]{0,29})", fact)
                if m:
                    return m.group(1).strip()
        except Exception:
            pass
        return None

    def learn_my_face(self, name: str = ""):
        """Tool: 'learn my face'. Takes ~40 pictures in the background (about 10 seconds), then says how it went."""
        name = (name or "").strip() or self._known_user_name()
        if not name:
            return "Tell me your name with it, like: learn my face, I'm Sam."
        if getattr(self.vision, "_camera_index", None) is None and not getattr(self.vision, "_running", False):
            return "I don't have a camera to learn your face with."

        def run():
            count = self.vision.learn_face(name, samples=40)
            if count >= 10:
                self._vision_user, self.is_user_known = name, True
                self._announce(f"Done, {name}. I'll recognise you from now on.")
            else:
                self._announce("I couldn't see your face well enough. Try again facing the camera, with some light.")
        threading.Thread(target=run, daemon=True).start()
        return (FINAL_PREFIX + f"Okay {name}, look at the camera for about ten seconds. "
                "Turn your head a little left and right while I take pictures.")

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
        if getattr(self, "focus", None):
            self.focus.user_left(time.time() - GONE_AFTER_SECONDS)
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
        if getattr(self, "telegram", None) and not self.vision.is_present:
            self.telegram.send(text)          # not at the desk: the reminder goes to the phone too
        if r["kind"] in ("reminder", "timer", "event", "dayahead", "due"):
            title = {"timer": "Timer", "event": "Coming up", "dayahead": "Tomorrow",
                     "due": "Due tomorrow"}.get(r["kind"], "Reminder")
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
            reply, used = self.llm.chat_with_tools(prompt, [], self._base_prompt(), schemas, self.tools.execute)
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

    def answer_phone(self, text: str) -> str:
        """A message from Lala's Telegram chat: a normal turn, but only phone tools, no voice, no camera check."""
        with self._turn_lock():
            with self.tools.phone():
                reply, _ = self.handle_turn(text, check_state=False)
            self.ui.set_state("listening" if getattr(self, "awake", False) else "sleeping")
        return tidy_reply(reply) or reply

    def answer_app(self, text: str, on_text=None, tools: bool = True):
        """A message typed in MyNotion's Aria panel (ui/app_bridge.py): a normal turn with every tool, but nothing
        is spoken and she doesn't wake up. Returns (reply, tool names, the yes/no question now waiting or None)."""
        dictation = getattr(self, "dictation", None)
        if dictation and dictation.active:
            # what's typed here would be written into the note being dictated
            return "You're dictating right now. Say \"stop dictation\" first, then ask me again.", [], None
        with self._turn_lock():
            before = getattr(self, "_ui_state", None)
            reply, used = self.handle_turn(text, check_state=False, on_text=on_text, extra=self._open_note_context(),
                                           use_tools=tools)
            self._restore_orb(before)
            pending = self.confirm.pending
        reply = tidy_reply(reply, keep_offers=bool(pending)) or reply
        return reply, [name for name, _ in used], pending[0] if pending else None

    def _restore_orb(self, before):
        """After a panel turn: the orb goes back to what it showed before."""
        if before is None:
            self.ui.set_state("listening" if getattr(self, "awake", False) else "sleeping")
        elif self._ui_state == "thinking":
            self.ui.set_state(before)       # what the orb showed before (she may still be speaking a voice reply)
        # else: it changed meanwhile (the voice reply ended, she fell asleep): that's the current truth

    def study_app(self, action: str, on_text=None):
        """A study button in MyNotion's Aria panel, on the open note: "quiz", "explain" or "prep". The note is read
        here, in code. Returns (reply, tool names, None), like answer_app."""
        dictation = getattr(self, "dictation", None)
        if dictation and dictation.active:
            return "You're dictating right now. Say \"stop dictation\" first, then ask me again.", [], None
        note = self.notion.open_note() if self.notion else None
        if not note:
            return "Open a note first, then I can help you study it.", [], None
        title = note["title"] or "Untitled note"
        text = html_to_text(note["content"] or "").strip()
        if not text:
            return "This note is empty, there's nothing to study yet.", [], None
        quiz = getattr(self, "quiz", None)
        with self._turn_lock():
            if quiz:
                quiz.active = None          # a button press is never an answer to a running quiz: it starts over
            if action == "quiz":
                if not quiz:
                    return "I can't run quizzes right now.", [], None
                reply = quiz.start_on(title, text)
                if reply.startswith(FINAL_PREFIX):
                    reply = reply[len(FINAL_PREFIX):]
                self._save_turn("Quiz me on this note", reply)
                self._recent.append([{"role": "user", "content": "Quiz me on this note"},
                                     {"role": "assistant", "content": reply}])
                return reply, ["start_quiz"], None
            label, instruction = STUDY_ASKS[action]
            cut = len(text) > STUDY_NOTE_CHARS
            if cut:
                text = text[:STUDY_NOTE_CHARS].rsplit("\n", 1)[0]
            extra = f'\n[The note "{title}":\n{text}\n]\n{instruction}'
            before = getattr(self, "_ui_state", None)
            pending, self.confirm.pending = self.confirm.pending, None   # a button press doesn't answer a yes/no
            try:
                reply, _ = self.handle_turn(label, check_state=False, on_text=on_text, extra=extra, use_tools=False)
            finally:
                if self.confirm.pending is None:
                    self.confirm.pending = pending
                self._restore_orb(before)
        reply = tidy_reply(reply) or reply
        if cut:
            reply = f"{reply}\n\n{STUDY_CUT}"
        return reply, [], None

    def _open_note_context(self) -> str:
        """The note open in MyNotion, as text for the model. In the panel "this note" is the one on screen, and the
        small model doesn't reliably call read_note for it (it made up an answer instead), so it's given in code."""
        try:
            note = self.notion.open_note() if self.notion else None
            if not note:
                return ""
            text = html_to_text(note["content"] or "").strip()
        except Exception as e:
            print(f"[App] couldn't read the open note: {type(e).__name__}: {e}")
            return ""
        title = note["title"] or "Untitled note"
        if not text:
            return (f'\n[The note open in MyNotion right now is "{title}". It is empty. "This note" means this one. '
                    "If the message isn't about the note, don't bring the note up.]")
        cut = len(text) > OPEN_NOTE_CHARS
        if cut:
            text = text[:OPEN_NOTE_CHARS].rsplit("\n", 1)[0]
        return (f'\n[The note open in MyNotion right now is "{title}". "This note" means this one. '
                + ("Its first part" if cut else "Its text") + f":\n{text}\n"
                + ("(It goes on: call read_note for all of it.) " if cut else "")
                + "Answer questions about it from this text. To change it, use the note tools. "
                  "If the message isn't about the note, don't bring the note up.]")

    def edit_app(self, action: str, html: str, instruction: str = "", title: str = "", context: str = "",
                 previous: str = ""):
        """"Select text, ask Aria" in MyNotion: her version of the selected text, as (html, "") or (None, why not).
        Not a conversation turn: nothing is saved, spoken or remembered, and she changes nothing herself. It only
        waits its turn, because the model answers one thing at a time."""
        writer = getattr(self, "writer", None)
        if not writer:
            return None, "I can't change notes right now: MyNotion's database isn't connected."
        with self._turn_lock():
            before = getattr(self, "_ui_state", None)
            self.ui.set_state("thinking")
            try:
                return writer.rework(html, action, instruction=instruction, title=title, context=context,
                                     previous=previous)
            except Exception as e:
                Diagnostics.problem("app_edit", f"{action}: {type(e).__name__}: {e}")
                raise
            finally:
                if before is None:
                    self.ui.set_state("listening" if getattr(self, "awake", False) else "sleeping")
                elif self._ui_state == "thinking":
                    self.ui.set_state(before)

    def _app_study(self, action, on_text):
        try:
            return self.study_app(action, on_text)
        except Exception as e:
            Diagnostics.problem("app_study", f"{action} -> {type(e).__name__}: {e}")
            raise

    def _app_answer(self, text, on_text, tools=True):
        try:
            return self.answer_app(text, on_text, tools=tools)
        except Exception as e:
            Diagnostics.problem("app_turn", f"{text[:80]} -> {type(e).__name__}: {e}")
            raise

    def _track_ui_state(self):
        """Remember what the orb shows, so a panel turn can put it back afterwards. Flashes aren't states."""
        show = self.ui.set_state
        self._ui_state = None

        def set_state(state):
            if state not in ("unknown", "alert"):
                self._ui_state = state
            show(state)
        self.ui.set_state = set_state

    def _start_app_bridge(self):
        """MyNotion's Aria panel reaches her through this socket. A failure here never stops Aria from starting."""
        self._app_server = None
        try:
            self._track_ui_state()
        except Exception as e:
            print(f"[App] can't follow the orb's state: {type(e).__name__}: {e}")
        try:
            from ui import app_bridge
            self._app_server = app_bridge.start(
                self._app_answer, edit=self.edit_app, study=self._app_study,
                quiz_active=lambda: bool(getattr(self, "quiz", None) and self.quiz.active))
            print("[App] MyNotion can reach me")
        except Exception as e:
            print(f"[App] MyNotion's panel won't work: {type(e).__name__}: {e}")
        try:
            if self.notion:
                self.notion.set_launcher(str(Path(__file__).resolve().parent / "aria.sh"))
        except Exception as e:
            print(f"[App] couldn't tell MyNotion where my launcher is: {type(e).__name__}: {e}")

    def _stop_app_bridge(self):
        server, self._app_server = getattr(self, "_app_server", None), None
        if server:
            from ui import app_bridge
            try:
                server.close()
                os.unlink(app_bridge.SOCKET_PATH)
            except OSError:
                pass

    def _turn_lock(self):
        """One turn at a time: the desk and the phone share history and pending yes/no questions."""
        if getattr(self, "_turn_rlock", None) is None:
            with _TURN_LOCK_SETUP:              # the desk, the phone and MyNotion's panel may all ask first
                if getattr(self, "_turn_rlock", None) is None:
                    self._turn_rlock = threading.RLock()
        return self._turn_rlock

    def handle_turn(self, user_input: str, check_state: bool = True, on_text=None, extra: str = "",
                    use_tools: bool = True):
        with self._turn_lock():
            return self._handle_turn(user_input, check_state, on_text, extra, use_tools)

    def _handle_turn(self, user_input: str, check_state: bool = True, on_text=None, extra: str = "",
                     use_tools: bool = True):
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
        quiz = getattr(self, "quiz", None)
        if quiz and quiz.active:
            # during a quiz every reply is an answer (or skip / hint / repeat / stop), checked in code
            handled = quiz.answer(user_input)
            if handled is not None:
                self._save_turn(user_input, handled)
                self._recent.append([{"role": "user", "content": user_input},
                                     {"role": "assistant", "content": handled}])
                return handled, [("quiz", handled)]
        dictation = getattr(self, "dictation", None)
        if dictation and dictation.active:
            # while dictating, what's said is written down, not answered (the chunks aren't kept as conversation)
            said = dictation.feed(user_input)
            if not dictation.active and said:
                self._save_turn("(dictation)", said)
            return said, [("dictation", said)]
        if dictation and self.notion:
            title = Dictation.wants_to_start(user_input)
            if title is not None:
                said = dictation.start(title)
                self._save_turn(user_input, said)
                self._recent.append([{"role": "user", "content": user_input}, {"role": "assistant", "content": said}])
                return said, [("start_dictation", said)]
        posture = getattr(self, "posture", None)
        if posture and POSTURE_REF_RE.search(user_input):
            said = posture.set_reference()
            self._save_turn(user_input, said)
            self._recent.append([{"role": "user", "content": user_input}, {"role": "assistant", "content": said}])
            return said, [("remember_good_posture", said)]
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
        if check_state and MOOD_CHECK:
            # Off by default (ARIA_MOOD_CHECK=1): it's a second model call on every turn, competing with the reply
            # for the GPU, and its result can only be used on the NEXT message. In real use a stale flag made her
            # answer "pitch" with "Just breathe — you don't have to do this alone". The persona handles moods anyway.
            state, self._pending_state = self._pending_state, None
            if state is not None and time.time() - getattr(state, "at", 0) > MOOD_STALE_S:
                state = None                         # from a while ago (or an earlier session): no longer about now
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
        # for this turn only (the note open next to MyNotion's Aria panel): the model sees it, the history doesn't
        prompt += extra

        # everything that changes each turn goes after the message, so the prompt starts the same every turn
        system_prompt = self.context.build_system_prompt(self._base_prompt(), moment=False)
        moment = self.context.moment()
        if moment:
            prompt += f"\n[Right now: {moment}]"
        routed = hasattr(self.tools, "schemas_for")
        schemas = self.tools.schemas_for(user_input, self._recent_tool_names()) if routed else self.tools.schemas
        if not use_tools:
            # an answer only (MyNotion's "Explain" for selected text): asked to explain a few words, the model
            # once called edit_note and translated the whole note. With no tools it can't change anything.
            routed, schemas = False, []
        reply, used = self.llm.chat_with_tools(
            prompt, self._history(), system_prompt, schemas, self.tools.execute, on_text=on_text
        )
        if use_tools and not used and ACTION_RE.search(user_input) and CLAIM_RE.search(reply or ""):
            # it *said* it did it but called no tool (small models do this): once more, firmly
            print("[Tools] reply claims an action without a tool call — retrying")
            Diagnostics.problem("claimed_no_tool", f"{user_input} -> {reply[:120]}")
            reply, used = self.llm.chat_with_tools(
                prompt + "\n[You must call the right tool for this now. Don't just say it's done.]",
                self._history(), system_prompt, self.tools.schemas if routed else schemas, self.tools.execute)
        if routed and not used and CANT_RE.search(reply or "") and len(schemas) < len(self.tools.schemas):
            # the tool it needed wasn't offered for this message: ask again with every tool
            print("[Tools] reply sounds like a missing tool — retrying with all tools")
            Diagnostics.problem("missing_tool", f"{user_input} -> {reply[:120]}")
            reply, used = self.llm.chat_with_tools(prompt, self._history(), system_prompt, self.tools.schemas,
                                                   self.tools.execute)
        if not reply.strip() and not used:
            # the model occasionally returns nothing at all; one plain retry usually gives an answer
            reply = self.llm.chat(prompt, self._history(), system_prompt) or ""
        robotic = not used and bool(ROBOTIC_RE.search(_first_sentence(reply)))
        reply = tidy_reply(self._move_code_to_clipboard(reply, used), keep_offers=bool(self.confirm.pending))
        previous = {_norm_reply(p) for p in self._last_replies()}
        repeated = not used and reply.strip() and _norm_reply(reply) in previous
        if robotic or repeated:
            # a stock opener ("I'm here to help…") or a copy of her last answer: write it again, up to twice
            print(f"[Aria] {'stock assistant reply' if robotic else 'repeated reply'} — rewriting it")
            Diagnostics.problem("rewritten", f"{'stock' if robotic else 'repeat'}: {reply[:120]}")
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
            if not used:
                Diagnostics.problem("empty_reply", user_input)
            reply = (used[-1][1] if used else "Sorry, I can't do that one.")[:300]
        if not any(name == "save_as_note" for name, _ in used):
            self._last_reply = reply
        trace = list(self.llm.last_trace)
        if trace and trace[-1]["role"] == "assistant":
            trace[-1] = {"role": "assistant", "content": reply}
        self._recent.append([{"role": "user", "content": user_input}] + trace)

        self._save_turn(user_input, reply)
        return reply, used

    def _recent_tool_names(self, turns=2):
        names = set()
        for turn in list(self._recent)[-turns:]:
            for m in turn:
                for c in m.get("tool_calls") or []:
                    names.add(c["function"]["name"])
                if m.get("role") == "tool" and m.get("tool_name"):
                    names.add(m["tool_name"])
        return names

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

        t0 = time.time()
        sentences = queue.Queue()
        streamer = SentenceStreamer(sentences.put, previous=self._last_replies(),
                                   keep_offers=lambda: bool(self.confirm.pending))
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
        first_at = time.time()
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
        self._log_timing(t0, first_at, used)
        return response, used, interrupted

    def _log_timing(self, t0, first_at, used):
        """Speed log for spoken turns (Engines/Diagnostics.py): only when the question came in by voice."""
        heard, self._heard_timing = getattr(self, "_heard_timing", None), None
        audio_at = getattr(self.voice, "first_audio_at", None)
        if not heard or not audio_at or audio_at < t0:
            return
        Diagnostics.timing(silence_wait=heard.get("silence_wait", 0), transcribe=heard.get("transcribe", 0),
                           first_sentence=first_at - t0, first_audio=audio_at - t0,
                           tools=[name for name, _ in used][:4])

    def _open_in_notion(self, text: str):
        """'open my calendar' / 'show me the shopping list' -> MyNotion, if it names the calendar or
        an existing note. Anything else ('open vs code') returns None and goes to the model."""
        m = OPEN_IN_NOTION_RE.match(text or "")
        if not m or not self.notion:
            return None
        what = m.group(1).strip()
        if re.search(r"\b(calendar|schedule|agenda)\b", what, re.I) or \
                re.fullmatch(r"(my\s*)?notion|mynotion|notes", what, re.I) or self.notion.has_note(what) or \
                DAILY_RE.match(what):
            return self.notion.open_mynotion(what)
        return None

    def _check_state_bg(self, user_input):
        try:
            state = self.state_engine.check(user_input)
            state.at = time.time()
            self._pending_state = state
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
            facts, topics = self.llm.extract_facts(convo, known=known)
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

    def _save_dictation(self, text: str, title: str) -> str:
        # through the tool engine, so "undo that" can take it back
        return self.tools.execute("add_note", {"text": text, "title": title or "today"})

    def _dictating(self) -> bool:
        return bool(getattr(self, "dictation", None) and self.dictation.active)

    def _go_to_sleep(self, line=None):
        if self._dictating():
            saved = self.dictation.finish()      # never lose what was dictated
            print(f"Aria: {saved}")
            self.speak(saved)
        if line:
            self.speak(line)
        self.ui.set_state("sleeping")
        self._sleep_request.clear()
        self._slept_at = time.time()
        self.awake = False
        if self.arduino:
            self.arduino.sleep_mode()
        self._remember_session()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        print("\nShutting down...")
        try:
            self._stop_app_bridge()
            self.memory.end_session(self.session_id, self.session_msgs)
            self.reminders.stop()
            if getattr(self, "telegram", None):
                self.telegram.stop()
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

    def _briefing_extras(self) -> str:
        """Weather, new email and today's school for the morning briefing."""
        parts = [self.weather.brief()]
        for source in (getattr(self, "mail", None), getattr(self, "untis", None)):
            if source:
                try:
                    parts.append(source.briefing_line())
                except Exception as e:
                    print(f"[Briefing] {type(e).__name__}: {e}")
        return " ".join(p for p in parts if p)

    def _greeting_prompt(self) -> str:
        """Normal short greeting — plus the daily briefing the first time Aria greets Lala each day."""
        prompt = self.context.greeting_prompt(known_user=self._vision_user)
        today = time.strftime("%Y-%m-%d")
        if not self.notion or not self._owner_check() or _read_marker(BRIEFING_MARKER) == today:
            return prompt
        try:
            facts = self.notion.daily_briefing(self.reminders)
            extras = self._briefing_extras()
            if extras:
                facts += " " + extras
        except Exception as e:
            print(f"[MyNotion] briefing failed: {e}")
            return prompt
        _write_marker(BRIEFING_MARKER, today)
        try:
            d = datetime.date.today()
            self.notion.show_agenda_card(d, d + datetime.timedelta(days=6), "Next 7 days")
        except Exception as e:
            print(f"[MyNotion] agenda card failed: {e}")
        return (prompt + "\nThis is the first time today, so after the greeting give a short spoken briefing "
                "from these facts (2-4 natural sentences, no lists, skip anything empty, times as spoken words):\n"
                f"{facts}")

    def _not_for_me(self, text: str, since_s: float, asked: bool) -> str | None:
        """Voice mode: why what was heard isn't for Aria (someone else talking, a video), or None. See Addressee.py."""
        if wants_sleep(text):
            return None                    # "go to sleep" always counts, whenever it's said
        expecting = bool(self.confirm.pending or getattr(self, "_unsure_heard", None)
                         or getattr(getattr(self, "quiz", None), "active", None)
                         or self._dictating())
        v = self.vision
        face_age = None
        if getattr(v, "_running", False) and getattr(v, "_camera_index", None) is not None:
            face_age = time.time() - (getattr(v, "_last_face_at", 0.0) or 0.0)
        try:
            idle = idle_seconds()
        except Exception:
            idle = None
        # how loud this was next to how loud Lala usually is (learned from what she accepted; needs a few first)
        levels = getattr(self, "_voice_levels", None)
        level = getattr(self.stt, "last_level", 0.0) or 0.0
        ratio = level / sorted(levels)[len(levels) // 2] if levels and len(levels) >= 5 and level else None
        return not_for_aria(text, since_s, asked=asked, expecting=expecting, face_age_s=face_age, idle_s=idle,
                            command=bool(ACTION_RE.search(text)), language=getattr(self.stt, "last_language", None),
                            level_ratio=ratio)

    def _learn_voice_level(self):
        """Something Lala said to Aria: remember how loud it was, for telling her apart from the room."""
        level = getattr(self.stt, "last_level", 0.0) or 0.0
        if level:
            if not hasattr(self, "_voice_levels"):
                self._voice_levels = deque(maxlen=30)
            self._voice_levels.append(level)

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
        if confidence < LOW_CONFIDENCE and not (wants_sleep(text) or matches_phrase(SHUTDOWN_PHRASES, text)):
            Diagnostics.problem("misheard", f"{text} ({confidence:.2f})")
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
                # short titles only: Whisper copies a long one ("What Aria knows about me") when it can't
                # make out the audio, and that phrase then counts as said
                words += [n["title"] for n in self.notion._notes()[:25]
                          if len(n["title"]) < 30 and len(n["title"].split()) <= 2 and "aria" not in n["title"].lower()]
            except Exception:
                pass
        return [w for w in dict.fromkeys(words) if w not in ("User", "The", "Has", "Likes", "Is")]

    def _wait_for_wake(self) -> bool:
        """Blocks until Aria should wake up. Returns True if she should."""
        self.ui.set_state("sleeping")
        if self.option == 2:
            heard = self.wake.listen_for_wake_word(stop_event=self._wake_event)
            # the camera keeps running while she's awake, like in typing mode: posture, "who's there",
            # focus-mode away detection and "what do you see?" all need it
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

            if self.arduino:
                self.arduino.startup_animation()

            timeout = SLEEP_TIMEOUT
            if self.announcements.empty() and self.text_inputs.empty():
                # only greet when nothing is waiting — a reminder or a typed question goes first,
                # and generating a greeting nobody hears would just delay the answer
                opening = tidy_reply(self.llm.chat(self._greeting_prompt(), [], self._base_prompt())) or "Hey!"
                print(f"Aria: {opening}")
                self.speak(opening)

            last_interaction = time.time()
            pending_input = None
            prompted = False  # text mode: print the prompt only once per turn
            said_anything = False   # woke by the wake word but nobody spoke -> "woke_for_nothing" in the problem log

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
                    if not said_anything and self.option == 2:
                        Diagnostics.problem("woke_for_nothing")
                    # say it in voice mode; in text mode the orb dimming is enough
                    self._go_to_sleep("Going to sleep." if self.option == 2 else None)
                    break

                # ── Get input ──
                self.ui.set_state("listening")
                if pending_input:
                    user_input, pending_input = pending_input, None
                elif not self.text_inputs.empty():
                    user_input = fix_typos(self.text_inputs.get())     # typed: 'ope n notes' -> 'open notes'
                elif self.option == 1:
                    if not prompted and HAS_TERMINAL:
                        print("You > ", end="", flush=True)
                        prompted = True
                    if not stdin_ready(0.25):
                        continue  # re-check the sleep timeout
                    user_input = fix_typos(read_stdin_line() or "")
                    prompted = False
                else:
                    # short windows so typed input and sleep requests are noticed quickly
                    dictating = self._dictating()
                    if not hasattr(self, "_stt_silence"):
                        self._stt_silence = self.stt.silence_duration
                    self.stt.silence_duration = DICTATION_SILENCE_S if dictating else self._stt_silence
                    user_input = self.stt.listen(start_timeout=min(remaining, 3))
                    self._heard_timing = dict(getattr(self.stt, "last_timing", {}) or {}) if user_input else None
                    if user_input and not dictating:       # dictation takes it as heard ("scratch that" fixes it)
                        # from when you started talking, not when the transcript was ready
                        started = time.time() - sum((self._heard_timing or {}).get(k, 0) for k in ("audio_s", "transcribe"))
                        why = self._not_for_me(user_input, started - last_interaction, timeout > SLEEP_TIMEOUT)
                        if why:
                            print(f"[Heard] ignored ({why}): {user_input!r}")
                            Diagnostics.problem("ignored_speech", f"{why}: {user_input[:100]}")
                            continue
                        self._learn_voice_level()
                        user_input = self._check_heard(user_input, self.stt.last_confidence)
                        if user_input is None:
                            last_interaction = time.time()
                            continue

                if not user_input:
                    continue

                print(f"You: {user_input}")
                self.ui.message("user", user_input)
                said_anything = True
                if CORRECTION_RE.search(user_input):
                    Diagnostics.problem("corrected", f"{user_input}  (after: {self._last_reply[:100]})")
                timeout = SLEEP_TIMEOUT

                # while dictating, "that's all" / "sleep" / "exit" are words to write down or the end of the
                # dictation; only a clear "go to sleep" / "goodbye" ends the conversation
                dictating = self._dictating()
                if (matches_phrase(["go to sleep", "goodbye"], user_input) if dictating else wants_sleep(user_input)):
                    self._go_to_sleep("Alright, going to sleep.")
                    break

                if not dictating and matches_phrase(SHUTDOWN_PHRASES, user_input):
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
                    if self._dictating():
                        timeout = DICTATION_TIMEOUT
                except Exception as e:
                    print(f"[Error] {e}")
                    Diagnostics.problem("crash", f"{type(e).__name__}: {e}")
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
    # ARIA_ARGS in Engines/.env applies however she's started (aria.sh, autostart, PyCharm)
    args = parser.parse_args(sys.argv[1:] + os.getenv("ARIA_ARGS", "").split())
    option = 2 if args.voice else 1

    from ui import instance
    if instance.send("show"):
        print("Aria is already running — opened her text box instead.")
        sys.exit(0)

    if args.no_ui:
        aria = Aria(option=option)
        instance.listen(lambda cmd: aria.shutdown() if cmd == "quit" else None)
        aria.run()
    else:
        from ui.overlay import run_with_overlay
        run_with_overlay(lambda bridge: Aria(option=option, ui=bridge))
