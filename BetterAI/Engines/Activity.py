"""
What Lala is doing on the laptop, so Aria can talk about it and suggest breaks.

Every 20 seconds: which app is in front, and whether Lala used keyboard/mouse in the last 2 minutes.
Kept only in memory (app names and minutes) — never written to disk, gone when Aria quits.
Window titles are only looked at in the moment, to tell whether Lala is watching something.

  stretch     — time at the laptop without a break (a break = 5+ minutes away, idle or locked)
  current     — the app in front and for how long
  today       — minutes per app since midnight (since Aria started)
"""

import re
import subprocess
import threading
import time
from collections import Counter

from Engines.Initiative import idle_seconds, screen_locked

TICK_S = 20
ACTIVE_IDLE_S = 120      # input within this counts as "using the laptop"
BREAK_IDLE_S = 5 * 60    # this much idle (or locked) ends a stretch
WATCH_RE = re.compile(r"youtube|netflix|twitch|prime video|disney\+|crunchyroll|vlc|mpv|\bepisode\b|\bS\d+E\d+\b", re.I)
VIDEO_APPS = {"firefox", "google-chrome", "chromium", "brave-browser", "vlc", "mpv", "totem", "celluloid"}


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""


def active_window():
    """(wm_class, title) of the window in front, or (None, None)."""
    m = re.search(r"window id # (0x[0-9a-f]+)", _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
    if not m or m.group(1) == "0x0":
        return None, None
    out = _run(["xprop", "-id", m.group(1), "WM_CLASS", "_NET_WM_NAME"])
    cls = re.findall(r'WM_CLASS\(STRING\) = "([^"]*)", "([^"]*)"', out)
    title = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', out)
    return (cls[0][0].lower() if cls else None), (title.group(1) if title else "")


class Activity:
    def __init__(self, menu=None):
        self.menu = menu                 # LaptopEngine.MenuApps, for friendly app names
        self._lock = threading.Lock()
        self.day = time.strftime("%Y-%m-%d")
        self.today = Counter()           # app -> seconds
        self.stretch_start = None        # when the current stretch at the laptop began
        self.stretch_apps = Counter()
        self.current_app, self.current_since = None, None
        self._watching = False
        self._names = {}

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception as e:
                print(f"[Activity] {e}")
            time.sleep(TICK_S)

    def _name(self, wm):
        if wm not in self._names:
            name = None
            if self.menu:
                for a in self.menu.all():
                    if a["wm"] and (a["wm"] == wm or a["wm"] in wm or wm in a["wm"]):
                        name = a["name"]
                        break
            self._names[wm] = name or wm.replace("-", " ").title()
        return self._names[wm]

    def tick(self):
        now = time.time()
        idle = idle_seconds()
        locked = screen_locked()
        with self._lock:
            if time.strftime("%Y-%m-%d") != self.day:
                self.day, self.today = time.strftime("%Y-%m-%d"), Counter()
            if locked or idle is None or idle >= BREAK_IDLE_S:
                self.stretch_start, self.stretch_apps = None, Counter()
                self.current_app = self.current_since = None
                self._watching = False
                return
            wm, title = active_window()
            if not wm or idle >= ACTIVE_IDLE_S:
                return
            app = self._name(wm)
            if wm in ("aria", "python3") or app.lower() == "aria":
                return
            self._watching = bool(title) and wm in VIDEO_APPS | {"vlc", "mpv"} and bool(WATCH_RE.search(title))
            self.today[app] += TICK_S
            if self.stretch_start is None:
                self.stretch_start = now
            self.stretch_apps[app] += TICK_S
            if app != self.current_app:
                self.current_app, self.current_since = app, now

    # ── for Initiative and the tool ──

    def stretch_minutes(self) -> int:
        with self._lock:
            return int((time.time() - self.stretch_start) / 60) if self.stretch_start else 0

    def stretch_main_app(self):
        with self._lock:
            return self.stretch_apps.most_common(1)[0][0] if self.stretch_apps else None

    def current(self):
        """(app, minutes in it) or (None, 0)."""
        with self._lock:
            if not self.current_app:
                return None, 0
            return self.current_app, int((time.time() - self.current_since) / 60)

    def watching(self) -> bool:
        return self._watching

    def screen_time(self):
        """Tool: 'how long have I been on the laptop?' / 'what did I do today?'"""
        with self._lock:
            items = [(a, s) for a, s in self.today.most_common(6) if s >= 60]
            stretch = int((time.time() - self.stretch_start) / 60) if self.stretch_start else 0
        if not items:
            return "I haven't seen much laptop use today yet (I only count since I started)."
        fmt = lambda s: f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min"
        parts = ", ".join(f"{a} {fmt(int(s))}" for a, s in items)
        out = f"Laptop use today (since Aria started): {parts}."
        if stretch >= 10:
            out += f" Current stretch without a break: {fmt(stretch * 60)}."
        return out
