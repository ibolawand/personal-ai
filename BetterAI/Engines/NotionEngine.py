"""
MyNotion integration: Aria reads and writes the same SQLite file as the MyNotion app
(../MyNotion/note/noted.db, set as DB_PATH in Engines/.env). MyNotion watches the file
and refreshes itself, so whatever Aria adds shows up there right away.

  Notes   — quick notes into an "Inbox" note, named notes, read / search / list
  Lists   — "add eggs to my shopping list": a note holding a bullet list
  Calendar— read, add, move, delete events (move/delete ask first)
  Extras  — reminders 15 min before events, and the daily briefing

Note content is TipTap HTML (what MyNotion's editor stores), so text is converted both ways.
"""

import datetime as dt
import html
import os
import re
import sqlite3
import subprocess
from pathlib import Path
import time
from contextlib import contextmanager

from Engines.DueDates import (EVENING_HOUR, SOON_DAYS, say_due, split_due, strip_by_phrase, with_due)

EVENT_REMINDER_MIN = 15          # announce events this many minutes before they start
DAY_AHEAD_HOUR = 9               # birthdays & co: heads-up at this hour the day before
YEARLY_RE = re.compile(r"\b(birthday|bday|anniversary|name ?day)\b", re.I)
ARIA_EVENT_COLOR = "purple"      # MyNotion's calendar colours: blue, green, purple, red
INBOX_TITLE = "Inbox"
# Today's note: MyNotion's Ctrl+D opens a note with this title, made from the same template.
DAILY_RE = re.compile(r"^\s*(?:my\s+)?(?:today'?s?|daily|day)(?:\s+note)?\s*$", re.I)
DAILY_TEMPLATE = ('<h2>Plan</h2><ul data-type="taskList"><li data-checked="false" data-type="taskItem"><label>'
                  '<input type="checkbox"><span></span></label><div><p></p></div></li></ul><h2>Notes</h2><p></p>')


def daily_title(day: dt.date = None) -> str:
    """'Saturday, 7 November 2026', the same as MyNotion's today's note."""
    d = day or dt.date.today()
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B %Y')}"
# the packaged app (MyNotion: build_app.sh); override with MYNOTION_BIN in Engines/.env
MYNOTION_BIN = os.environ.get("MYNOTION_BIN") or str(
    Path(__file__).resolve().parents[3] / "MyNotion" / "note" / "out" / "MyNotion-linux-x64" / "MyNotion")
MAX_READ_CHARS = 2500
# "this note", "the open note", "it": the note open in MyNotion right now (MyNotion keeps it in app_state)
THIS_RE = re.compile(r"^\s*(?:(?:this|that|the current|the open|my open|current|open|the)\s*(?:note|page|one)?|it|here)\s*$",
                     re.I)
EDIT_SETTLE_S = 1.2     # before Aria reads the open note: MyNotion saves what was just typed (600 ms after the last key)
LOCK_FOR_S = 180        # MyNotion ignores a lock older than this (Aria crashed while editing)
APP_STATE_SQL = ("CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT, "
                 "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")


def mynotion_running() -> bool:
    """Is the MyNotion app open? (Its "open note" is only true while it is.)"""
    try:
        return subprocess.run(["pgrep", "-x", "MyNotion"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=3).returncode == 0
    except Exception:                       # no pgrep, a timeout, or the tests' stand-in for starting programs
        return False

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


# ── Text <-> TipTap HTML ──────────────────────────────────────────────────────

MATH_RE = re.compile(r'<(span|div)[^>]*data-type="(inline|block)-math"[^>]*>.*?</\1>', re.I | re.S)


def _math_text(m):
    """A formula from MyNotion (stored only in data-latex) as $…$ / $$…$$, so it can be read and searched."""
    latex = re.search(r'data-latex="([^"]*)"', m.group(0))
    tex = html.unescape(latex.group(1)) if latex else ""
    return f" ${tex}$ " if m.group(2).lower() == "inline" else f"\n$${tex}$$\n"


TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.I | re.S)


def _table_text(m):
    """A table from MyNotion as one line per row, cells split by " | " (a cell with several lines stays on its row)."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), flags=re.I | re.S):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.I | re.S)
        rows.append(" | ".join(html_to_text(c).replace("\n", " ") for c in cells))
    return "\n" + "\n".join(rows) + "\n"


def html_to_text(content: str) -> str:
    s = content or ""
    s = MATH_RE.sub(_math_text, s)
    s = TABLE_RE.sub(_table_text, s)
    s = re.sub(r"<sup[^>]*>(.*?)</sup>", r"^\1", s, flags=re.I | re.S)   # m² as m^2 (like the formulas)
    s = re.sub(r"<li[^>]*data-checked=\"true\"[^>]*>", "\n☑ ", s, flags=re.I)
    s = re.sub(r"<li[^>]*data-checked=\"false\"[^>]*>", "\n☐ ", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "\n• ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</h\d>|</li>|</blockquote>|</summary>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def text_to_html(text: str) -> str:
    lines = [l.strip() for l in (text or "").strip().splitlines() if l.strip()]
    bullets = [l for l in lines if re.match(r"^[-•*]\s+", l)]
    if lines and len(bullets) == len(lines):
        return list_html([re.sub(r"^[-•*]\s+", "", l) for l in lines])
    return "".join(f"<p>{html.escape(l)}</p>" for l in lines) or "<p></p>"


def list_html(items) -> str:
    return "<ul>" + "".join(f"<li><p>{html.escape(i)}</p></li>" for i in items) + "</ul>"


def task_item(text: str, checked: bool = False) -> str:
    """One checklist item in the HTML MyNotion's editor (TipTap task list) uses."""
    c = "true" if checked else "false"
    box = '<input type="checkbox" checked="checked">' if checked else '<input type="checkbox">'
    return (f'<li data-checked="{c}" data-type="taskItem"><label>{box}<span></span></label>'
            f'<div><p>{html.escape(text)}</p></div></li>')


def li_text(li_html: str) -> str:
    return html_to_text(li_html).lstrip("•☐☑ ").strip()


def list_items(content: str) -> list:
    return [li_text(m) for m in re.findall(r"<li[^>]*>.*?</li>", content or "", flags=re.S | re.I)]


def card_items(content: str) -> list:
    """[{"text", "checked"}] for the overlay card; checked is None for plain bullets (no checkbox)."""
    out = []
    for li in re.findall(r"<li[^>]*>.*?</li>", content or "", flags=re.S | re.I):
        tag = li[:li.find(">") + 1].lower()
        checked = None
        if 'data-type="taskitem"' in tag:
            checked = 'data-checked="true"' in tag
        text = li_text(li)
        if text:
            out.append({"text": text, "checked": checked})
    return out


