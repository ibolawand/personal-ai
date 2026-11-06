"""
Focus mode — one command that sets up the desk for deep work, and works with just the laptop:

  - laptop do-not-disturb: Cinnamon's notification popups are paused, and restored afterwards
  - lo-fi on Spotify (paused during breaks), warm breathing LEDs and phone DND when those are set up
  - Pomodoro rounds: "4 rounds on databases" = 25 min work / 5 min break, repeating on its own
  - a gentle nudge (once per round) if a distracting app (Discord, YouTube, games…) is in front for 2+ minutes
  - stats: every finished block is logged, "how much did I focus this week?"
  - away from the desk: when the camera hasn't seen Lala for AWAY_PAUSE_S (and the keyboard is idle too), the
    work block pauses from the moment they left; it continues with the same time left when they're back

The countdown is a reminder ('focus' = work block ends, 'focusbreak' = break ends), so it survives restarts;
the rest of the session (round, task, previous notification setting) is kept in ~/.cache/aria/focus.json.
"""

import datetime as dt
import json
import os
import re
import subprocess
import threading
import time

FOCUS_RGB = (255, 120, 30)       # warm amber
FOCUS_BRIGHTNESS = 70
FOCUS_PLAYLIST = "lofi beats"
NORMAL_RGB = (255, 210, 170)     # soft white after the session
NORMAL_BRIGHTNESS = 150
STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "focus.json")
NOTIFY_SCHEMA = ["org.cinnamon.desktop.notifications", "display-notifications"]
DISTRACTING = re.compile(r"discord|steam|youtube|netflix|twitch|instagram|tiktok|reddit|whatsapp|telegram|"
                         r"minecraft|roblox|lutris|heroic", re.I)
DISTRACTED_AFTER_MIN = 2
AWAY_PAUSE_S = 3 * 60          # gone this long (camera) -> pause; shorter absences don't count
TYPING_MEANS_HERE_S = 90       # keyboard/mouse used this recently -> they're here, even if the camera lost the face
GIVE_UP_AFTER_S = 2 * 3600     # paused this long -> the session ends quietly


def _gsettings(*args):
    try:
        return subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ""


