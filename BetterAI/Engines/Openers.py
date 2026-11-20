"""
Weekend openers: on free days (no lessons) the companion starts a chat now and then, in a bubble.

Decided in code: when (10 min after she wakes, then every 25–45 min, backing off when ignored, at most 8 a day) and
what about (a nudge from something real, at most every other time, or small talk). The local model only words it;
a fixed line stands in when it can't. Plain functions and one small class, tested without a model.
"""
import datetime as dt
import random
import re
from dataclasses import dataclass

FIRST_S = 10 * 60               # the first opener, this long after she woke
MIN_GAP_S, MAX_BASE_GAP_S = 25 * 60, 45 * 60
MAX_GAP_S = 2 * 3600            # backing off stops here
PER_DAY = 8
ANSWER_S = 10 * 60              # a conversation this soon after an opener answers it
NUDGE_CHANCE = 0.7              # a nudge is possible (something real, and the last one wasn't a nudge)
TEST_DAYS = 3                   # a test this close is worth a nudge
WATCH_MIN = 60                  # minutes of video before a break nudge

NUDGES = ("test", "today", "watch")


def free_day(now: dt.datetime, span) -> bool:
    """No lessons today. `span` as in Companion.school_span: (start, end), None (no lessons) or UNKNOWN (can't
    tell: then Saturday and Sunday)."""
    if span is None:
        return True
    if isinstance(span, tuple):
        return False
    return now.weekday() >= 5


@dataclass
class Topic:
    name: str           # test | today | watch | app | time | rain | random
    about: str          # what the model is told to talk about
    fallback: str       # the line when the model can't
    gesture: str = "smile"


_TIME = {"morning": ("the morning: ask how they slept or what the plan for today is", "slept well? what's the plan today?"),
         "lunch": ("lunchtime: ask if they've eaten", "had lunch yet?"),
         "afternoon": ("a lazy free afternoon: ask what they're up to", "what are you up to this afternoon?"),
         "evening": ("the evening: ask how the day was", "how was your day?")}

_RANDOM = [("a fun what-if question, like which superpower they'd want today", "if you could have any superpower today, which one?"),
           ("the best thing that happened to them this week", "what's the best thing that happened this week?"),
           ("something they're looking forward to", "tell me something you're looking forward to"),
           ("a song they'd recommend to you", "quick, name a song I should know"),
           ("being a little bored and wanting to chat", "I'm bored. talk to me 😄"),
           ("a small fun plan for the rest of the day", "we should do something fun today. ideas?")]

_APP = {"code": "the code they're writing", "video": "what they're watching", "browser": "what they're browsing",
        "mynotion": "the notes they're working on", "terminal": "what they're doing in the terminal",
        "music": "the music they're playing", "chat": "who they're chatting with", "docs": "what they're reading"}
_APP_FALLBACK = {"code": "ooh, what are we building?", "video": "ooh, what are we watching?",
                 "browser": "whatcha looking up?", "mynotion": "notes time? you've got this",
                 "terminal": "what are you hacking on?", "music": "what are we listening to?",
                 "chat": "who are you talking to?", "docs": "reading something smart?"}
_APP_GESTURE = {"code": "think", "video": "curious", "browser": "lookAround", "music": "rock", "docs": "think"}


def _day_part(hour: int) -> str:
    return "morning" if hour < 11 else "lunch" if hour < 14 else "afternoon" if hour < 18 else "evening"


def _nudges(facts) -> list:
    out = []
    test = facts.get("test")
    if test and test.get("subject") and test.get("days") is not None and test["days"] <= TEST_DAYS:
        when = test.get("when") or "soon"
        out.append(Topic("test", f"their {test['subject']} test {when}: suggest a short 15-minute review, warmly, "
                                 f"no pressure", f"{test['subject']} test {when}… 15 minutes of review together?",
                         "think"))
    today = facts.get("today") or []
    if today:
        text, at = today[0]
        out.append(Topic("today", f"a reminder that '{text}' is at {at} today", f"don't forget: {text} at {at}",
                         "lookAround"))
    if facts.get("kind") == "video" and (facts.get("watch_min") or 0) >= WATCH_MIN:
        out.append(Topic("watch", "they've been watching videos for over an hour: suggest a stretch break or doing "
                                  "something they wanted to get done, playfully",
                         "you've been watching for over an hour 👀 stretch break? or something off your list first?",
                         "stretch"))
    return out


