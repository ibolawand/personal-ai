"""Test countdown: which tests are close, which notebook and notes belong to them, and the quiz it starts.

Everything is decided here in code. WebUntis gives the tests, the user maps a subject to a MyNotion notebook once
(kept in test_prep.json), the test's topic picks the notes, and the quiz asks earlier mistakes first."""
import datetime as dt
import json
import os
import random
import re
import threading
import time

from Engines import Diagnostics
from Engines.NotionEngine import html_to_text

STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "test_prep.json")
DAYS = 7              # how far ahead tests count as coming up
MAX_CARDS = 3
RETRY_AFTER = 60      # seconds a failed WebUntis lookup is not asked again
QUIZ_SIZE = 8         # questions in one test quiz
MAX_OLD = 4           # of those, at most this many earlier mistakes
MAX_NOTES = 3         # new questions come from at most this many notes
MIN_WORDS = 25        # a note shorter than this has nothing to quiz on

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WORD_RE = re.compile(r"[^\W_]+")


class TestPrep:
    __test__ = False      # not a pytest class

    def __init__(self, untis, notion, quiz, today=dt.date.today, rng=random, clock=time.monotonic):
        self.untis, self.notion, self.quiz = untis, notion, quiz
        self.today, self.rng, self.clock = today, rng, clock
        self._failed = None            # (time, exception) of the last failed WebUntis lookup
        self._lock = threading.Lock()

    # ── subject → notebook map ──

    def _load_map(self) -> dict:
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        subjects = data.get("subjects") if isinstance(data, dict) else None
        return subjects if isinstance(subjects, dict) else {}

    def notebooks(self) -> list:
        return self.notion.notebooks()

    def notebook_for(self, subject: str):
        books = self.notebooks()
        with self._lock:
            mapped = self._load_map().get(subject)
        for b in books:
            if mapped is not None and b["id"] == mapped:
                return {"id": b["id"], "name": b["name"]}
        for b in books:
            if (b["name"] or "").lower() == (subject or "").lower():
                return {"id": b["id"], "name": b["name"]}
        return None

    def set_notebook(self, subject: str, folder_id: int) -> bool:
        if folder_id not in {b["id"] for b in self.notebooks()}:
            return False
        with self._lock:
            data = self._load_map()
            data[subject] = folder_id
            try:
                os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
                with open(STATE_FILE, "w") as f:
                    json.dump({"subjects": data}, f)
            except OSError:
                return False
        return True

    # ── notes ──

    def _notes(self, folder_id: int) -> list:
        """(title, text) of every note in the notebook with enough in it to quiz on."""
        out = []
        for n in self.notion.notebook_notes(folder_id):
            text = html_to_text(n.get("content") or "")
            if len(text.split()) >= MIN_WORDS:
                out.append((n.get("title") or "Untitled note", text))
        return out

    @staticmethod
    def _pick(notes: list, topic: str) -> list:
        words = [w.lower() for w in WORD_RE.findall(topic or "") if len(w) > 2]
        if words:
            kept = [(t, x) for t, x in notes if all(w in f"{t} {x}".lower() for w in words)]
            if kept:
                return kept
        return notes

    # ── cards ──

    @staticmethod
    def _label(t: dict) -> str:
        return f"{t['subject']} test" if t["kind"] == "Test" else f"{t['subject']} {t['kind']}"

    def _upcoming(self) -> list:
        failed = self._failed
        if failed and self.clock() - failed[0] < RETRY_AFTER:
            raise failed[1]
        try:
            tests = self.untis.upcoming_tests(DAYS)
        except Exception as e:
            self._failed = (self.clock(), e)
            raise
        self._failed = None
        return tests

    def _card(self, t: dict, today: dt.date) -> dict:
        days = (t["date"] - today).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else WEEKDAYS[t["date"].weekday()]
        label = self._label(t)
        headline = f"{label} {when}" if days <= 1 else f"{label} on {when} · in {days} days"
        book = self.notebook_for(t["subject"])
        count = len(self._pick(self._notes(book["id"]), t.get("topic", ""))) if book else 0
        return {"id": t["id"], "subject": t["subject"], "kind": t["kind"], "date": f"{t['date']:%Y-%m-%d}",
                "when": when, "days": days, "topic": t.get("topic", ""), "headline": headline,
                "notebook": book, "notes": count}

    def cards(self) -> list:
        try:
            tests = self._upcoming()[:MAX_CARDS]
            today = self.today()
            return [self._card(t, today) for t in tests]
        except Exception as e:
            Diagnostics.problem("test_prep", type(e).__name__)
            return []

    # ── the quiz ──

    def start_quiz(self, test_id: str):
        try:
            test = next((t for t in self._upcoming() if t["id"] == test_id), None)
        except Exception as e:
            Diagnostics.problem("test_prep", type(e).__name__)
            return "I can't reach WebUntis right now.", ""
        if not test:
            return "That test isn't coming up any more.", ""
        subject = test["subject"]
        book = self.notebook_for(subject)
        if not book:
            return f"Tell me which notebook belongs to {subject} first.", subject
        usable = self._notes(book["id"])
        picked = self._pick(usable, test.get("topic", ""))
        if not picked:
            return f"Your {book['name']} notes don't have enough in them to quiz you on yet.", subject
        titles = {n.get("title") or "Untitled note" for n in self.notion.notebook_notes(book["id"])}
        misses = [m for m in self.quiz._load().get("misses", []) if m.get("source") in titles]
        old = sorted(misses, key=lambda m: m.get("at", 0), reverse=True)[:MAX_OLD]
        chosen = self.rng.sample(picked, min(MAX_NOTES, len(picked)))
        base, extra = divmod(QUIZ_SIZE - len(old), len(chosen))
        sources = [(t, x, base + (1 if i < extra else 0)) for i, (t, x) in enumerate(chosen)]
        return self.quiz.start_mixed(self._label(test), old, sources), subject

    def briefing_line(self) -> str:
        try:
            today = self.today()
            for c in (self._card(t, today) for t in self._upcoming()):
                if c["notebook"] and c["notes"] > 0:
                    return f"I can quiz you on your {c['notebook']['name']} notes."
        except Exception as e:
            Diagnostics.problem("test_prep", type(e).__name__)
        return ""
