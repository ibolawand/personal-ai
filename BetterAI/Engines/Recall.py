"""
"What did we talk about yesterday?" / "when did I mention the exam?" — Aria looks through her message history
(aria_memory.db, the last 3000 messages) instead of guessing.
"""

import datetime as dt
import re

from Engines.NotionEngine import WEEKDAYS, parse_day

MAX_CHARS = 3500       # what goes back to the model
STOP = {"what", "did", "we", "talk", "talked", "about", "when", "i", "mention", "mentioned", "say", "said",
        "the", "a", "an", "my", "you", "me", "to", "of", "last", "time", "ever", "did", "do", "tell", "told"}


def past_day(text: str, today: dt.date = None):
    """'yesterday', 'monday' / 'last monday' (the most recent one), '3 days ago', or a date — looking back."""
    today = today or dt.date.today()
    s = re.sub(r"^(on|last|this|the)\s+", "", (text or "yesterday").strip().lower())
    if s in ("today", "earlier", "this morning"):
        return today
    if s == "yesterday":
        return today - dt.timedelta(days=1)
    if s in ("day before yesterday", "the day before yesterday"):
        return today - dt.timedelta(days=2)
    m = re.fullmatch(r"(\d+|a|one|two|three) days? ago", s)
    if m:
        return today - dt.timedelta(days={"a": 1, "one": 1, "two": 2, "three": 3}.get(m.group(1)) or int(m.group(1)))
    if s.rstrip("s") in WEEKDAYS:
        back = (today.weekday() - WEEKDAYS.index(s.rstrip("s"))) % 7 or 7
        return today - dt.timedelta(days=back)
    d = parse_day(s, today)
    if d and d > today:                       # "12.11." etc. without a year that landed in the future
        d = d.replace(year=d.year - 1) if d.replace(year=d.year - 1) <= today else d
    return d


def past_label(d: dt.date, today: dt.date = None) -> str:
    today = today or dt.date.today()
    if d == today:
        return "today"
    if d == today - dt.timedelta(days=1):
        return "yesterday"
    return f"on {d.strftime('%A')} {d.day} {d.strftime('%B')}"


class Recall:
    def __init__(self, memory):
        self.memory = memory

    def conversations_on(self, day: str = "yesterday"):
        d = past_day(day or "yesterday")
        if not d:
            return f"I couldn't understand the day '{day}'."
        rows = self.memory.messages_on(d.isoformat())
        label = past_label(d)
        if not rows:
            return f"We didn't talk {label}." if d != dt.date.today() else "We haven't talked today yet."
        lines, size = [], 0
        for hhmm, role, content in rows:
            who = "Lala" if role == "user" else "Aria"
            line = f"{hhmm} {who}: {' '.join(content.split())[:160]}"
            size += len(line)
            lines.append(line)
        while size > MAX_CHARS and len(lines) > 10:          # keep the start and the end of a long day
            size -= len(lines.pop(len(lines) // 2))
        return (f"Conversation {label} ({len(rows)} messages). Summarise the main topics in two or three spoken "
                f"sentences, as a friend remembering it:\n" + "\n".join(lines))

    def search(self, query: str):
        words = [w for w in re.findall(r"[a-z0-9#+']+", (query or "").lower()) if w not in STOP and len(w) > 1]
        if not words:
            return "What should I look for?"
        rows = self.memory.search_messages(words)
        if not rows:
            return f"I can't find us talking about {' '.join(words)} (I remember the last 3000 messages)."
        today = dt.date.today()
        out = []
        for day, hhmm, role, content in rows:
            who = "Lala" if role == "user" else "Aria"
            out.append(f"{past_label(dt.date.fromisoformat(day), today)} {hhmm} {who}: {' '.join(content.split())[:200]}")
        return "Messages that mention it, newest first:\n" + "\n".join(out)
