"""
What's going on at the desk, for features that speak up by themselves (posture nudges) or need to know whether
Lala is here: quiet hours, a locked screen, something fullscreen, another app using the microphone (a call),
and how long the keyboard and mouse have been idle.

Also the posture nudge loop: once a minute, if Lala is at the desk and it's a good moment (not in a conversation,
not muted, outside quiet hours, not watching something, screen not locked, nothing fullscreen, no call), Posture
may say one short line ("Sit up a bit?").

Aria no longer starts conversations on her own (removed on purpose); this is all that's left of that loop.

Settings (Engines/.env): ARIA_QUIET=22:30-08:30   quiet hours
"""

import datetime as dt
import json
import os
import re
import subprocess
import threading
import time

QUIET = os.environ.get("ARIA_QUIET", "22:30-08:30")


def _parse_quiet(spec):
    try:
        a, b = spec.split("-")
        h1, m1 = map(int, a.split(":"))
        h2, m2 = map(int, b.split(":"))
        return h1 * 60 + m1, h2 * 60 + m2
    except Exception:
        return None


def in_quiet_hours(now: dt.datetime = None) -> bool:
    q = _parse_quiet(QUIET)
    if not q:
        return False
    now = now or dt.datetime.now()
    m = now.hour * 60 + now.minute
    start, end = q
    return start <= m < end if start < end else (m >= start or m < end)


def _run(cmd, timeout=2):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def screen_locked() -> bool:
    out = _run(["dbus-send", "--session", "--print-reply", "--dest=org.cinnamon.ScreenSaver",
                "/org/cinnamon/ScreenSaver", "org.cinnamon.ScreenSaver.GetActive"])
    return "boolean true" in out


def idle_seconds() -> float | None:
    out = _run(["gdbus", "call", "--session", "--dest", "org.cinnamon.Muffin.IdleMonitor",
                "--object-path", "/org/cinnamon/Muffin/IdleMonitor/Core",
                "--method", "org.cinnamon.Muffin.IdleMonitor.GetIdletime"])
    m = re.search(r"(\d+)", out)
    return int(m.group(1)) / 1000 if m else None


def fullscreen_app() -> bool:
    win = re.search(r"window id # (0x[0-9a-f]+)", _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
    if not win or win.group(1) == "0x0":
        return False
    return "_NET_WM_STATE_FULLSCREEN" in _run(["xprop", "-id", win.group(1), "_NET_WM_STATE"])


def mic_in_use_by_others() -> bool:
    """A call or recording in another app (Aria's own microphone use doesn't count)."""
    try:
        streams = json.loads(_run(["pactl", "-f", "json", "list", "source-outputs"]) or "[]")
    except ValueError:
        return False
    me = str(os.getpid())
    for s in streams:
        props = s.get("properties", {})
        if props.get("application.process.id") == me or s.get("corked"):
            continue
        name = (props.get("media.name", "") + " " + props.get("application.id", "")).lower()
        if "peak detect" in name or "pavucontrol" in name:     # volume meters, not a call
            continue
        return True
    return False


class PostureNudges:
    """Once a minute: a posture nudge when it's a good moment (Engines/Posture.py decides whether one is due)."""

    def __init__(self, aria):
        self.aria = aria

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        time.sleep(90)    # let startup and the first greeting happen first
        while not self.aria._shutting_down:
            try:
                self.tick(time.time())
            except Exception as e:
                print(f"[Posture] {e}")
            time.sleep(60)

    def _present(self) -> bool:
        vision = getattr(self.aria, "vision", None)
        if getattr(vision, "_camera_index", None) is not None and getattr(vision, "_running", False):
            return bool(vision.is_present)
        idle = idle_seconds()       # no camera: recent keyboard/mouse use counts as being here
        return idle is not None and idle < 5 * 60

    def tick(self, now, present=None):
        a = self.aria
        posture = getattr(a, "posture", None)
        if not posture or a.awake or a.muted or a._shutting_down:
            return
        if not (self._present() if present is None else present):
            return
        if in_quiet_hours():
            return
        activity = getattr(a, "activity", None)
        if activity and activity.watching():
            return
        if screen_locked() or fullscreen_app() or mic_in_use_by_others():
            return
        line = posture.nudge(now)
        if line:
            print(f"[Posture] {line}")
            a._announce(line)