def split_items(items) -> list:
    """'eggs, oat milk and bread' / ['eggs', 'milk'] -> ['eggs', 'oat milk', 'bread']"""
    if isinstance(items, (list, tuple)):
        raw = [str(i) for i in items]
    else:
        raw = re.split(r",|;|\n|\band\b|\&", str(items or ""))
    return [i.strip(" .") for i in raw if i.strip(" .")]


# ── Dates & times ─────────────────────────────────────────────────────────────

def parse_day(text, today: dt.date = None) -> dt.date | None:
    """today / tomorrow / friday / next friday / in 3 days / 2026-11-12 / 12.11. / 12 november / november 12"""
    today = today or dt.date.today()
    s = str(text or "").strip().lower().rstrip(".")
    s = re.sub(r"^(on|this|the)\s+", "", s)
    if s in ("", "today", "tonight", "now"):
        return today
    if s == "tomorrow":
        return today + dt.timedelta(days=1)
    if s in ("day after tomorrow", "the day after tomorrow", "overmorrow"):
        return today + dt.timedelta(days=2)
    m = re.fullmatch(r"in (\d+|a|one|two|three) (day|days|week|weeks)", s)
    if m:
        n = {"a": 1, "one": 1, "two": 2, "three": 3}.get(m.group(1)) or int(m.group(1))
        return today + dt.timedelta(days=n * (7 if m.group(2).startswith("week") else 1))
    m = re.fullmatch(r"(next )?(" + "|".join(WEEKDAYS) + r")", s)
    if m:
        ahead = (WEEKDAYS.index(m.group(2)) - today.weekday()) % 7 or 7
        return today + dt.timedelta(days=ahead)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", s)          # 12.11. / 12/11/2026 (day first)
    if m:
        return _with_year(int(m.group(1)), int(m.group(2)), m.group(3), today)
    mon = "|".join(MONTHS + [x[:3] for x in MONTHS])
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?(?: of)? ({mon})(?: (\d{{4}}))?", s) or \
        re.fullmatch(rf"({mon}) (\d{{1,2}})(?:st|nd|rd|th)?(?:,? (\d{{4}}))?", s)
    if m:
        a, b, year = m.group(1), m.group(2), m.group(3)
        day, name = (int(a), b) if a.isdigit() else (int(b), a)
        month = [x[:3] for x in MONTHS].index(name[:3]) + 1
        return _with_year(day, month, year, today)
    return None


def _safe_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _with_year(day, month, year, today):
    if year:
        y = int(year)
        return _safe_date(y + 2000 if y < 100 else y, month, day)
    d = _safe_date(today.year, month, day)
    if d and d < today - dt.timedelta(days=1):       # "12.1." in December means next year
        d = _safe_date(today.year + 1, month, day)
    return d


def parse_time(text) -> float | None:
    """'15:00' / '3pm' / '3:30 pm' / '9.30' / '15h' -> hours as float (15.5)"""
    s = str(text or "").strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?:[:.h](\d{2}))?h?(am|pm|a\.m\.|p\.m\.)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        h = h % 12 + (12 if ap.startswith("p") else 0)
    if h > 23 or mi > 59:
        return None
    return h + mi / 60


def fmt_hour(h) -> str:
    if h is None:
        return ""
    hh, mm = int(h), int(round((h - int(h)) * 60))
    if mm == 60:
        hh, mm = hh + 1, 0
    return f"{hh:02d}:{mm:02d}"


def fmt_day(d: dt.date, today: dt.date = None) -> str:
    today = today or dt.date.today()
    if d == today:
        return "today"
    if d == today + dt.timedelta(days=1):
        return "tomorrow"
    if 0 < (d - today).days < 7:
        return d.strftime("%A")
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


_FILLER_WORDS = {"just", "already", "finally", "done", "with", "that", "this", "have", "the", "some"}


def _repeat_value(text) -> str | None:
    """'weekly' / 'every week' / 'each monday' -> 'weekly' (None if empty or unknown)"""
    s = str(text or "").strip().lower()
    if not s or s in ("none", "no", "once", "never"):
        return None
    for key, words in {"daily": ("daily", "day"), "weekly": ("weekly", "week", "monday", "tuesday", "wednesday",
                       "thursday", "friday", "saturday", "sunday"), "monthly": ("monthly", "month"),
                       "yearly": ("yearly", "annual", "year", "birthday")}.items():
        if any(w in s for w in words):
            return key
    return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9äöüß ]", " ", (s or "").lower()).strip()


def _stem(text: str) -> str:
    """crude singular: pancakes -> pancake, lists -> list (enough for matching titles)"""
    def one(w):
        if len(w) > 4 and w.endswith("es") and w[:-2].endswith(("s", "x", "ch", "sh")):
            return w[:-2]                                   # classes -> class, boxes -> box
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            return w[:-1]                                   # pancakes -> pancake
        return w
    return " ".join(one(w) for w in text.split())


def _match_score(query: str, title: str) -> float:
    q, t = _stem(_norm(query)), _stem(_norm(title))
    if not q or not t:
        return 0
    if q == t:
        return 100
    # prefix / substring matches only count on whole words, so a note called "c#" ("c")
    # doesn't match "packing" and "art" doesn't match "party"
    if re.match(rf"{re.escape(q)}\b", t) or re.match(rf"{re.escape(t)}\b", q):
        return 80
    if re.search(rf"\b{re.escape(q)}\b", t) or re.search(rf"\b{re.escape(t)}\b", q):
        return 60
    qw, tw = set(q.split()) - {"my", "the", "a", "list", "note"}, set(t.split()) - {"list", "note"}
    return 40 * len(qw & tw) / max(1, len(qw)) if qw else 0


# ── Engine ────────────────────────────────────────────────────────────────────

