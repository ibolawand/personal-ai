"""
Small fixes for typed messages, before anything else sees them (never for speech: Whisper writes real words).
From the real log: "ope n notes" went nowhere. Only safe cases are changed:
  - a command word split in two: "ope n notes" -> "open notes", "pla y music" -> "play music"
  - a misspelt first word that is clearly a command: "opne", "pley", "remidn" (not when it's a real English word)
  - a few common misspellings anywhere: calender, tommorow, wether…
"""

import difflib
import re
from functools import lru_cache

COMMANDS = ["open", "close", "play", "pause", "stop", "start", "show", "add", "remind", "remove", "delete", "set",
            "turn", "quiz", "learn", "search", "find", "what", "when", "where", "how", "skip", "mute", "lock",
            "cancel", "move", "check", "tell", "read", "note", "undo", "snooze", "focus", "clear", "put", "look"]
MISSPELLINGS = {"calender": "calendar", "calandar": "calendar", "calener": "calendar", "tommorow": "tomorrow",
                "tomorow": "tomorrow", "tommorrow": "tomorrow", "tmrw": "tomorrow", "wether": "weather",
                "whether's": "weather's", "remeber": "remember", "rember": "remember", "shoping": "shopping",
                "playlsit": "playlist", "spotfy": "spotify", "spotif": "spotify", "reminer": "reminder",
                "remider": "reminder", "notifcations": "notifications", "volumn": "volume", "voume": "volume",
                "wifi's": "wifi is", "teh": "the", "plz": "please", "pls": "please", "u": "you", "ur": "your"}


@lru_cache(maxsize=1)
def _dictionary():
    try:
        with open("/usr/share/dict/words") as f:
            return frozenset(w.strip().lower() for w in f)
    except OSError:
        return frozenset()


def _is_word(w):
    d = _dictionary()
    return not d or w in d


def fix_typos(text: str) -> str:
    words = text.split()
    if not words:
        return text
    low = [w.lower() for w in words]
    # "ope n notes": the first two pieces make a command
    if len(words) >= 2 and low[0] + low[1] in COMMANDS and not (_is_word(low[0]) and _is_word(low[1]) and
                                                                  len(low[1]) > 1):
        words[:2] = [words[0] + words[1]]
        low[:2] = [low[0] + low[1]]
    # "opne notes": a non-word first word that's one typo away from a command
    first = re.sub(r"[^a-z]", "", low[0])
    if first and first not in COMMANDS and len(first) >= 3 and not _is_word(first):
        close = difflib.get_close_matches(first, COMMANDS, n=1, cutoff=0.75)
        if close:
            words[0] = close[0]
    out = []
    for w in words:
        m = re.match(r"^([A-Za-z']+)(\W*)$", w)
        if m and m.group(1).lower() in MISSPELLINGS:
            out.append(MISSPELLINGS[m.group(1).lower()] + m.group(2))
        else:
            out.append(w)
    return " ".join(out)