def _small_talk(facts) -> list:
    out = []
    kind = facts.get("kind")
    if kind in _APP:
        out.append(Topic("app", _APP[kind], _APP_FALLBACK[kind], _APP_GESTURE.get(kind, "smile")))
    about, line = _TIME[_day_part(facts.get("hour", 12))]
    out.append(Topic("time", about, line, "smile"))
    if facts.get("rain"):
        out.append(Topic("rain", "rain coming later: a cosy reason to stay in", "rain's coming later. perfect excuse to stay in",
                         "lookAround"))
    return out


class Openers:
    """When the next opener is due and what it's about. Times in seconds (any clock), days as dates."""

    def __init__(self, rng=random):
        self.rng = rng
        self.next_at = None
        self.ignored = 0            # openers in a row nobody answered
        self.day, self.count = None, 0
        self.last = None            # the last Topic
        self.shown_at = None        # when the last opener went up, until it was answered
        self._random_left = []

    def woke(self, t: float):
        """She woke herself: the first opener comes a while later (not on top of the greeting)."""
        self.next_at = max(self.next_at or 0, t + FIRST_S)

    def due(self, t: float, day: dt.date) -> bool:
        if day != self.day:
            self.day, self.count = day, 0
        return self.count < PER_DAY and (self.next_at is None or t >= self.next_at)

    def pick(self, facts: dict) -> Topic:
        """`facts`: kind (app in front), hour, test (the next TestPrep card), today [(text, "HH:MM")] still ahead,
        watch_min (minutes on video), rain."""
        last = self.last.name if self.last else None
        nudges = [n for n in _nudges(facts) if n.name != last]
        if nudges and last not in NUDGES and self.rng.random() < NUDGE_CHANCE:
            return self.rng.choice(nudges)
        talk = [s for s in _small_talk(facts) if s.name != last]
        if last != "random" and (not talk or self.rng.random() < 0.4):
            return self._random()
        return self.rng.choice(talk) if talk else self._random()

    def _random(self) -> Topic:
        if not self._random_left:
            self._random_left = list(_RANDOM)
        about, line = self._random_left.pop(self.rng.randrange(len(self._random_left)))
        return Topic("random", about, line, "curious")

    def shown(self, t: float, topic: Topic, day: dt.date):
        if self.shown_at is not None:           # the one before went unanswered
            self.ignored += 1
        if day != self.day:
            self.day, self.count = day, 0
        self.count += 1
        self.last, self.shown_at = topic, t
        gap = self.rng.uniform(MIN_GAP_S, MAX_BASE_GAP_S) * 2 ** max(0, self.ignored - 1)
        self.next_at = t + min(gap, MAX_GAP_S)

    def answered(self):
        self.ignored, self.shown_at = 0, None

    def open_since(self, t: float) -> bool:
        """An opener went up recently and hasn't been answered: a conversation now answers it."""
        return self.shown_at is not None and t - self.shown_at <= ANSWER_S


def prompt_for(topic: Topic) -> str:
    """The model's task for one opener (sent with Aria's usual system prompt, no tools, no history)."""
    return ("(Not from Lala. You're keeping Lala company on a free day and want to start a chat by yourself. "
            f"Topic: {topic.about}. Write only the one short casual line you send them: at most 20 words, a remark or "
            "a question a friend would send. No greeting, no offer of help, no quotes.)")


_STOCK_RE = re.compile(r"\b(help you|assist|how can i|anything (?:else )?i can|let me know if)\b", re.I)


def clean_line(text, fallback: str) -> str:
    """The model's line, tidied; the fallback when it's empty, long, several lines or sounds like an assistant."""
    text = (text or "").strip().strip('"“”\'').strip()
    if not text or len(text) > 180 or len(text.split()) > 30 or text.count("\n") >= 2 or _STOCK_RE.search(text):
        return fallback
    return " ".join(text.split())
