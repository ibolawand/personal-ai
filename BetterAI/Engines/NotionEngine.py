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

EVENT_REMINDER_MIN = 15          # announce events this many minutes before they start
ARIA_EVENT_COLOR = "purple"      # MyNotion's calendar colours: blue, green, purple, red
INBOX_TITLE = "Inbox"
# the packaged app (MyNotion: build_app.sh); override with MYNOTION_BIN in Engines/.env
MYNOTION_BIN = os.environ.get("MYNOTION_BIN") or str(
    Path(__file__).resolve().parents[3] / "MyNotion" / "note" / "out" / "MyNotion-linux-x64" / "MyNotion")
MAX_READ_CHARS = 2500

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


# ── Text <-> TipTap HTML ──────────────────────────────────────────────────────

def html_to_text(content: str) -> str:
    s = content or ""
    s = re.sub(r"<li[^>]*>", "\n• ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</h\d>|</li>|</blockquote>", "\n", s, flags=re.I)
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


def list_items(content: str) -> list:
    return [html_to_text(m) for m in re.findall(r"<li[^>]*>(.*?)</li>", content or "", flags=re.S | re.I)]


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

    # ── notes: tools ──

    def add_note(self, text: str, title: str = ""):
        text = (text or "").strip()
        if not text:
            return "What should the note say?"
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
        n = self._find_note(title)
        if not n:
            return f"I couldn't find a note called '{title}'. " + self._titles_hint()
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
        nid = self._create_note(title, "<ul></ul>")
        return {"id": nid, "title": title, "content": "<ul></ul>"}

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
        addition = "".join(f"<li><p>{html.escape(i)}</p></li>" for i in new)
        idx = content.lower().rfind("</ul>")
        content = content[:idx] + addition + content[idx:] if idx >= 0 else content + f"<ul>{addition}</ul>"
        self._set_content(n["id"], content)
        return f"Added {', '.join(new)} to your {n['title']}."

    def remove_from_list(self, list_name: str, items):
        n = self._list_note(list_name or "shopping", create=False)
        if not n:
            return f"I couldn't find a list called '{list_name}'."
        content, removed = n["content"] or "", []
        for item in split_items(items):
            for li in re.findall(r"<li[^>]*>.*?</li>", content, flags=re.S | re.I):
                li_text = html_to_text(li).lstrip("• ").strip()
                if _match_score(item, li_text) >= 60:
                    content = content.replace(li, "", 1)
                    removed.append(li_text)
                    break
        if not removed:
            return f"None of that is on your {n['title']}."
        self._set_content(n["id"], content)
        return f"Removed {', '.join(removed)} from your {n['title']}."

    def clear_list(self, list_name: str):
        n = self._list_note(list_name or "shopping", create=False)
        if not n:
            return f"I couldn't find a list called '{list_name}'."
        count = len(list_items(n["content"]))
        if not count:
            return f"Your {n['title']} is already empty."

        def do():
            self._set_content(n["id"], "<ul></ul>")
            return f"Cleared your {n['title']}."
        return self.confirm.request(f"clear all {count} items from {n['title']}", do) if self.confirm else do()

    # ── calendar ──

    def _events_between(self, start: dt.date, end: dt.date):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM EVENTS WHERE userID = ? AND date BETWEEN ? AND ? "
                "ORDER BY date, allDay DESC, COALESCE(startHour, 0)",
                (self.user_id, start.isoformat(), end.isoformat())).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _fmt_event(e, today=None, with_day=True) -> str:
        d = dt.date.fromisoformat(e["date"])
        day = fmt_day(d, today) + " " if with_day else ""
        if e["allDay"] or e["startHour"] is None:
            return f"{day}(all day) {e['title']}"
        end = f"–{fmt_hour(e['startHour'] + e['duration'])}" if e.get("duration") else ""
        return f"{day}{fmt_hour(e['startHour'])}{end} {e['title']}"

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
        if not events:
            return f"Nothing in your calendar {label}."
        single = start == end
        return f"Calendar {label}: " + "; ".join(self._fmt_event(e, today, with_day=not single) for e in events) + "."

    def add_event(self, title: str, date: str, time: str = "", duration_hours=1):
        title = (title or "").strip()
        if not title:
            return "What's the event called?"
        day = parse_day(date)
        if not day:
            return f"I couldn't understand the date '{date}'. Say e.g. 'friday' or '12.11.'."
        start = parse_time(time) if time else None
        if time and start is None:
            return f"I couldn't understand the time '{time}'. Use HH:MM."
        all_day = start is None
        duration = None if all_day else max(0.25, float(duration_hours or 1))
        with self._conn() as c:
            c.execute("INSERT INTO EVENTS (date, startHour, duration, title, color, allDay, userID) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (day.isoformat(), start, duration, title,
                       None if all_day else ARIA_EVENT_COLOR, 1 if all_day else 0, self.user_id))
        when = f"{fmt_day(day)} ({day.strftime('%d.%m.')})"
        if all_day:
            return f"Added '{title}' {when} as an all-day event."
        note = " MyNotion's week view only shows 08:00–23:00." if start < 8 else ""
        return f"Added '{title}' {when} at {fmt_hour(start)} for {duration:g} h. I'll remind you {EVENT_REMINDER_MIN} minutes before.{note}"

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
            return f"Moved '{e['title']}' to {fmt_day(day)}" + ("" if all_day else f" at {fmt_hour(start)}") + "."
        target = fmt_day(day) + ("" if all_day else f" at {fmt_hour(start)}")
        return self.confirm.request(f"move '{old}' to {target}", do) if self.confirm else do()

    def delete_event(self, title: str, date: str = ""):
        e = self._find_event(title, date)
        if not e:
            return f"I couldn't find an upcoming event matching '{title}'."

        def do():
            with self._conn() as c:
                c.execute("DELETE FROM EVENTS WHERE id = ?", (e["id"],))
            return f"Deleted '{e['title']}'."
        return self.confirm.request(f"delete '{self._fmt_event(e)}' from your calendar", do) if self.confirm else do()

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
        else:
            n = self._find_note(what)
            if not n:
                return f"I couldn't find a note called '{what}'. " + self._titles_hint()
            target, said = f"note:{n['id']}", f"'{n['title']}'"
        # a running MyNotion receives this and focuses itself; the new process exits right away
        subprocess.Popen([MYNOTION_BIN, f"--open={target}"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return "Opening MyNotion." if target == "home" else f"Opening {said} in MyNotion."

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

        later = self._events_between(today + dt.timedelta(days=1), today + dt.timedelta(days=6))
        if later:
            parts.append("Coming up: " + "; ".join(self._fmt_event(e, today) for e in later[:4]) + ".")

        if reminders:
            rem = [r for r in reminders.pending(("reminder", "timer"))
                   if dt.date.fromtimestamp(r["due"]) == today]
            if rem:
                parts.append("Reminders today: " + "; ".join(
                    f"{r['text']} at {dt.datetime.fromtimestamp(r['due']).strftime('%H:%M')}" for r in rem) + ".")

        inbox = self._find_note(INBOX_TITLE)
        if inbox and _match_score(INBOX_TITLE, inbox["title"]) >= 80:
            lines = [l for l in html_to_text(inbox["content"]).splitlines() if l.strip()]
            if lines:
                parts.append(f"Inbox has {len(lines)} note{'s' if len(lines) != 1 else ''}, latest: {lines[-1]}.")
        return " ".join(parts)