class NotionEngine:
    def __init__(self, db_path: str, confirm=None, user_id=None):
        if not db_path or not os.path.exists(db_path):
            raise FileNotFoundError(f"MyNotion database not found: {db_path}")
        self.db_path = db_path
        self.confirm = confirm
        self.user_id = int(user_id or os.environ.get("NOTION_USER_ID") or 0) or self._find_user()
        self.last_reply = lambda: ""        # set by Aria: her previous answer, for "save that as a note"
        self.on_card = None                 # set by Aria: shows a list/agenda card next to the orb
        self._ensure_repeat_column()

    @contextmanager
    def _conn(self):
        """Commit on success, roll back on error, and always close (MyNotion has the file open too)."""
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _find_user(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT id FROM USERS ORDER BY logged_in DESC, id ASC LIMIT 1").fetchone()
        return row["id"] if row else 1

    # ── notes: low level ──

    def _notes(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM notes WHERE userID = ? ORDER BY updated_at DESC", (self.user_id,))]

    def _find_note(self, title: str):
        if title and THIS_RE.match(title):
            return self.open_note()
        best, score = None, 0
        for n in self._notes():
            s = _match_score(title, n["title"])
            if s > score:
                best, score = n, s
        return best if score >= 30 else None

    def _create_note(self, title: str, content_html: str) -> int:
        with self._conn() as c:
            cur = c.execute("INSERT INTO notes (title, content, categoryID, folderID, userID) VALUES (?, ?, 0, 0, ?)",
                            (title, content_html, self.user_id))
            return cur.lastrowid

    def _set_content(self, note_id: int, content_html: str):
        with self._conn() as c:
            c.execute("UPDATE notes SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                      (content_html, note_id))

    # ── the note open in MyNotion, and editing it safely ──

    @staticmethod
    def is_this(title) -> bool:
        return not (title or "").strip() or bool(THIS_RE.match(title))

    def title_score(self, query, title) -> float:
        return _match_score(query, title)

    def _state(self, key):
        with self._conn() as c:
            c.execute(APP_STATE_SQL)
            row = c.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_state(self, key, value):
        with self._conn() as c:
            c.execute(APP_STATE_SQL)
            c.execute("INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                      (key, value))

    def open_note(self):
        """The note open in MyNotion right now (None if none is, or MyNotion isn't running)."""
        value = self._state("open_note")
        if not value or not str(value).isdigit() or not mynotion_running():
            return None
        n = self._note_by_id(int(value))
        return n if n and n["userID"] in (self.user_id, 0) else None

    def resolve_note(self, title):
        """The note meant by a title, or by "this note" / nothing at all (the one open in MyNotion)."""
        return self.open_note() if self.is_this(title) else self._find_note(title)

    @contextmanager
    def editing(self, note_id: int):
        """While Aria reworks a note, MyNotion shows "Aria is editing…" and doesn't let you type in it."""
        self._set_state("aria_editing", str(note_id))
        try:
            if str(self._state("open_note")) == str(note_id) and mynotion_running():
                time.sleep(EDIT_SETTLE_S)          # what was just typed reaches the database first
            yield
        finally:
            try:
                self._set_state("aria_editing", None)
            except sqlite3.Error as e:
                print(f"[MyNotion] couldn't clear the editing lock: {e}")

    def replace_content(self, note_id: int, old_html: str, new_html: str) -> bool:
        """Save the new version only if the note still is what Aria read (else someone changed it meanwhile)."""
        with self._conn() as c:
            cur = c.execute("UPDATE notes SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND "
                            "COALESCE(content, '') = ?", (new_html, note_id, old_html or ""))
            return cur.rowcount == 1

    # ── notes: tools ──

    def _daily_note(self, create=True):
        title = daily_title()
        n = next((x for x in self._notes() if (x["title"] or "").strip() == title), None)
        if not n and create:
            self._create_note(title, DAILY_TEMPLATE)
            n = next((x for x in self._notes() if (x["title"] or "").strip() == title), None)
        return n

    def add_note(self, text: str, title: str = ""):
        text = (text or "").strip()
        if not text:
            return "What should the note say?"
        if title and DAILY_RE.match(title):
            n = self._daily_note()
            content = n["content"] or ""
            if content.endswith("<h2>Notes</h2><p></p>"):          # fill the template's empty line first
                content = content[:-len("<p></p>")]
            self._set_content(n["id"], content + text_to_html(text))
            return "Added to today's note."
        if title and THIS_RE.match(title):
            n = self.open_note()
            if not n:
                return "Which note? I can't see one open in MyNotion — say its name."
            self._set_content(n["id"], (n["content"] or "") + text_to_html(text))
            return f"Added to '{n['title']}'."
        if title:
            existing = self._find_note(title)
            if existing and _match_score(title, existing["title"]) >= 80:
                self._set_content(existing["id"], (existing["content"] or "") + text_to_html(text))
                return f"Added to your note '{existing['title']}'."
            self._create_note(title.strip(), text_to_html(text))
            return f"Created the note '{title.strip()}'."
        stamp = dt.datetime.now().strftime("%d.%m. %H:%M")
        line = f"<p><strong>{stamp}</strong> {html.escape(text)}</p>"
        inbox = self._find_note(INBOX_TITLE)
        if inbox and _match_score(INBOX_TITLE, inbox["title"]) >= 80:
            self._set_content(inbox["id"], (inbox["content"] or "") + line)
        else:
            self._create_note(INBOX_TITLE, line)
        return "Noted — it's in your Inbox in MyNotion."

    def save_as_note(self, title: str, text: str = ""):
        text = (text or "").strip() or (self.last_reply() or "").strip()
        if not text:
            return "There's nothing to save yet."
        return self.add_note(text, title=title or "Saved from Aria")

    def read_note(self, title: str):
        if DAILY_RE.match(title or ""):
            n = self._daily_note(create=False)
            if not n:
                return "There's no note for today yet."
        else:
            n = self._find_note(title)
        if not n:
            return f"I couldn't find a note called '{title}'. " + self._titles_hint()
        if self._is_list(n):
            self.show_list_card(n)
        body = html_to_text(n["content"]) or "(empty)"
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS] + "\n…[truncated]"
        return f"Note '{n['title']}':\n{body}"

    def list_notes(self):
        notes = self._notes()
        if not notes:
            return "You don't have any notes yet."
        titles = [n["title"] for n in notes[:20]]
        return f"{len(notes)} notes. Most recent: " + ", ".join(titles) + "."

    def search_notes(self, query: str):
        words = [w for w in _norm(query).split() if len(w) > 2] or _norm(query).split()
        if not words:
            return "What should I look for?"
        hits = []
        for n in self._notes():
            text = html_to_text(n["content"])
            low_t, low_x = _norm(n["title"]), text.lower()
            score = sum(3 * low_t.count(w) + low_x.count(w) for w in words)
            if score:
                hits.append((score, n, text))
        if not hits:
            return f"Nothing in your notes about '{query}'."
        hits.sort(key=lambda h: -h[0])
        out = []
        for _, n, text in hits[:3]:
            low = text.lower()
            pos = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
            start = max(0, pos - 150)
            snippet = text[start:start + 450].replace("\n", " / ")
            out.append(f"[{n['title']}] {'…' if start else ''}{snippet}")
        return "From your notes (answer from these):\n" + "\n".join(out)

    def _titles_hint(self):
        titles = [n["title"] for n in self._notes()[:8]]
        return ("Your notes: " + ", ".join(titles) + ".") if titles else ""

    # ── cards for the overlay ──

    def _card(self, card):
        if self.on_card:
            try:
                self.on_card(card)
            except Exception as e:
                print(f"[MyNotion] card failed: {e}")

    def _note_by_id(self, note_id: int):
        with self._conn() as c:
            row = c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return dict(row) if row else None

    def show_list_card(self, note):
        if note:
            self._card({"type": "list", "note_id": note["id"], "title": note["title"],
                        "items": card_items(note["content"])})

    def set_item_checked(self, note_id: int, text: str, checked: bool) -> bool:
        """Tick/untick one item from the overlay card (exact item text, no fuzzy matching)."""
        n = self._note_by_id(note_id)
        if not n:
            return False
        for li in re.findall(r'<li[^>]*data-type="taskItem"[^>]*>.*?</li>', n["content"] or "", flags=re.S | re.I):
            if li_text(li) == text:
                self._set_content(note_id, n["content"].replace(li, task_item(text, checked), 1))
                return True
        return False

    def show_agenda_card(self, start: dt.date, end: dt.date, title: str):
        today = dt.date.today()
        daily, rest = self._split_daily(self._events_between(start, end))
        days = []
        if daily and start != end:
            days.append({"label": "Every day", "events": [self._card_event(e) for e in daily]})
            events = rest
        else:
            events = daily + rest
        for e in sorted(events, key=lambda e: (e["date"], -int(bool(e["allDay"])), e["startHour"] or 0)):
            label = fmt_day(dt.date.fromisoformat(e["date"]), today).capitalize()
            if not days or days[-1]["label"] != label:
                days.append({"label": label, "events": []})
            days[-1]["events"].append(self._card_event(e))
        self._card({"type": "agenda", "title": title, "days": days})

    @staticmethod
    def _card_event(e):
        if e["allDay"] or e["startHour"] is None:
            when = "all day"
        else:
            when = fmt_hour(e["startHour"])
        return {"time": when, "title": e["title"], "repeat": bool(e.get("repeat"))}

    # ── lists ──

    @staticmethod
    def _is_list(note) -> bool:
        return "<ul" in (note.get("content") or "").lower() or "list" in note["title"].lower()

    def _list_note(self, name: str, create: bool):
        """Only ever returns a note that IS a list, so list commands can't write into ordinary notes."""
        candidates = [(_match_score(name, n["title"]), n) for n in self._notes() if self._is_list(n)]
        candidates.sort(key=lambda x: -x[0])
        if candidates and candidates[0][0] >= 30:
            return candidates[0][1]
        if not create:
            return None
        title = name.strip().strip(".").capitalize()
        if "list" not in title.lower():
            title += " list"
        empty = '<ul data-type="taskList"></ul>'
        nid = self._create_note(title, empty)
        return {"id": nid, "title": title, "content": empty}

    def add_to_list(self, list_name: str, items):
        new = split_items(items)
        if not new:
            return "What should I add?"
        n = self._list_note(list_name or "shopping", create=True)
        content = n["content"] or ""
        have = {i.lower() for i in list_items(content)}
        new = [i for i in new if i.lower() not in have]
        if not new:
            return f"That's already on your {n['title']}."
        is_checklist = 'data-type="tasklist"' in content.lower() or "<ul" not in content.lower()
        if is_checklist:
            addition = "".join(task_item(i) for i in new)
            start = content.lower().rfind('<ul data-type="tasklist"')
            idx = content.lower().find("</ul>", start) if start >= 0 else -1
            wrapper = f'<ul data-type="taskList">{addition}</ul>'
        else:
            addition = "".join(f"<li><p>{html.escape(i)}</p></li>" for i in new)
            idx = content.lower().rfind("</ul>")
            wrapper = f"<ul>{addition}</ul>"
        content = content[:idx] + addition + content[idx:] if idx >= 0 else content + wrapper
        self._set_content(n["id"], content)
        self.show_list_card({**n, "content": content})
        return f"Added {', '.join(new)} to your {n['title']}."

    def remove_from_list(self, list_name: str, items):
        n = self._list_note(list_name or "shopping", create=False)
        if not n:
            return f"I couldn't find a list called '{list_name}'."
        content, removed = n["content"] or "", []
        for item in split_items(items):
            for li in re.findall(r"<li[^>]*>.*?</li>", content, flags=re.S | re.I):
                text = li_text(li)
                if _match_score(item, split_due(text)[0]) >= 60:
                    content = content.replace(li, "", 1)
                    removed.append(text)
                    break
        if not removed:
            return f"None of that is on your {n['title']}."
        self._set_content(n["id"], content)
        self.show_list_card({**n, "content": content})
        return f"Removed {', '.join(removed)} from your {n['title']}."

    def clear_list(self, list_name: str):
        n = self._list_note(list_name or "shopping", create=False)
        if not n:
            return f"I couldn't find a list called '{list_name}'."
        count = len(list_items(n["content"]))
        if not count:
            return f"Your {n['title']} is already empty."

        def do():
            self._set_content(n["id"], '<ul data-type="taskList"></ul>')
            return f"Cleared your {n['title']}."
        return self.confirm.request(f"clear all {count} items from {n['title']}", do) if self.confirm else do()

    def check_off(self, items, list_name: str = "", done: bool = True):
        """Tick (or untick) checklist items. Without a list name, looks through all checklists."""
        done = str(done).lower() not in ("false", "0", "no")
        wanted = split_items(items)
        if not wanted:
            return "Which item?"
        if list_name:
            n = self._list_note(list_name, create=False)
            pool = [n] if n else []
        else:
            pool = [n for n in self._notes() if 'data-type="tasklist"' in (n["content"] or "").lower()]
        if not pool:
            return "I couldn't find that list." if list_name else "You don't have any checklists yet."
        changed = []
        for item in wanted:
            best = None
            for n in pool:
                for li in re.findall(r'<li[^>]*data-type="taskItem"[^>]*>.*?</li>', n["content"] or "", flags=re.S | re.I):
                    score = _match_score(item, split_due(li_text(li))[0])
                    if score >= 60 and (not best or score > best[0]):
                        best = (score, n, li)
            if not best:
                # "I paid the rent" vs "pay rent": accept one shared meaningful word if it points to a single item
                words = {w for w in _stem(_norm(item)).split() if len(w) > 3 and w not in _FILLER_WORDS}
                hits = [(n, li) for n in pool
                        for li in re.findall(r'<li[^>]*data-type="taskItem"[^>]*>.*?</li>', n["content"] or "", flags=re.S | re.I)
                        if words & set(_stem(_norm(split_due(li_text(li))[0])).split())]
                if len(hits) == 1:
                    best = (50, *hits[0])
            if best:
                _, n, li = best
                n["content"] = n["content"].replace(li, task_item(li_text(li), done), 1)
                changed.append((n, li_text(li)))
        if not changed:
            return f"I couldn't find {', '.join(wanted)} on your checklists."
        for n in {id(n): n for n, _ in changed}.values():
            self._set_content(n["id"], n["content"])
        self.show_list_card(changed[-1][0])
        names = ", ".join(t for _, t in changed)
        return f"Ticked off {names}." if done else f"Unticked {names}."

    def _open_todos(self):
        """Unticked items on to-do/task lists (not the shopping list etc.) that have no due date."""
        return [text for _, text in self.open_todo_items() if not split_due(text)[1]]

    # ── to-dos with due dates (Engines/DueDates.py) ──

    TASK_LI = r'<li[^>]*data-type="taskItem"[^>]*>.*?</li>'

    def due_items(self, include_done=False):
        """[{note, li, text, day, done}] for every checklist item with a due date, soonest first."""
        out = []
        for n in self._notes():
            for li in re.findall(self.TASK_LI, n["content"] or "", flags=re.S | re.I):
                done = 'data-checked="true"' in li[:li.find(">")].lower()
                if done and not include_done:
                    continue
                text, day = split_due(li_text(li))
                if day:
                    out.append({"note": n, "li": li, "text": text, "day": day, "done": done})
        return sorted(out, key=lambda x: x["day"])

    def _find_task(self, item: str, open_only=True):
        """(note, li) of the checklist item that best matches item, or (None, None)."""
        best = (0, None, None)
        for n in self._notes():
            for li in re.findall(self.TASK_LI, n["content"] or "", flags=re.S | re.I):
                if open_only and 'data-checked="true"' in li[:li.find(">")].lower():
                    continue
                score = _match_score(item, split_due(li_text(li))[0])
                if score > best[0]:
                    best = (score, n, li)
        return (best[1], best[2]) if best[0] >= 60 else (None, None)

    def add_todo(self, task: str, due: str = "", list_name: str = ""):
        """One to-do, optionally with a due date. Not split at 'and' (unlike add_to_list): 'call mum and dad'."""
        task = (task or "").strip().strip(".")
        if not due:
            task, due = strip_by_phrase(task)          # the model sometimes leaves "by friday" in the task
        task = re.sub(r"^(?:to\s+|that i (?:have|need) to\s+|i (?:have|need) to\s+)", "", task, flags=re.I).strip()
        if not task:
            return "What's the to-do?"
        day = None
        if due and str(due).strip().lower() not in ("none", "no", ""):
            day = parse_day(due)
            if not day:
                return f"I didn't get the date '{due}'. Say it like 'friday' or '20 november'."
        task = task[:1].upper() + task[1:]
        n, li = self._find_task(task)
        if n and _match_score(task, split_due(li_text(li))[0]) >= 90:
            if not day:
                return f"'{split_due(li_text(li))[0]}' is already on your {n['title']}."
            return self.set_due(task, due)
        n = self._list_note(list_name or "to-do", create=True)
        content = n["content"] or ""
        addition = task_item(with_due(task, day))
        start = content.lower().rfind('<ul data-type="tasklist"')
        idx = content.lower().find("</ul>", start) if start >= 0 else -1
        content = content[:idx] + addition + content[idx:] if idx >= 0 else content + f'<ul data-type="taskList">{addition}</ul>'
        self._set_content(n["id"], content)
        self.show_list_card({**n, "content": content})
        if day:
            return f"Added '{task}' to your {n['title']}, due {say_due(day)}."
        return f"Added '{task}' to your {n['title']}."

    def set_due(self, item: str, due: str = ""):
        """Give a to-do a due date, move it ('the essay is due monday now'), or remove it (due = 'none')."""
        n, li = self._find_task(item)
        if not n:
            return f"I couldn't find an open to-do like '{item}'."
        text = li_text(li)
        clear = str(due or "").strip().lower() in ("", "none", "no", "remove", "no date", "never")
        day = None if clear else parse_day(due)
        if not clear and not day:
            return f"I didn't get the date '{due}'."
        new = task_item(with_due(text, day), False)
        content = n["content"].replace(li, new, 1)
        self._set_content(n["id"], content)
        self.show_list_card({**n, "content": content})
        base = split_due(text)[0]
        return f"'{base}' has no due date now." if clear else f"'{base}' is due {say_due(day)} now."

    def get_due(self, when: str = "this week"):
        """What's due: overdue items always, plus everything up to the end of `when`."""
        today = dt.date.today()
        w = (when or "this week").strip().lower()
        if w in ("all", "everything", "anything", "ever"):
            end = dt.date.max
        elif "next week" in w:
            end = today + dt.timedelta(days=13 - today.weekday())
        elif "week" in w:
            end = today + dt.timedelta(days=6)
        elif "month" in w:
            end = today + dt.timedelta(days=31)
        else:
            end = parse_day(w) or today + dt.timedelta(days=6)
        items = [x for x in self.due_items() if x["day"] <= end]
        if not items:
            return "Nothing's due " + ("at all." if end == dt.date.max else "then.") + \
                (" Your open to-dos have no dates." if self._open_todos() else "")
        late = [x for x in items if x["day"] < today]
        rest = [x for x in items if x["day"] >= today]
        parts = []
        if late:
            parts.append("Overdue: " + "; ".join(f"{x['text']} (was due {say_due(x['day'])})" for x in late))
        if rest:
            parts.append("Due: " + "; ".join(f"{x['text']} {say_due(x['day'])}" for x in rest))
        notes = {x["note"]["id"]: x["note"] for x in items}
        if len(notes) == 1:
            self.show_list_card(next(iter(notes.values())))
        return ". ".join(parts) + "."

    def open_todo_items(self):
        """[(list title, item text)] for unticked items on to-do/task lists."""
        out = []
        for n in self._notes():
            if not re.search(r"to-?do|task", n["title"], re.I):
                continue
            for li in re.findall(r'<li[^>]*data-checked="false"[^>]*>.*?</li>', n["content"] or "", flags=re.S | re.I):
                out.append((n["title"], li_text(li)))
        return out

    # ── calendar ──

    def _ensure_repeat_column(self):
        """MyNotion adds this too; whichever starts first creates it."""
        with self._conn() as c:
            cols = [r["name"] for r in c.execute("PRAGMA table_info(EVENTS)")]
            if cols and "repeat" not in cols:
                c.execute("ALTER TABLE EVENTS ADD COLUMN repeat TEXT DEFAULT NULL")

    @staticmethod
    def _occurs_on(e, day: dt.date) -> bool:
        first = dt.date.fromisoformat(e["date"])
        rep = e.get("repeat")
        if not rep:
            return day == first
        if day < first:
            return False
        return {"daily": True,
                "weekly": day.weekday() == first.weekday(),
                "monthly": day.day == first.day,
                "yearly": (day.month, day.day) == (first.month, first.day)}.get(rep, False)

    def _events_between(self, start: dt.date, end: dt.date):
        """Events in [start, end], with repeating events expanded into one entry per day they happen."""
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM EVENTS WHERE userID = ? AND date <= ? AND (date >= ? OR repeat IS NOT NULL)",
                (self.user_id, end.isoformat(), start.isoformat()))]
        out = []
        day = start
        while day <= end:
            for e in rows:
                if self._occurs_on(e, day):
                    out.append({**e, "date": day.isoformat(), "first_date": e["date"]})
            day += dt.timedelta(days=1)
        out.sort(key=lambda e: (e["date"], -int(bool(e["allDay"])), e["startHour"] or 0))
        return out

    REPEAT_WORDS = {"daily": "every day", "weekly": "every week", "monthly": "every month", "yearly": "every year"}

    @classmethod
    def _fmt_event(cls, e, today=None, with_day=True) -> str:
        d = dt.date.fromisoformat(e["date"])
        day = fmt_day(d, today) + " " if with_day else ""
        rep = f" ({cls.REPEAT_WORDS[e['repeat']]})" if e.get("repeat") in cls.REPEAT_WORDS else ""
        if e["allDay"] or e["startHour"] is None:
            return f"{day}(all day) {e['title']}{rep}"
        end = f"–{fmt_hour(e['startHour'] + e['duration'])}" if e.get("duration") else ""
        return f"{day}{fmt_hour(e['startHour'])}{end} {e['title']}{rep}"

    def get_events(self, when: str = "this week"):
        today = dt.date.today()
        w = (when or "this week").strip().lower()
        if w in ("week", "this week", "the week", "upcoming", "coming up", "next 7 days", "soon"):
            start, end, label = today, today + dt.timedelta(days=6), "in the next 7 days"
        elif w == "next week":
            start = today + dt.timedelta(days=7 - today.weekday())
            end, label = start + dt.timedelta(days=6), "next week"
        elif w in ("weekend", "this weekend", "the weekend"):
            start = today + dt.timedelta(days=(5 - today.weekday()) % 7)
            end, label = start + dt.timedelta(days=1), "this weekend"
        elif w in ("month", "this month", "next 30 days"):
            start, end, label = today, today + dt.timedelta(days=30), "in the next 30 days"
        else:
            day = parse_day(w, today)
            if not day:
                return f"I couldn't understand the day '{when}'."
            start = end = day
            label = fmt_day(day, today)
        events = self._events_between(start, end)
        self.show_agenda_card(start, end, re.sub(r"^in the ", "", label).capitalize())
        if not events:
            return f"Nothing in your calendar {label}."
        single = start == end
        if single:
            return f"Calendar {label}: " + "; ".join(self._fmt_event(e, today, with_day=False) for e in events) + "."
        daily, rest = self._split_daily(events)
        parts = [f"every day {self._fmt_event(e, today, with_day=False).replace(' (every day)', '')}" for e in daily]
        parts += [self._fmt_event(e, today) for e in rest]
        return f"Calendar {label}: " + "; ".join(parts) + "."

    @staticmethod
    def _split_daily(events):
        """Daily events once (not 7 times in a week view), everything else as is."""
        daily, seen, rest = [], set(), []
        for e in events:
            if e.get("repeat") == "daily":
                if e["id"] not in seen:
                    seen.add(e["id"])
                    daily.append(e)
            else:
                rest.append(e)
        return daily, rest

    def add_event(self, title: str, date: str, time: str = "", duration_hours=1, repeat: str = ""):
        title = (title or "").strip()
        if not title:
            return "What's the event called?"
        # "monday and thursday" / "mondays, wednesdays" -> one event per weekday (weekly unless told otherwise)
        days = [d for d in WEEKDAYS if re.search(rf"\b{d}s?\b", str(date or "").lower())]
        if len(days) > 1:
            results = [self.add_event(title, d, time, duration_hours, repeat or "weekly") for d in days]
            ok = [r for r in results if r.startswith("Added")]
            if len(ok) == len(results):
                every = "every " if _repeat_value(repeat or "weekly") == "weekly" else ""
                names = " and ".join(d.capitalize() for d in days)
                at = f" at {fmt_hour(parse_time(time))}" if time and parse_time(time) is not None else ""
                return f"Added '{title}' {every}{names}{at}. I'll remind you {EVENT_REMINDER_MIN} minutes before each one."
            return " ".join(results)
        day = parse_day(date)
        if not day:
            return f"I couldn't understand the date '{date}'. Say e.g. 'friday' or '12.11.'."
        start = parse_time(time) if time else None
        if time and start is None:
            return f"I couldn't understand the time '{time}'. Use HH:MM."
        all_day = start is None
        duration = None if all_day else max(0.25, float(duration_hours or 1))
        rep = _repeat_value(repeat)
        if repeat and rep is None and str(repeat).strip().lower() not in ("none", "no", "once", "never"):
            return f"I can repeat events daily, weekly, monthly or yearly — not '{repeat}'."
        if not repeat and YEARLY_RE.search(title):
            rep = "yearly"                  # birthdays come back every year
        clash = self._conflicts(day, start, duration)
        with self._conn() as c:
            c.execute("INSERT INTO EVENTS (date, startHour, duration, title, color, allDay, userID, repeat) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (day.isoformat(), start, duration, title,
                       None if all_day else ARIA_EVENT_COLOR, 1 if all_day else 0, self.user_id, rep))
        when = f"{fmt_day(day)} ({day.strftime('%d.%m.')})"
        if rep:
            when = f"{self.REPEAT_WORDS[rep]} from {when}"
        if all_day:
            return f"Added '{title}' {when} as an all-day event."
        note = " MyNotion's week view only shows 08:00–23:00." if start < 8 else ""
        return (f"Added '{title}' {when} at {fmt_hour(start)} for {duration:g} h. "
                f"I'll remind you {EVENT_REMINDER_MIN} minutes before.{note}{clash}")

    def _conflicts(self, day: dt.date, start, duration, exclude_id=None) -> str:
        """' Heads up: that overlaps with …' for timed events on that day that overlap [start, start+duration)."""
        if start is None:
            return ""
        end = start + (duration or 1)
        clash = [e for e in self._events_between(day, day)
                 if e["id"] != exclude_id and not e["allDay"] and e["startHour"] is not None
                 and e["startHour"] < end and start < e["startHour"] + (e["duration"] or 1)]
        if not clash:
            return ""
        names = " and ".join(f"{e['title']} at {fmt_hour(e['startHour'])}" for e in clash[:2])
        return f" Heads up: that overlaps with {names}."

    def _find_event(self, title: str, date: str = ""):
        today = dt.date.today()
        if date:
            day = parse_day(date)
            pool = self._events_between(day, day) if day else []
        else:
            pool = self._events_between(today, today + dt.timedelta(days=60))
        scored = sorted(((_match_score(title, e["title"]), e) for e in pool), key=lambda x: -x[0])
        return scored[0][1] if scored and scored[0][0] >= 30 else None

    def move_event(self, title: str, new_date: str = "", new_time: str = "", date: str = ""):
        e = self._find_event(title, date)
        if not e:
            return f"I couldn't find an upcoming event matching '{title}'."
        day = parse_day(new_date) if new_date else dt.date.fromisoformat(e["date"])
        if not day:
            return f"I couldn't understand the date '{new_date}'."
        start = parse_time(new_time) if new_time else e["startHour"]
        if new_time and start is None:
            return f"I couldn't understand the time '{new_time}'."
        all_day = start is None
        old = self._fmt_event(e)

        def do():
            with self._conn() as c:
                c.execute("UPDATE EVENTS SET date = ?, startHour = ?, allDay = ?, duration = ? WHERE id = ?",
                          (day.isoformat(), start, 1 if all_day else 0,
                           None if all_day else (e["duration"] or 1), e["id"]))
            return (f"Moved '{e['title']}' to {fmt_day(day)}" + ("" if all_day else f" at {fmt_hour(start)}") + "."
                    + self._conflicts(day, start, e["duration"] or 1, exclude_id=e["id"]))
        target = fmt_day(day) + ("" if all_day else f" at {fmt_hour(start)}")
        return self.confirm.request(f"move '{old}' to {target}", do) if self.confirm else do()

    def delete_event(self, title: str, date: str = ""):
        e = self._find_event(title, date)
        if not e:
            return f"I couldn't find an upcoming event matching '{title}'."

        def do():
            with self._conn() as c:
                c.execute("DELETE FROM EVENTS WHERE id = ?", (e["id"],))
            return f"Deleted '{e['title']}'" + (" and all its repeats." if e.get("repeat") else ".")
        what = f"'{self._fmt_event(e)}'" + (" (the whole series)" if e.get("repeat") else "")
        return self.confirm.request(f"delete {what} from your calendar", do) if self.confirm else do()

    # ── open things in the MyNotion app ──

    def has_note(self, title: str) -> bool:
        """Confident match only (used to decide that 'open X' means a MyNotion note)."""
        n = self._find_note(title)
        return bool(n) and _match_score(title, n["title"]) >= 80

    def open_mynotion(self, what: str = ""):
        """Start MyNotion (or bring it forward) on the calendar, a note, or its home page."""
        if not os.path.exists(MYNOTION_BIN):
            return "MyNotion isn't built yet — run build_app.sh in the MyNotion folder."
        w = _norm(what)
        if w in ("", "mynotion", "my notion", "notion", "notes", "home", "app"):
            target, said = "home", "MyNotion"
        elif any(k in w for k in ("calendar", "schedule", "agenda", "week", "events")):
            target, said = "calendar", "your calendar"
        elif DAILY_RE.match(what or ""):
            n = self._daily_note()                     # made from the template if it isn't there yet
            target, said = f"note:{n['id']}", "today's note"
        else:
            n = self._find_note(what)
            if not n:
                return f"I couldn't find a note called '{what}'. " + self._titles_hint()
            target, said = f"note:{n['id']}", f"'{n['title']}'"
        # a running MyNotion receives this and focuses itself; the new process exits right away
        subprocess.Popen([MYNOTION_BIN, f"--open={target}"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return "Opening MyNotion." if target == "home" else f"Opening {said} in MyNotion."

    # ── older versions from MyNotion's daily backups ──
    # MyNotion copies its database once a day to backups/noted-YYYY-MM-DD.db (made when the app starts). These are
    # only ever opened read-only; a restore goes through the yes/no confirmation (and "undo that" works after it).

    def _backups(self):
        folder = os.path.join(os.path.dirname(self.db_path), "backups")
        out = []
        try:
            for name in os.listdir(folder):
                m = re.fullmatch(r"noted-(\d{4}-\d{2}-\d{2})\.db", name)
                if m:
                    out.append((dt.date.fromisoformat(m.group(1)), os.path.join(folder, name)))
        except OSError:
            pass
        return sorted(out, reverse=True)                                   # newest first

    @staticmethod
    def _backup_notes(path):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT id, title, content, userID FROM notes")]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def _old_version(self, title, current, before: dt.date):
        """The newest backup taken on or before `before` that has this note (by id, else by title) with different
        text. Returns (backup date, note) or None."""
        for day, path in self._backups():
            if day > before:
                continue
            notes = [n for n in self._backup_notes(path) if n["userID"] in (self.user_id, 0)]
            old = next((n for n in notes if current and n["id"] == current["id"]), None)
            if not old:
                best, score = None, 0
                for n in notes:
                    sc = _match_score(title, n["title"])
                    if sc > score:
                        best, score = n, sc
                old = best if score >= 60 else None
            if old and (not current or (old["content"] or "") != (current["content"] or "")):
                return day, old
        return None

    def restore_note(self, title: str, day: str = "yesterday"):
        """Tool: bring back an older version of a note (or a deleted note) from MyNotion's daily backups."""
        if not self._backups():
            return "There are no backups yet (MyNotion makes one a day when it's open)."
        before = parse_day(day or "yesterday") or dt.date.today() - dt.timedelta(days=1)
        if before > dt.date.today():
            before = dt.date.today()
        current = self._find_note(title)
        if current and _match_score(title, current["title"]) < 60:
            current = None
        found = self._old_version(title, current, before)
        if not found:
            what = f"'{current['title']}'" if current else f"a note called '{title}'"
            return f"I couldn't find an older version of {what} in the backups (up to {fmt_day(before)})."
        when, old = found
        words = lambda html_: len(html_to_text(html_ or "").split())
        if current:
            def do():
                self._set_content(current["id"], old["content"] or "")
                return f"Restored '{current['title']}' to how it was on {fmt_day(when)}."
            ask = (f"replace '{current['title']}' ({words(current['content'])} words now) with the version from "
                   f"{fmt_day(when)} ({words(old['content'])} words)")
        else:
            def do():
                self._create_note(old["title"], old["content"] or "")
                return f"Brought back '{old['title']}' from {fmt_day(when)}."
            ask = f"bring back the deleted note '{old['title']}' from {fmt_day(when)} ({words(old['content'])} words)"
        return self.confirm.request(ask, do) if self.confirm else do()

    # ── reminders for events ──

    def sync_event_reminders(self, reminders):
        """Keep one 'event' reminder per timed event in the next 24 h, EVENT_REMINDER_MIN before it.
        Stateless: compares what should exist with what's pending, so moved/deleted events are handled."""
        now = time.time()
        today = dt.date.today()
        wanted = {}
        for e in self._events_between(today, today + dt.timedelta(days=1)):
            if e["allDay"] or e["startHour"] is None:
                continue
            start = dt.datetime.combine(dt.date.fromisoformat(e["date"]), dt.time()) + \
                dt.timedelta(hours=float(e["startHour"]))
            due = start.timestamp() - EVENT_REMINDER_MIN * 60
            if due > now:
                wanted[(e["title"], round(due))] = due
        have = {(r["text"], round(r["due"])): r for r in reminders.pending(("event",))}
        for key, r in have.items():
            if key not in wanted:
                reminders.cancel_id(r["id"])
        for (title, k), due in wanted.items():
            if (title, k) not in have:
                reminders.add(title, "event", due)
        self._sync_day_ahead(reminders, now, today)
        self._sync_due(reminders, now, today)

    def _sync_due(self, reminders, now, today):
        """Open to-dos due tomorrow: a heads-up at EVENING_HOUR today. Gone when ticked off or moved."""
        wanted = {}
        tomorrow = today + dt.timedelta(days=1)
        evening = dt.datetime.combine(today, dt.time(EVENING_HOUR)).timestamp()
        for x in self.due_items():
            if x["day"] == tomorrow and evening > now:
                wanted[(x["text"], round(evening))] = evening
        have = {(r["text"], round(r["due"])): r for r in reminders.pending(("due",))}
        for key, r in have.items():
            if key not in wanted:
                reminders.cancel_id(r["id"])
        for (text, k), due in wanted.items():
            if (text, k) not in have:
                reminders.add(text, "due", due)

    @staticmethod
    def _is_special(e) -> bool:
        return bool(e["allDay"] or e["startHour"] is None) and (e.get("repeat") == "yearly" or YEARLY_RE.search(e["title"]))

    def _sync_day_ahead(self, reminders, now, today):
        """Birthdays and other yearly all-day days: a heads-up at DAY_AHEAD_HOUR the day before."""
        wanted = {}
        for e in self._events_between(today + dt.timedelta(days=1), today + dt.timedelta(days=2)):
            if not self._is_special(e):
                continue
            day = dt.date.fromisoformat(e["date"])
            due = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(DAY_AHEAD_HOUR)).timestamp()
            if due > now:
                wanted[(e["title"], round(due))] = due
        have = {(r["text"], round(r["due"])): r for r in reminders.pending(("dayahead",))}
        for key, r in have.items():
            if key not in wanted:
                reminders.cancel_id(r["id"])
        for (title, k), due in wanted.items():
            if (title, k) not in have:
                reminders.add(title, "dayahead", due)

    # ── daily briefing ──

    def daily_briefing(self, reminders=None):
        """Facts for the morning briefing: today, what's coming up, open reminders, inbox."""
        today = dt.date.today()
        now_h = dt.datetime.now().hour + dt.datetime.now().minute / 60
        parts = [f"Today is {today.strftime('%A')} {today.day} {today.strftime('%B')}, "
                 f"it is {dt.datetime.now().strftime('%H:%M')} now."]

        todays = self._events_between(today, today)
        upcoming = [e for e in todays if e["allDay"] or (e["startHour"] or 0) + (e["duration"] or 0) > now_h]
        if upcoming:
            parts.append("Today: " + "; ".join(self._fmt_event(e, today, with_day=False) for e in upcoming) + ".")
        else:
            parts.append("Nothing else in the calendar today.")

        _, later = self._split_daily(self._events_between(today + dt.timedelta(days=1), today + dt.timedelta(days=6)))
        if later:
            parts.append("Coming up: " + "; ".join(self._fmt_event(e, today) for e in later[:4]) + ".")
        special = [e for e in self._events_between(today + dt.timedelta(days=1), today + dt.timedelta(days=14))
                   if self._is_special(e)]
        if special:
            parts.append("Special days ahead: " + "; ".join(
                f"{e['title']} in {(dt.date.fromisoformat(e['date']) - today).days} days"
                if (dt.date.fromisoformat(e['date']) - today).days > 1 else f"{e['title']} tomorrow"
                for e in special[:3]) + " (maybe mention a gift or plan if it's a birthday).")

        if reminders:
            rem = [r for r in reminders.pending(("reminder", "timer"))
                   if dt.date.fromtimestamp(r["due"]) == today]
            if rem:
                parts.append("Reminders today: " + "; ".join(
                    f"{r['text']} at {dt.datetime.fromtimestamp(r['due']).strftime('%H:%M')}" for r in rem) + ".")

        due = self.due_items()
        late = [x for x in due if x["day"] < today]
        now_due = [x for x in due if x["day"] == today]
        soon = [x for x in due if today < x["day"] <= today + dt.timedelta(days=SOON_DAYS)]
        if late:
            parts.append("Overdue: " + "; ".join(f"{x['text']} (was due {say_due(x['day'], today)})" for x in late[:3]) + ".")
        if now_due:
            parts.append("Due today: " + "; ".join(x["text"] for x in now_due[:3]) + ".")
        if soon:
            parts.append("Due soon: " + "; ".join(f"{x['text']} {say_due(x['day'], today)}" for x in soon[:3]) + ".")

        todos = self._open_todos()
        if todos:
            shown = ", ".join(todos[:3]) + (f" and {len(todos) - 3} more" if len(todos) > 3 else "")
            parts.append(f"Open to-dos: {shown}.")

        inbox = self._find_note(INBOX_TITLE)
        if inbox and _match_score(INBOX_TITLE, inbox["title"]) >= 80:
            lines = [l for l in html_to_text(inbox["content"]).splitlines() if l.strip()]
            if lines:
                parts.append(f"Inbox has {len(lines)} note{'s' if len(lines) != 1 else ''}, latest: {lines[-1]}.")
        return " ".join(parts)