class FocusMode:
    def __init__(self, reminders, spotify=None, arduino=None, ha=None, memory=None):
        self.reminders = reminders
        self.spotify = spotify
        self.arduino = arduino
        self.ha = ha
        self.memory = memory              # for the focus log (stats)
        self.activity = None              # set by Aria: what's in front, for distraction nudges
        self.on_nudge = None              # set by Aria: fn(text) to say something
        self.idle_seconds = None          # set by Aria: fn() -> seconds since keyboard/mouse use, or None
        self._away_since = None
        self.state = self._load()
        self.music_started = self.state.get("music", False)

    # ── state ──

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f)
        except OSError:
            pass

    def _block(self, kinds=("focus",)):
        items = self.reminders.pending(kinds)
        return items[0] if items else None

    @property
    def paused(self):
        return self.state.get("paused")       # {"left": seconds, "at": when they left} or None

    @property
    def active(self) -> bool:
        """In a work block (breaks don't count, so Aria may chat during a break)."""
        return self._block() is not None or bool(self.paused)

    @property
    def in_session(self) -> bool:
        return self._block(("focus", "focusbreak")) is not None or bool(self.paused)

    @property
    def task(self):
        return self.state.get("task", "")

    # ── setup / restore of the desk ──

    def _desk_on(self, music=True):
        done = []
        if self.arduino:
            self.arduino.set_rgb(*FOCUS_RGB)
            self.arduino.set_effect("breathe")
            self.arduino.set_brightness(FOCUS_BRIGHTNESS)
            done.append("lights dimmed")
        if "prev_notify" not in self.state:
            prev = _gsettings("get", *NOTIFY_SCHEMA)
            if prev in ("true", "false"):
                self.state["prev_notify"] = prev
                _gsettings("set", *NOTIFY_SCHEMA, "false")
                done.append("notifications paused")
        self.music_started = False
        if self.spotify and music:
            try:
                result = self.spotify.play_playlist(FOCUS_PLAYLIST)
                if str(result).startswith("Playing"):
                    self.music_started = True
                    done.append("lo-fi on")
            except Exception as e:
                print(f"[Focus] Spotify failed: {e}")
        self.state["music"] = self.music_started
        if self.ha and self.ha.set_dnd(True):
            done.append("phone on do not disturb")
        return done

    def _desk_off(self):
        if self.arduino:
            self.arduino.set_effect("solid")
            self.arduino.set_rgb(*NORMAL_RGB)
            self.arduino.set_brightness(NORMAL_BRIGHTNESS)
        self._pause_music()
        prev = self.state.pop("prev_notify", None)
        if prev in ("true", "false"):
            _gsettings("set", *NOTIFY_SCHEMA, prev)
        if self.ha:
            self.ha.set_dnd(False)

    def _pause_music(self):
        if self.spotify and self.music_started:
            try:
                self.spotify.pause()
            except Exception:
                pass
        self.music_started = False
        self.state["music"] = False

    # ── tool handlers ──

    def start(self, minutes=25, task: str = "", music=True, rounds=1, break_minutes=5):
        if self.in_session:
            return "A focus session is already running. " + self.status()
        minutes = float(minutes or 25)
        rounds = max(1, min(8, int(float(rounds or 1))))
        break_minutes = max(1.0, float(break_minutes or 5))
        if minutes <= 0:
            return "Focus length has to be more than zero."
        music = str(music).lower() not in ("false", "0", "no")
        self.state = {"task": (task or "").strip(), "work": minutes, "break": break_minutes, "rounds": rounds,
                      "round": 1, "block_start": time.time(), "want_music": music, "nudged_round": 0}
        done = self._desk_on(music)
        self.reminders.add(self.task or "focus", "focus", time.time() + minutes * 60)
        self._save()
        what = f" on {self.task}" if self.task else ""
        plan = (f"{rounds} rounds of {int(minutes)} minutes with {int(break_minutes)} minute breaks"
                if rounds > 1 else f"{int(minutes)} minutes")
        extras = f" ({', '.join(done)})" if done else ""
        return f"Focus session started{what}: {plan}{extras}."

    def stop(self):
        block = self._block(("focus", "focusbreak"))
        if not block and not self.paused:
            return "No focus session is running."
        if block:
            self.reminders.cancel_id(block["id"])
        mins = self._log_block() if not block or block["kind"] == "focus" else 0
        self._desk_off()
        self.state = {}
        self._save()
        return f"Focus session ended early" + (f" after {mins} minutes." if mins else ".")

    def status(self):
        if self.paused:
            left = max(1, round(self.paused["left"] / 60))
            return f"Focus is paused while you're away: {left} minutes left when you're back."
        block = self._block(("focus", "focusbreak"))
        if not block:
            return "No focus session is running."
        left = max(0, round((block["due"] - time.time()) / 60))
        rounds = self.state.get("rounds", 1)
        rnd = f" (round {self.state.get('round', 1)} of {rounds})" if rounds > 1 else ""
        if block["kind"] == "focusbreak":
            return f"On a break{rnd}: {left} minutes left."
        what = f" on {self.task}" if self.task else ""
        return f"Focus session{what}{rnd}: {left} minutes left."

    def stats(self, period: str = "week"):
        if not self.memory:
            return "I don't have a focus log."
        days = {"today": 0, "week": 6, "this week": 6, "month": 29, "this month": 29}.get((period or "week").lower(), 6)
        since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        rows = self.memory.focus_log_since(since)
        if not rows:
            return "No finished focus sessions " + ("today." if days == 0 else f"in the last {days + 1} days.")
        total = sum(m for _, m, _ in rows)
        tasks = {}
        for _, m, t in rows:
            if t:
                tasks[t] = tasks.get(t, 0) + m
        fmt = lambda m: f"{int(m) // 60} h {int(m) % 60} min" if m >= 60 else f"{int(m)} min"
        out = f"{fmt(total)} of focus in {len(rows)} block{'s' if len(rows) != 1 else ''}"
        out += " today" if days == 0 else f" in the last {days + 1} days"
        if tasks:
            top = sorted(tasks.items(), key=lambda x: -x[1])[:3]
            out += ", mostly " + ", ".join(f"{t} ({fmt(m)})" for t, m in top)
        return out + "."

    # ── called by Aria when the countdown runs out ──

    def finish(self) -> str:
        """A work block ended: start the break, or wrap up after the last round."""
        mins = self._log_block()
        rnd, rounds = self.state.get("round", 1), self.state.get("rounds", 1)
        what = f" on {self.task}" if self.task else ""
        if rnd < rounds:
            brk = self.state.get("break", 5)
            self._pause_music()
            self.state["block_start"] = time.time()
            self.reminders.add("break", "focusbreak", time.time() + brk * 60)
            self._save()
            return f"Round {rnd} of {rounds} done. Take a {int(brk)} minute break, I'll call you back."
        self._desk_off()
        total = self.state.get("total", mins)
        self.state = {}
        self._save()
        if rounds > 1:
            return f"That's all {rounds} rounds — {total} minutes of focus{what}. Nice work, take a proper break."
        return f"Focus session done — {mins} minutes{what}. Take a five minute break."

    def end_break(self) -> str:
        """A break ended: next work block."""
        self.state["round"] = self.state.get("round", 1) + 1
        self.state["block_start"] = time.time()
        self.reminders.add(self.task or "focus", "focus", time.time() + self.state.get("work", 25) * 60)
        if self.state.get("want_music"):
            self._desk_on(True)
        self._save()
        return f"Break's over — round {self.state['round']} of {self.state.get('rounds', 1)}. Back to it!"

    def _log_block(self) -> int:
        start = self.state.get("block_start") or time.time()
        end = self.paused["at"] if self.paused else time.time()      # time away doesn't count
        mins = max(0, round((end - start) / 60))
        self.state["total"] = self.state.get("total", 0) + mins
        if self.memory and mins >= 1:
            try:
                self.memory.log_focus(mins, self.task)
            except Exception as e:
                print(f"[Focus] log failed: {e}")
        return mins

    # ── away from the desk ──

    def user_left(self, at=None):
        """The camera stopped seeing them (at = when the face was last seen)."""
        self._away_since = at or time.time()

    def user_back(self):
        """The camera sees someone again. Returns what to say if a paused block continues, else None."""
        self._away_since = None
        return self.resume()

    def check_away(self, now=None):
        """Every 30 s: pause after AWAY_PAUSE_S away; resume if they're typing again; give up after hours."""
        now = now or time.time()
        idle = self.idle_seconds() if self.idle_seconds else None
        typing = idle is not None and idle < TYPING_MEANS_HERE_S
        if self.paused:
            if typing:
                self._away_since = None
                return self.resume(now)
            if now - self.paused["at"] > GIVE_UP_AFTER_S:
                self._log_block()
                self._desk_off()
                self.state = {}
                self._save()
                print("[Focus] away for hours — session ended")
            return None
        block = self._block()
        if not block or self._away_since is None or typing or now - self._away_since < AWAY_PAUSE_S:
            return None
        self.reminders.cancel_id(block["id"])
        self.state["paused"] = {"left": max(60.0, block["due"] - self._away_since), "at": self._away_since}
        self.state["resume_music"] = self.music_started
        self._pause_music()
        self._save()
        print(f"[Focus] paused — away since {time.strftime('%H:%M', time.localtime(self._away_since))}")
        return None

    def resume(self, now=None):
        p = self.paused
        if not p:
            return None
        now = now or time.time()
        self.state.pop("paused")
        self.state["block_start"] = self.state.get("block_start", p["at"]) + (now - p["at"])
        self.reminders.add(self.task or "focus", "focus", now + p["left"])
        if self.state.pop("resume_music", False) and self.spotify:
            try:
                self.spotify.play()
                self.music_started = self.state["music"] = True
            except Exception as e:
                print(f"[Focus] Spotify resume failed: {e}")
        self._save()
        left = max(1, round(p["left"] / 60))
        what = f" on {self.task}" if self.task else ""
        if now - p["at"] < 60:          # barely gone: no need to say anything
            return None
        return f"Welcome back! I paused your focus{what} while you were away, {left} minutes to go."

    # ── distraction nudge ──

    def start_watching(self):
        def loop():
            while True:
                time.sleep(30)
                try:
                    back = self.check_away()
                    if back and self.on_nudge:
                        self.on_nudge(back)
                    self.check_distraction()
                except Exception as e:
                    print(f"[Focus] {e}")
        threading.Thread(target=loop, daemon=True).start()

    def check_distraction(self):
        if not (self.active and self.activity and self.on_nudge):
            return None
        app, mins = self.activity.current()
        rnd = self.state.get("round", 1)
        distracting = bool(app) and (DISTRACTING.search(app) or self.activity.watching())
        if not distracting or mins < DISTRACTED_AFTER_MIN or self.state.get("nudged_round") == rnd:
            return None
        if self.activity.watching() and not DISTRACTING.search(app):
            app = "the video"
        self.state["nudged_round"] = rnd
        self._save()
        block = self._block()
        left = max(1, round((block["due"] - time.time()) / 60)) if block else 0
        text = f"Psst, it's still focus time — {app} can wait {left} more minutes."
        self.on_nudge(text)
        return text
