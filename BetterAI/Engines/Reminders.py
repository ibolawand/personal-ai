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
                    self.on_due(r)
                if due:
                    self.on_change()
            except Exception as e:
                print(f"[Reminders] {e}")
            time.sleep(1)

    # ── Core ──────────────────────────────────────────────────────────────────

    def add(self, text: str, kind: str, due: float) -> int:
        rid = self.memory.add_reminder(text, kind, due)
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

    def set_reminder(self, text: str, in_minutes=None, at_time: str = None):
        text = (text or "").strip() or "something"
        if in_minutes not in (None, ""):
            due = time.time() + float(in_minutes) * 60
        elif at_time:
            target = _parse_clock(str(at_time))
            if not target:
                return f"I couldn't understand the time '{at_time}'. Use HH:MM."
            due = target.timestamp()
        else:
            return "When should I remind you? Give minutes from now or a time."
        self.add(text, "reminder", due)
        return f"I'll remind you to {text} {_fmt_when(due)}."

    def list_reminders(self):
        items = self.pending(("timer", "reminder", "focus", "event"))
        if not items:
            return "No timers or reminders set."
        parts = []
        for r in items:
            what = {"timer": f"timer '{r['text']}'", "focus": "focus session ends",
                    "event": f"heads-up for {r['text']}"}.get(r["kind"], r["text"])
            parts.append(f"{what} {_fmt_when(r['due'])}")
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
