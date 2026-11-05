"""
Follow-ups: Lala mentions something coming up ("I have an exam tomorrow"), and afterwards Aria asks how it went.

After each conversation the fact extraction (llm_engine.extract_facts) also returns upcoming things. They're
scheduled here: asked about the evening of that day (a few hours later for "today"), either in Aria's
greeting or as a conversation she starts (Engines/Initiative.py). Unasked ones expire after 3 days.
Things that are timed events in MyNotion are skipped: the event check-in already asks about those.
"""

import datetime as dt
import re
import time

from Engines.NotionEngine import _match_score, parse_day

ASK_AT_HOUR = 17          # ask about a day's thing from this hour on
TODAY_DELAY_H = 3         # "this afternoon"/"today": ask a few hours later
EXPIRE_DAYS = 3


def ask_time(when: str, now: dt.datetime = None) -> float | None:
    now = now or dt.datetime.now()
    w = (when or "").strip().lower()
    w = re.sub(r"\s+(?:at|around|from)\s+\d.*$|\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)$", "", w)   # "friday at 3 pm" -> "friday"
    today = now.date()
    if w in ("", "now", "today", "tonight", "this afternoon", "this evening", "later", "later today", "this morning"):
        at = now + dt.timedelta(hours=TODAY_DELAY_H)
        if at.hour >= 22 or at.date() > today:           # too late tonight: ask the next morning instead
            at = dt.datetime.combine(today + dt.timedelta(days=1), dt.time(9))
        return at.timestamp()
    if w in ("soon", "unclear", "unknown"):
        day = today + dt.timedelta(days=2)
    elif "weekend" in w:
        day = today + dt.timedelta(days=(5 - today.weekday()) % 7 or 7)    # saturday
        day += dt.timedelta(days=1)                                         # ask on sunday
    elif w == "next week":
        day = today + dt.timedelta(days=7)
    else:
        day = parse_day(re.sub(r"^(on|this|next)\s+", lambda m: "next " if m.group(1) == "next" else "", w), today)
        if not day:
            return None
    at = dt.datetime.combine(day, dt.time(ASK_AT_HOUR))
    return max(at, now + dt.timedelta(hours=1)).timestamp()


class Followups:
    def __init__(self, memory, notion=None):
        self.memory = memory
        self.notion = notion

    def add_from_extraction(self, items) -> int:
        added = 0
        pending = self.memory.pending_followups()
        for it in items:
            about = str(it.get("about", "")).strip()
            question = str(it.get("question", "")).strip()
            at = ask_time(str(it.get("when", "")))
            if not about or not question or at is None:
                continue
            if any(_match_score(about, p["about"]) >= 60 for p in pending):
                continue                                     # already waiting to ask about this
            if self._in_calendar(about, at):
                continue
            self.memory.add_followup(about, question, at, at + EXPIRE_DAYS * 86400)
            pending.append({"about": about})
            added += 1
        return added

    def _in_calendar(self, about, at):
        if not self.notion:
            return False
        day = dt.date.fromtimestamp(at)
        try:
            events = self.notion._events_between(day - dt.timedelta(days=1), day)
        except Exception:
            return False
        return any(not e["allDay"] and e["startHour"] is not None and not e.get("repeat")
                   and _match_score(about, e["title"]) >= 60 for e in events)

    def due(self):
        """The oldest follow-up that's ready to ask (expired ones are dropped)."""
        now = time.time()
        for f in self.memory.pending_followups():
            if f["expires"] < now:
                self.memory.set_followup_status(f["id"], 2)
                continue
            if f["ask_after"] <= now:
                return f
        return None

    def asked(self, f):
        self.memory.set_followup_status(f["id"], 1)
