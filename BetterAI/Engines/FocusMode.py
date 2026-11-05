"""
Focus mode — one command that sets up the whole desk for deep work:
warm breathing LEDs, lo-fi on Spotify, phone on Do Not Disturb, and a
countdown (stored as a 'focus' reminder so it survives restarts).
"""

import time

FOCUS_RGB = (255, 120, 30)       # warm amber
FOCUS_BRIGHTNESS = 70
FOCUS_PLAYLIST = "lofi beats"
NORMAL_RGB = (255, 210, 170)     # soft white after the session
NORMAL_BRIGHTNESS = 150


class FocusMode:
    def __init__(self, reminders, spotify=None, arduino=None, ha=None):
        self.reminders = reminders
        self.spotify = spotify
        self.arduino = arduino
        self.ha = ha
        self.task = ""
        self.started = None
        self.music_started = False
        self._restore_existing()

    def _session(self):
        items = self.reminders.pending(("focus",))
        return items[0] if items else None

    def _restore_existing(self):
        """If Aria restarted mid-session, pick the session back up."""
        s = self._session()
        if s:
            self.task = s["text"] if s["text"] != "focus" else ""
            self.started = s["created"]

    @property
    def active(self) -> bool:
        return self._session() is not None

    # ── Tool handlers ─────────────────────────────────────────────────────────

    def start(self, minutes=25, task: str = "", music=True):
        if self.active:
            return "A focus session is already running. " + self.status()
        minutes = float(minutes or 25)
        if minutes <= 0:
            return "Focus length has to be more than zero."
        self.task = (task or "").strip()
        self.started = time.time()
        done = []

        if self.arduino:
            self.arduino.set_rgb(*FOCUS_RGB)
            self.arduino.set_effect("breathe")
            self.arduino.set_brightness(FOCUS_BRIGHTNESS)
            done.append("lights dimmed")
        self.music_started = False
        if self.spotify and str(music).lower() not in ("false", "0", "no"):
            try:
                self.spotify.play_playlist(FOCUS_PLAYLIST)
                self.music_started = True
                done.append("lo-fi on")
            except Exception as e:
                print(f"[Focus] Spotify failed: {e}")
        if self.ha and self.ha.set_dnd(True):
            done.append("phone on do not disturb")

        self.reminders.add(self.task or "focus", "focus", self.started + minutes * 60)
        what = f" on {self.task}" if self.task else ""
        extras = f" ({', '.join(done)})" if done else ""
        return f"Focus session started{what} for {int(minutes)} minutes{extras}."

    def stop(self):
        s = self._session()
        if not s:
            return "No focus session is running."
        self.reminders.cancel_id(s["id"])
        mins = self._restore()
        return f"Focus session ended early after {mins} minutes."

    def status(self):
        s = self._session()
        if not s:
            return "No focus session is running."
        left = max(0, round((s["due"] - time.time()) / 60))
        what = f" on {self.task}" if self.task else ""
        return f"Focus session{what}: {left} minutes left."

    # ── Called by Aria when the focus reminder fires ──────────────────────────

    def finish(self) -> str:
        mins = self._restore()
        what = f" on {self.task}" if self.task else ""
        return f"Focus session done — {mins} minutes{what}. Take a five minute break."

    def _restore(self) -> int:
        mins = round((time.time() - (self.started or time.time())) / 60)
        if self.arduino:
            self.arduino.set_effect("solid")
            self.arduino.set_rgb(*NORMAL_RGB)
            self.arduino.set_brightness(NORMAL_BRIGHTNESS)
        if self.spotify and self.music_started:
            try:
                self.spotify.pause()
            except Exception:
                pass
        if self.ha:
            self.ha.set_dnd(False)
        self.music_started = False
        self.started = None
        return mins
