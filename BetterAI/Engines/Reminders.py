"""
Reminders & timers, stored in aria_memory.db so they survive restarts.

A background thread checks every second; due items are handed to on_due(reminder)
(Aria announces them). on_change() fires whenever the pending list changes, so the
overlay can update its countdown ring.
"""

import datetime
import re
import threading
import time


def _fmt_delta(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    h, m = divmod(minutes, 60)
    out = f"{h} hour{'s' if h != 1 else ''}"
    return out + (f" {m} minute{'s' if m != 1 else ''}" if m else "")


def _fmt_when(due: float) -> str:
    dt = datetime.datetime.fromtimestamp(due)
    delta = due - time.time()
    if delta < 3600:
        return f"in {_fmt_delta(delta)}"
    day = "" if dt.date() == datetime.date.today() else (
        " tomorrow" if dt.date() == datetime.date.today() + datetime.timedelta(days=1)
        else dt.strftime(" on %A %d %B"))
    return f"at {dt.strftime('%H:%M')}{day}"


def _parse_clock(text: str) -> datetime.datetime | None:
    """'14:30', '2:30pm', '7pm', '07:05' → next occurrence of that time."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*", text.lower())
    if not m:
        return None
    h, mi, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        h = h % 12 + (12 if ampm.startswith("p") else 0)
    if h > 23 or mi > 59:
        return None
    now = datetime.datetime.now()
    target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return target


DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_repeat(text):
    """'every day' -> daily, 'weekdays' -> weekdays, 'every week' -> weekly, 'monthly',
    'every monday and thursday' / 'mondays' -> 'mon,thu'. None = no repeat, False = not understood."""
    s = str(text or "").strip().lower()
    if s in ("", "none", "no", "once", "never", "false"):
        return None
    days = [k for k, name in zip(DAY_KEYS, DAY_NAMES) if re.search(rf"\b{name.lower()}s?\b|\b{k}\b", s)]
    if days:
        return ",".join(days)
    if re.search(r"week ?days?|work ?days?|monday to friday", s):
        return "weekdays"
    if re.search(r"daily|every ?day|each day|every morning|every evening|every night", s):
        return "daily"
    if re.search(r"weekly|every week|each week", s):
        return "weekly"
    if re.search(r"monthly|every month|each month", s):
        return "monthly"
    return False


def describe_repeat(rep) -> str:
    if not rep:
        return ""
    fixed = {"daily": "every day", "weekdays": "every weekday", "weekly": "every week", "monthly": "every month"}
    if rep.split(":")[0] in fixed:
        return fixed[rep.split(":")[0]]
    names = [DAY_NAMES[DAY_KEYS.index(k)] for k in rep.split(",") if k in DAY_KEYS]
    return "every " + (" and ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else names[0])


def _repeat_matches(rep, date: datetime.date, first: datetime.date) -> bool:
    if rep == "daily":
        return True
    if rep == "weekdays":
        return date.weekday() < 5
    if rep == "weekly":
        return date.weekday() == first.weekday()
    if rep.startswith("monthly"):
        # "monthly:31" keeps the original day, so the 31st -> 28 Feb -> 31 Mar (not the 28th forever)
        want = int(rep.split(":")[1]) if ":" in rep else first.day
        last = (date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        return date.day == min(want, last.day)
    return DAY_KEYS[date.weekday()] in rep.split(",")


def next_occurrence(rep, after: datetime.datetime, first: datetime.date = None) -> datetime.datetime:
    """Next time on a day matching `rep`, at after's clock time, strictly later than `after`."""
    first = first or after.date()
    day = after.date() + datetime.timedelta(days=1)
    for _ in range(400):
        if _repeat_matches(rep, day, first):
            return datetime.datetime.combine(day, after.time())
        day += datetime.timedelta(days=1)
    raise ValueError(f"bad repeat {rep!r}")


class Reminders:
    def __init__(self, memory, on_due, on_change=None):
        self.memory = memory
        self.on_due = on_due
        self.on_change = on_change or (lambda: None)
        self.last_fired = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        self.on_change()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                due = self.memory.take_due_reminders(time.time())
                for r in due:
                    self.last_fired = r
                    if r.get("repeat"):     # schedule the next one before announcing this one
                        nxt = next_occurrence(r["repeat"], datetime.datetime.fromtimestamp(r["due"]))
                        while nxt.timestamp() <= time.time():      # laptop was off for a while: skip missed ones
                            nxt = next_occurrence(r["repeat"], nxt)
                        self.memory.add_reminder(r["text"], r["kind"], nxt.timestamp(), r["repeat"])
                    self.on_due(r)
                if due:
                    self.on_change()
            except Exception as e:
                print(f"[Reminders] {e}")
            time.sleep(1)

    # ── Core ──────────────────────────────────────────────────────────────────

    def add(self, text: str, kind: str, due: float, repeat: str = None) -> int:
        rid = self.memory.add_reminder(text, kind, due, repeat) if repeat else self.memory.add_reminder(text, kind, due)
        self.on_change()
        return rid

    def cancel_id(self, reminder_id: int):
        self.memory.cancel_reminder(reminder_id)
        self.on_change()

    def pending(self, kinds=None) -> list:
        items = self.memory.pending_reminders()
        return [r for r in items if not kinds or r["kind"] in kinds]

    # ── Tool handlers ─────────────────────────────────────────────────────────

    def set_timer(self, minutes, label: str = ""):
        seconds = float(minutes) * 60
        if seconds <= 0:
            return "Timer length has to be more than zero."
        label = (label or "").strip()
        self.add(label or "timer", "timer", time.time() + seconds)
        return f"Timer set for {_fmt_delta(seconds)}" + (f" ({label})." if label else ".")

    def set_reminder(self, text: str, in_minutes=None, at_time: str = None, day: str = None, repeat: str = None):
        text = (text or "").strip() or "something"
        rep = parse_repeat(repeat)
        if rep is False:
            return f"I can repeat reminders every day, on weekdays, every week, every month or on certain weekdays — not '{repeat}'."
        if rep is None and day and parse_repeat(day):          # "mondays" given as the day
            rep = parse_repeat(day)
            day = None
        if rep:
            return self._set_repeating(text, at_time, day, rep)
        if in_minutes not in (None, ""):
            due = time.time() + float(in_minutes) * 60
        elif day not in (None, "", "today"):
            # "monday at 10" / "tomorrow" (no time -> 09:00); same date words as the calendar
            from Engines.NotionEngine import parse_day
            date = parse_day(day)
            if not date:
                return f"I couldn't understand the day '{day}'. Say e.g. 'tomorrow', 'monday' or '12.11.'."
            clock = _parse_clock(str(at_time)) if at_time else None
            if at_time and not clock:
                return f"I couldn't understand the time '{at_time}'. Use HH:MM."
            hh, mm = (clock.hour, clock.minute) if clock else (9, 0)
            target = datetime.datetime.combine(date, datetime.time(hh, mm))
            if target.timestamp() <= time.time():
                return "That time has already passed."
            due = target.timestamp()
        elif at_time:
            target = _parse_clock(str(at_time))
            if not target:
                return f"I couldn't understand the time '{at_time}'. Use HH:MM."
            due = target.timestamp()
        else:
            return "When should I remind you? Give minutes from now or a time."
        self.add(text, "reminder", due)
        return f"I'll remind you to {text} {_fmt_when(due)}."

    def _set_repeating(self, text, at_time, day, rep):
        clock = _parse_clock(str(at_time)) if at_time else None
        if at_time and not clock:
            return f"I couldn't understand the time '{at_time}'. Use HH:MM."
        hh, mm = (clock.hour, clock.minute) if clock else (9, 0)
        start = datetime.date.today()
        weekday_set = "," in rep or rep in DAY_KEYS
        if day not in (None, "", "today") and not (weekday_set and parse_repeat(day)):
            # (the model often repeats one of the weekdays as `day`; for "monday and thursday" that
            #  would skip this week's Monday, so a weekday given for a weekday repeat is ignored)
            from Engines.NotionEngine import parse_day
            start = parse_day(day) or start
        if rep == "monthly":
            rep = f"monthly:{start.day}"
        first = datetime.datetime.combine(start, datetime.time(hh, mm))
        if first.timestamp() <= time.time() or not _repeat_matches(rep, start, start):
            first = next_occurrence(rep, first, start)
        self.add(text, "reminder", first.timestamp(), rep)
        days = (first.date() - datetime.date.today()).days
        starting = "today" if days == 0 else "tomorrow" if days == 1 else first.strftime("%A %d %B")
        return f"I'll remind you to {text} {describe_repeat(rep)} at {hh:02d}:{mm:02d}, starting {starting}."

    def list_reminders(self):
        items = self.pending(("timer", "reminder", "focus", "event"))
        if not items:
            return "No timers or reminders set."
        parts = []
        for r in items:
            what = {"timer": f"timer '{r['text']}'", "focus": "focus session ends",
                    "event": f"heads-up for {r['text']}"}.get(r["kind"], r["text"])
            rep = f" (repeats {describe_repeat(r.get('repeat'))})" if r.get("repeat") else ""
            parts.append(f"{what} {_fmt_when(r['due'])}{rep}")
        return "; ".join(parts) + "."

    def cancel_reminder(self, which: str = "last"):
        items = self.pending(("timer", "reminder"))
        if not items:
            return "There's nothing to cancel."
        which = (which or "last").strip().lower()
        if which == "all":
            for r in items:
                self.memory.cancel_reminder(r["id"])
            self.on_change()
            return f"Cancelled {len(items)} timer{'s' if len(items) != 1 else ''}/reminder{'s' if len(items) != 1 else ''}."
        if which in ("last", "latest", "timer", "reminder", "it", "that"):
            pool = [r for r in items if which not in ("timer", "reminder") or r["kind"] == which] or items
            target = max(pool, key=lambda r: r["created"])
        else:
            matches = [r for r in items if which in r["text"].lower()]
            if not matches:
                return f"I couldn't find a timer or reminder matching '{which}'."
            target = matches[0]
        self.cancel_id(target["id"])
        if target.get("repeat"):
            return f"Cancelled '{target['text']}' ({describe_repeat(target['repeat'])}) — it won't come back."
        return f"Cancelled '{target['text']}'."

    def snooze(self, minutes=5):
        r = self.last_fired
        if not r or r["kind"] == "focus":
            return "There's nothing to snooze."
        seconds = float(minutes or 5) * 60
        self.add(r["text"], r["kind"], time.time() + seconds)
        return f"Snoozed '{r['text']}' for {_fmt_delta(seconds)}."

    @staticmethod
    def announcement(r) -> str:
        if r["kind"] == "timer":
            return "Time's up." if r["text"] == "timer" else f"Time's up: {r['text']}."
        if r["kind"] == "event":
            return f"Heads up: {r['text']} starts in 15 minutes."
        return f"Reminder: {r['text']}."
