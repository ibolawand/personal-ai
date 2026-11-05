"""
aria_memo.py — Unified Memory System for ARIA
===============================================
Everything in one DB:
  - Facts about the user
  - Message history
  - Mood / emotion log
  - Topic tracking
  - Session tracking
  - Face profiles (name + label ID + sample paths)
"""

import sqlite3
import datetime
import threading
import time

import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aria_memory.db")


class AriaMemory:
    def __init__(self):
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact      TEXT UNIQUE,
                    created   TEXT DEFAULT (datetime('now')),
                    hits      INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    role      TEXT,
                    content   TEXT,
                    ts        TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS mood_log (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    hour      INTEGER,
                    weekday   INTEGER,
                    mood      TEXT,
                    ts        TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS topics (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic     TEXT UNIQUE,
                    count     INTEGER DEFAULT 1,
                    last_seen TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    started    TEXT DEFAULT (datetime('now')),
                    ended      TEXT,
                    msg_count  INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS emotional_context (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    emotion TEXT,
                    note    TEXT,
                    ts      TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    text     TEXT,
                    kind     TEXT DEFAULT 'reminder',   -- reminder | timer | focus
                    due      REAL,                      -- unix timestamp
                    created  REAL,
                    done     INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS followups (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    about     TEXT,
                    question  TEXT,
                    ask_after REAL,                     -- unix timestamp
                    expires   REAL,
                    status    INTEGER DEFAULT 0,        -- 0 pending, 1 asked, 2 dropped
                    created   REAL
                );
                CREATE TABLE IF NOT EXISTS face_profiles (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    label_id    INTEGER UNIQUE,
                    name        TEXT,
                    sample_dir  TEXT,
                    created     TEXT DEFAULT (datetime('now')),
                    last_seen   TEXT,
                    seen_count  INTEGER DEFAULT 0
                );
            """)

        with self._connect() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(reminders)")]
            if "repeat" not in cols:   # daily | weekdays | weekly | monthly | mon,thu  (NULL = once)
                conn.execute("ALTER TABLE reminders ADD COLUMN repeat TEXT DEFAULT NULL")

    def _connect(self):
        return sqlite3.connect(DB_FILE, check_same_thread=False)

    # ── Facts ─────────────────────────────────────────────────
    def save_memory(self, fact: str):
        with self._lock:
            with self._connect() as conn:
                try:
                    conn.execute("INSERT INTO memories (fact) VALUES (?)", (fact,))
                except sqlite3.IntegrityError:
                    conn.execute(
                        "UPDATE memories SET hits = hits + 1 WHERE fact = ?", (fact,)
                    )

    def get_memories(self, limit: int = 20) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT fact FROM memories ORDER BY hits DESC, created DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [r[0] for r in rows]

    def forget(self, fact: str):
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM memories WHERE fact = ?", (fact,))

    def forget_like(self, pattern: str):
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM memories WHERE fact LIKE ?", (pattern,))

    # ── Message History ───────────────────────────────────────
    def save_message(self, role: str, content: str):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO messages (role, content) VALUES (?, ?)", (role, content)
                )
                conn.execute("""
                    DELETE FROM messages WHERE id NOT IN (
                        SELECT id FROM messages ORDER BY id DESC LIMIT 200
                    )
                """)

    # ── Follow-ups ("how did the exam go?") ───────────────────
    def add_followup(self, about: str, question: str, ask_after: float, expires: float):
        with self._lock:
            with self._connect() as conn:
                conn.execute("INSERT INTO followups (about, question, ask_after, expires, created) VALUES (?, ?, ?, ?, ?)",
                             (about, question, ask_after, expires, time.time()))

    def pending_followups(self) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT id, about, question, ask_after, expires FROM followups "
                                    "WHERE status = 0 ORDER BY ask_after").fetchall()
        return [{"id": r[0], "about": r[1], "question": r[2], "ask_after": r[3], "expires": r[4]} for r in rows]

    def set_followup_status(self, followup_id: int, status: int):
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE followups SET status = ? WHERE id = ?", (status, followup_id))

    def messages_today(self) -> int:
        """How many messages Lala sent today (local time)."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'user' AND "
                                   "date(ts, 'localtime') = date('now', 'localtime')").fetchone()
        return row[0] if row else 0

    def load_history(self, limit: int = 10) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
                    (limit * 2,)
                ).fetchall()
        rows.reverse()
        return [{"role": r[0], "content": r[1]} for r in rows]

    # ── Mood Log ──────────────────────────────────────────────
    def log_mood(self, mood: str):
        now = datetime.datetime.now()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO mood_log (hour, weekday, mood) VALUES (?, ?, ?)",
                    (now.hour, now.weekday(), mood)
                )

    def get_mood_pattern(self) -> dict:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT hour, mood, COUNT(*) as c
                    FROM mood_log GROUP BY hour, mood ORDER BY hour, c DESC
                """).fetchall()
        pattern = {}
        for hour, mood, _ in rows:
            if hour not in pattern:
                pattern[hour] = mood
        return pattern

    def get_typical_mood_now(self):
        return self.get_mood_pattern().get(datetime.datetime.now().hour)

    # ── Topics ────────────────────────────────────────────────
    def log_topic(self, topic: str):
        with self._lock:
            with self._connect() as conn:
                try:
                    conn.execute("INSERT INTO topics (topic) VALUES (?)", (topic,))
                except sqlite3.IntegrityError:
                    conn.execute("""
                        UPDATE topics SET count = count + 1, last_seen = datetime('now')
                        WHERE topic = ?
                    """, (topic,))

    def get_top_topics(self, limit: int = 5) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT topic FROM topics ORDER BY count DESC LIMIT ?", (limit,)
                ).fetchall()
        return [r[0] for r in rows]

    # ── Emotional Context ─────────────────────────────────────
    def log_emotion(self, emotion: str, note: str = ""):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO emotional_context (emotion, note) VALUES (?, ?)",
                    (emotion, note)
                )
                conn.execute("""
                    DELETE FROM emotional_context WHERE id NOT IN (
                        SELECT id FROM emotional_context ORDER BY id DESC LIMIT 50
                    )
                """)

    def get_recent_emotions(self, limit: int = 5) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT emotion FROM emotional_context ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [r[0] for r in rows]

    # ── Session Tracking ──────────────────────────────────────
    def start_session(self) -> int:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("INSERT INTO sessions DEFAULT VALUES")
                return cur.lastrowid

    def end_session(self, session_id: int, msg_count: int):
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE sessions SET ended = datetime('now'), msg_count = ? WHERE id = ?",
                    (msg_count, session_id)
                )

    def get_last_seen(self):
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT ended FROM sessions WHERE ended IS NOT NULL ORDER BY id DESC LIMIT 1"
                ).fetchone()
        if not row:
            return None
        try:
            return datetime.datetime.fromisoformat(row[0])
        except Exception:
            return None

    def get_session_count(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return row[0] if row else 0

    def get_total_messages(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0] if row else 0

    # ── Reminders / timers ────────────────────────────────────
    _REM_COLS = "id, text, kind, due, created, repeat"

    @staticmethod
    def _rem_row(r):
        return {"id": r[0], "text": r[1], "kind": r[2], "due": r[3], "created": r[4], "repeat": r[5]}

    def add_reminder(self, text: str, kind: str, due: float, repeat: str = None) -> int:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO reminders (text, kind, due, created, repeat) VALUES (?, ?, ?, ?, ?)",
                    (text, kind, due, time.time(), repeat),
                )
                return cur.lastrowid

    def pending_reminders(self) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT {self._REM_COLS} FROM reminders WHERE done = 0 ORDER BY due"
                ).fetchall()
        return [self._rem_row(r) for r in rows]

    def take_due_reminders(self, now: float) -> list:
        """Returns reminders that are due and marks them done, atomically."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT {self._REM_COLS} FROM reminders WHERE done = 0 AND due <= ? ORDER BY due",
                    (now,),
                ).fetchall()
                if rows:
                    conn.executemany("UPDATE reminders SET done = 1 WHERE id = ?", [(r[0],) for r in rows])
        return [self._rem_row(r) for r in rows]

    def cancel_reminder(self, reminder_id: int):
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE reminders SET done = 2 WHERE id = ?", (reminder_id,))

    # ══════════════════════════════════════════════════════════
    #  FACE PROFILES — fully integrated into DB
    # ══════════════════════════════════════════════════════════

    def save_face_profile(self, name: str, label_id: int, sample_dir: str):
        """
        Register a face profile in the DB.
        Automatically writes the name into memories so ARIA
        knows who the user is in every conversation.
        """
        with self._lock:
            with self._connect() as conn:
                try:
                    conn.execute(
                        "INSERT INTO face_profiles (label_id, name, sample_dir) VALUES (?, ?, ?)",
                        (label_id, name, sample_dir)
                    )
                except sqlite3.IntegrityError:
                    conn.execute(
                        "UPDATE face_profiles SET name = ?, sample_dir = ? WHERE label_id = ?",
                        (name, sample_dir, label_id)
                    )

        # Keep name fresh in main memory — remove old, add new
        self.forget_like("User's name is%")
        self.save_memory(f"User's name is {name}")

    def get_face_profiles(self) -> dict:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT label_id, name FROM face_profiles").fetchall()
        return {int(row[0]): row[1] for row in rows}

    def get_face_profile_by_name(self, name: str):
        """Returns (label_id, sample_dir) or None."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT label_id, sample_dir FROM face_profiles WHERE name = ?",
                    (name,)
                ).fetchone()
        return row

    def get_all_face_profiles(self) -> list:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT label_id, name, sample_dir, created, last_seen, seen_count "
                    "FROM face_profiles"
                ).fetchall()
        return [
            {"label_id": r[0], "name": r[1], "sample_dir": r[2],
             "created": r[3], "last_seen": r[4], "seen_count": r[5]}
            for r in rows
        ]

    def record_face_seen(self, label_id: int):
        """Call every time a known face is detected."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """UPDATE face_profiles
                       SET last_seen = datetime('now'), seen_count = seen_count + 1
                       WHERE label_id = ?""",
                    (label_id,)
                )

    def get_face_last_seen(self, name: str):
        """Returns datetime of last time this person was detected, or None."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT last_seen FROM face_profiles WHERE name = ?", (name,)
                ).fetchone()
        if not row or not row[0]:
            return None
        try:
            return datetime.datetime.fromisoformat(row[0])
        except Exception:
            return None

    def delete_face_profile(self, name: str):
        """Remove a face profile and its associated name from memory."""
        profile = self.get_face_profile_by_name(name)
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM face_profiles WHERE name = ?", (name,))
        self.forget_like(f"User's name is {name}%")
        return profile  # return so caller can delete sample images if needed

    def get_next_label_id(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT MAX(label_id) FROM face_profiles").fetchone()
        return (int(row[0]) if row[0] is not None else 0) + 1

    # ── Rich Context Summary ──────────────────────────────────
    def get_full_context(self) -> str:
        facts      = self.get_memories(20)
        topics     = self.get_top_topics(5)
        emotions   = self.get_recent_emotions(5)
        mood_now   = self.get_typical_mood_now()
        last_seen  = self.get_last_seen()
        total_msgs = self.get_total_messages()
        sessions   = self.get_session_count()
        profiles   = self.get_all_face_profiles()

        parts = []

        if facts:
            parts.append("What you know about the user:\n" +
                         "\n".join(f"  • {f}" for f in facts))

        if profiles:
            names = [p["name"] for p in profiles]
            parts.append(f"People you can recognise by face: {', '.join(names)}")

        if topics:
            parts.append("Topics they talk about most:\n" +
                         "\n".join(f"  • {t}" for t in topics))

        if emotions:
            parts.append("Recent emotional tone:\n" +
                         "\n".join(f"  • {e}" for e in emotions))

        if mood_now:
            parts.append(f"Their typical mood at this time of day: {mood_now}")

        if last_seen:
            delta = datetime.datetime.now() - last_seen
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                ago = "less than an hour ago"
            elif hours < 24:
                ago = f"{hours} hour{'s' if hours > 1 else ''} ago"
            else:
                days = hours // 24
                ago = f"{days} day{'s' if days > 1 else ''} ago"
            parts.append(f"Last time they talked to you: {ago}")

        if total_msgs > 0:
            parts.append(
                f"You've exchanged {total_msgs} messages across {sessions} sessions total."
            )

        return "\n\n".join(parts) if parts else ""