"""
Posture and screen-distance nudges from the camera, decided in code (no vision model, so no GPU and no lag).

The camera loop reports where the face is in each frame: its width (how close Lala sits) and the height of its
centre (sliding down in the chair moves the face lower). Samples are boiled down to one median per minute.

The "good posture" reference:
  - "this is my good posture" / "remember how I'm sitting" (tool) sets it from the last 20 seconds, and it stays;
  - otherwise it is learnt by itself from the first minutes after sitting down (people start upright), blended
    slowly over sessions.

A nudge comes when most of the last WINDOW_MIN minutes were clearly closer or lower than the reference,
at most once per NUDGE_EVERY_S, and only when Aria may speak (not muted, not in quiet hours, not mid-conversation,
not during a call or a video). Turn it off with ARIA_POSTURE=0.
"""

import json
import os
import random
import statistics
import time
from collections import deque

STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "posture.json")
WINDOW_MIN = 10            # judge the last 10 minutes...
NEEDED_SHARE = 0.8         # ...of which 80% must be off
MIN_MINUTES = 8            # with the face seen in at least 8 of them
CLOSE_FACTOR = 1.25        # face 25% wider than usual = leaning in
SLOUCH_DROP = 0.07         # face centre 7% of the frame height lower than usual = slouching
NUDGE_EVERY_S = 30 * 60
NUDGES_PER_DAY = 6
LEARN_FIRST_MIN = 3        # automatic reference: the first 3 minutes after sitting down
NEW_SITTING_AFTER_S = 10 * 60

CLOSE_LINES = ["Psst, you're leaning right into the screen. Sit back a bit, your eyes will thank you.",
               "You've crept pretty close to the screen. Lean back a little?",
               "Quick check: you're nose-to-screen again. Back up a bit."]
SLOUCH_LINES = ["Posture check: you're sliding down in your chair. Sit up a bit?",
                "You're slouching a little. Shoulders back, sit up straight for a sec.",
                "Little reminder to sit up, you've been sinking into the chair."]


class Posture:
    def __init__(self):
        self.enabled = os.environ.get("ARIA_POSTURE", "1") != "0"
        self.state = self._load()            # {"ref": {"w", "cy", "manual"}, "last_nudge", "day", "count"}
        self.minutes = deque(maxlen=60)      # (minute_start, median_w, median_cy)
        self._bucket, self._bucket_t = [], None
        self._raw = deque(maxlen=200)        # (t, w, cy) for "this is my good posture"
        self._last_sample = 0.0
        self._sitting_since = None

    # ── persistence ──

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

    # ── samples from the camera loop ──

    def add(self, w, cy, now=None):
        """w: face width / frame width; cy: face centre y / frame height (0 = top)."""
        now = now or time.time()
        if now - self._last_sample > NEW_SITTING_AFTER_S:
            self._sitting_since = now            # sat down again after a while away
            self.minutes.clear()
            self._bucket, self._bucket_t = [], None
        self._last_sample = now
        self._raw.append((now, w, cy))
        minute = int(now // 60) * 60
        if self._bucket_t is not None and minute != self._bucket_t:
            self._close_bucket()
        if self._bucket_t is None:
            self._bucket_t = minute
        self._bucket.append((w, cy))

    def _close_bucket(self):
        if self._bucket:
            self.minutes.append((self._bucket_t, statistics.median(b[0] for b in self._bucket),
                                 statistics.median(b[1] for b in self._bucket)))
            self._learn()
        self._bucket, self._bucket_t = [], None

    def _learn(self):
        """Automatic reference from the first minutes of each sitting (unless one was set by voice)."""
        ref = self.state.get("ref") or {}
        if ref.get("manual") or self._sitting_since is None:
            return
        first = [m for m in self.minutes if m[0] < self._sitting_since + LEARN_FIRST_MIN * 60]
        if len(first) < LEARN_FIRST_MIN or len(first) != len(self.minutes):
            return                                # not yet, or already past the first minutes
        w, cy = statistics.median(m[1] for m in first), statistics.median(m[2] for m in first)
        if ref:
            w, cy = ref["w"] * 0.7 + w * 0.3, ref["cy"] * 0.7 + cy * 0.3
        self.state["ref"] = {"w": w, "cy": cy, "manual": False}
        self._save()

    # ── tool ──

    def set_reference(self, now=None):
        """Tool: 'this is my good posture'."""
        now = now or time.time()
        recent = [r for r in self._raw if now - r[0] <= 20]
        if len(recent) < 5:
            return "I can't see you well enough right now. Sit in front of the camera and try again."
        self.state["ref"] = {"w": statistics.median(r[1] for r in recent),
                             "cy": statistics.median(r[2] for r in recent), "manual": True}
        self._save()
        return "Got it, that's your good posture. I'll tell you when you drift away from it."

    # ── the check ──

    def problem(self, now=None):
        """'close', 'slouch' or None, from the last WINDOW_MIN minutes."""
        now = now or time.time()
        ref = self.state.get("ref")
        if not ref:
            return None
        recent = [m for m in self.minutes if m[0] >= now - WINDOW_MIN * 60 - 60]
        if len(recent) < MIN_MINUTES:
            return None
        close = sum(m[1] > ref["w"] * CLOSE_FACTOR for m in recent)
        low = sum(m[2] > ref["cy"] + SLOUCH_DROP for m in recent)
        if close >= NEEDED_SHARE * len(recent):
            return "close"
        if low >= NEEDED_SHARE * len(recent):
            return "slouch"
        return None

    def nudge(self, now=None):
        """The line to say, or None. Call about once a minute when Aria may speak."""
        if not self.enabled:
            return None
        now = now or time.time()
        if now - self.state.get("last_nudge", 0) < NUDGE_EVERY_S:
            return None
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self.state.get("day") != today:
            self.state["day"], self.state["count"] = today, 0
        if self.state.get("count", 0) >= NUDGES_PER_DAY:
            return None
        kind = self.problem(now)
        if not kind:
            return None
        self.state["last_nudge"] = now
        self.state["count"] = self.state.get("count", 0) + 1
        self._save()
        self.minutes.clear()          # judge fresh minutes next time
        return random.choice(CLOSE_LINES if kind == "close" else SLOUCH_LINES)
