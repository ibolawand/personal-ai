"""
Shared test setup. The tests never touch real data:
  - Aria's memory database is a temporary file (database.DB_FILE is redirected per test), and opening
    the real aria_memory.db or MyNotion's noted.db fails the test
  - the MyNotion database is a fresh temporary file with MyNotion's schema
  - Aria's cache folder (~/.cache/aria) is redirected to a temporary folder before anything is imported
They also never need the language model, the camera, a microphone or the network, and never start
apps or MyNotion (launches are recorded instead).

Run:  .venv/bin/python -m pytest          (from the BetterAI folder)
"""

import os
import sqlite3
import sys
import tempfile
import types
from collections import deque
from pathlib import Path

# must happen before any Aria module computes its cache paths
_CACHE = tempfile.mkdtemp(prefix="aria-test-cache-")
os.environ["XDG_CACHE_HOME"] = _CACHE

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import database  # noqa: E402

REAL_FILES = [ROOT / "aria_memory.db", Path.home() / ".config" / "MyNotion" / "noted.db"]

MYNOTION_SCHEMA = """
CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, categoryID INTEGER NOT NULL DEFAULT 0,
    folderID INTEGER NOT NULL DEFAULT 0, userID INTEGER NOT NULL, title TEXT NOT NULL, content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, userID INTEGER NOT NULL);
CREATE TABLE FOLDERS (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, colour TEXT DEFAULT '#4ade80',
    parentID INTEGER DEFAULT NULL, userID INTEGER NOT NULL);
CREATE TABLE USERS (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, email TEXT NOT NULL,
    password TEXT NOT NULL, logged_in BOOLEAN DEFAULT 0);
CREATE TABLE EVENTS (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, startHour REAL, duration REAL,
    title TEXT NOT NULL, color TEXT, allDay BOOLEAN DEFAULT 0, userID INTEGER NOT NULL, repeat TEXT DEFAULT NULL);
INSERT INTO USERS (username, email, password, logged_in) VALUES ('me', '', '', 1);
"""


_real_connect = sqlite3.connect
_REAL = {str(p.resolve()) for p in REAL_FILES}


def _guarded_connect(target, *args, **kwargs):
    path = str(target)
    if path.startswith("file:"):
        path = path[5:].split("?")[0]
    if os.path.realpath(path) in _REAL:
        raise AssertionError(f"a test tried to open real data: {path}")
    return _real_connect(target, *args, **kwargs)


@pytest.fixture(autouse=True)
def _never_launch_anything(monkeypatch):
    """Tests must not open apps or MyNotion on the desktop: launches are recorded instead."""
    import subprocess
    import Engines.LaptopEngine as L
    import Engines.NotionEngine as N
    launched = []
    fake = lambda cmd, *a, **k: launched.append(cmd)
    monkeypatch.setattr(L, "_launch", fake)
    monkeypatch.setattr(N.subprocess, "Popen", fake)
    monkeypatch.setattr(subprocess, "Popen", fake)
    return launched


@pytest.fixture(autouse=True)
def fake_gsettings(monkeypatch):
    """Focus mode pauses notifications with gsettings; tests use a fake store instead of the real desktop."""
    import Engines.FocusMode as F
    store = {"display-notifications": "true"}

    def fake(*args):
        if args[0] == "get":
            return store.get(args[2], "")
        if args[0] == "set":
            store[args[2]] = args[3]
        return ""
    monkeypatch.setattr(F, "_gsettings", fake)
    return store


@pytest.fixture(autouse=True)
def _never_touch_real_files(monkeypatch, tmp_path):
    """Every test gets its own Aria memory DB, and opening a real database fails the test."""
    monkeypatch.setattr(database, "DB_FILE", str(tmp_path / "aria_memory.db"))
    monkeypatch.setattr(sqlite3, "connect", _guarded_connect)


@pytest.fixture
def memory():
    return database.AriaMemory()


@pytest.fixture
def notion_db(tmp_path):
    path = tmp_path / "noted.db"
    conn = sqlite3.connect(path)
    conn.executescript(MYNOTION_SCHEMA)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def notion(notion_db):
    from Engines.Confirm import Confirmer
    from Engines.NotionEngine import NotionEngine
    return NotionEngine(notion_db, Confirmer())


class FakeLLM:
    """Returns scripted replies, in order. chat_with_tools never calls tools unless scripted to."""
    def __init__(self, replies=(), chats=()):
        self.replies = list(replies)      # for chat_with_tools: (text, used)
        self.chats = list(chats)          # for chat()
        self.last_trace = []
        self.prompts = []

    def chat_with_tools(self, prompt, history, system_prompt, tools, execute, on_text=None, **_):
        self.prompts.append(prompt)
        text, used = self.replies.pop(0) if self.replies else ("", [])
        if on_text and text:
            on_text(text)
        self.last_trace = [{"role": "assistant", "content": text}]
        return text, list(used)

    def chat(self, prompt, history, system_prompt, temperature=None, **_):
        self.prompts.append(prompt)
        return self.chats.pop(0) if self.chats else ""


@pytest.fixture
def aria(notion):
    """A real Aria object with its devices replaced: no camera, mic, voice or model."""
    import main
    from Engines.Confirm import Confirmer

    a = main.Aria.__new__(main.Aria)
    a.ui = main.NullUI()
    a.voice = None
    a.muted = False
    a.arduino = None
    a.emotions = types.SimpleNamespace(process=lambda t: None, get_mood_label=lambda: "neutral")
    a.memory = types.SimpleNamespace(log_mood=lambda m: None, save_message=lambda r, c: None,
                                     load_history=lambda limit=6: [])
    a.confirm = Confirmer()
    a._recent = deque(maxlen=6)
    a._session_convo = []
    a.session_msgs = 0
    a._pending_state = None
    a._last_reply = ""
    a._session_hint = None
    a._review = None
    a._initiative_active = None
    a.last_talked = 0
    a.awake = False
    a.screen = types.SimpleNamespace(read_clipboard=lambda: "", copy_to_clipboard=lambda t: "Copied.")
    a.context = types.SimpleNamespace(build_system_prompt=lambda base: base)
    a.llm = FakeLLM()
    a.notion = notion
    a.tools = types.SimpleNamespace(schemas=[], execute=lambda n, args: "")

    class _Rem:
        def __init__(self):
            self.calls = []

        def set_reminder(self, text, **kw):
            self.calls.append((text, kw))
            return f"I'll remind you to {text} later."
    a.reminders = _Rem()
    return a
