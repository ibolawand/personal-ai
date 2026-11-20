"""
Aria's companion mode: after school she wakes herself, quietly (no voice, no model), stays on screen while the
laptop is used, and now and then reacts to the app in front with a gesture, a glance and, rarely, one bubble line.
On a free day (no lessons) she isn't quiet: she says her greeting and her conversation starters out loud.

The rules are plain functions, decided in code and tested without X, audio or network. Never during a lesson (the
WebUntis timetable), in quiet hours, while something is fullscreen, during a call or with the screen locked.
"""
import datetime as dt

UNKNOWN = object()          # the timetable couldn't be read
ACTIVE_S = 10               # input this recent = the user is using the laptop right now
AWAY_S = 2 * 3600           # away this long = she may greet again
DOZE_S = 600                # no input this long = she goes back to sleep
FALLBACK_END = 1600         # timetable unknown: weekdays count as school until 16:00


def _hhmm(t: dt.datetime) -> int:
    return t.hour * 100 + t.minute


def school_over(now: dt.datetime, span) -> bool:
    """Is school over for today? `span`: (first start, last end) as HHMM, None (no lessons today) or UNKNOWN."""
    if span is None:
        return True
    if span is UNKNOWN:
        return now.weekday() >= 5 or _hhmm(now) >= FALLBACK_END
    return _hhmm(now) >= span[1]


def may_self_wake(now: dt.datetime, *, over: bool, idle_s, away_s: float, last_wake, busy: bool) -> bool:
    """She may wake herself: school is over, the user is at the laptop right now, nothing forbids it (fullscreen, a
    call, locked, quiet hours), and she hasn't greeted today, or the user was away a long while."""
    if not over or busy or idle_s is None or idle_s > ACTIVE_S:
        return False
    return last_wake is None or last_wake.date() != now.date() or away_s >= AWAY_S


def should_doze(idle_s, *, over: bool, busy_quiet: bool) -> bool:
    """Companion goes back to sleep: no input for a while, a lesson (again), quiet hours or the screen locked."""
    return idle_s is None or idle_s >= DOZE_S or not over or busy_quiet


# ── what's in front, and how she reacts ──

import random                                                   # noqa: E402
import re                                                       # noqa: E402

from Engines.Activity import WATCH_RE                           # noqa: E402
from Engines.Openers import Openers, free_day, prompt_for, clean_line   # noqa: E402

SETTLE_S = 60               # just switched app: maybe only passing through
BODY_EVERY_S = 5 * 60
LINE_EVERY_S = 30 * 60

_BROWSERS = ("firefox", "chrom", "brave", "opera", "vivaldi", "edge")
_CALL_RE = re.compile(r"^meet - |\b(?:zoom meeting|google meet|jitsi|teams call|microsoft teams)\b", re.I)


def app_kind(wm_class, title: str):
    """The kind of app in front, or None (nothing, Aria herself, or an app she has nothing to say about)."""
    wm, title = (wm_class or "").lower(), title or ""
    if not wm or wm in ("aria", "python3") or title.strip().lower() == "aria":
        return None
    browser = any(b in wm for b in _BROWSERS)
    if wm in ("zoom", "teams", "microsoft teams - preview") or "zoom" in wm or _CALL_RE.search(title) \
            or (wm == "discord" and re.search(r"\b(call|voice)\b", title, re.I)):
        return "call"
    if "mynotion" in wm or title.startswith("MyNotion"):
        return "mynotion"
    if (browser or wm in ("vlc", "mpv", "totem", "celluloid")) and WATCH_RE.search(title):
        return "video"
    if wm in ("code", "code-oss", "vscodium", "jetbrains-pycharm", "jetbrains-idea", "jetbrains-webstorm") \
            or wm.startswith("jetbrains"):
        return "code"
    if "terminal" in wm or wm in ("tilix", "kitty", "alacritty", "konsole", "xterm"):
        return "terminal"
    if wm == "spotify":
        return "music"
    if wm in ("discord", "telegramdesktop", "telegram-desktop", "signal", "whatsapp", "element"):
        return "chat"
    if "libreoffice" in wm or wm in ("evince", "xreader", "okular") or title.lower().endswith(".pdf"):
        return "docs"
    if wm == "steam" or "steam_app" in wm:
        return "game"
    return "browser" if browser else None


BODY = {"code": "think", "video": "curious", "browser": "lookAround", "mynotion": "smile", "terminal": "lean",
        "music": "rock", "chat": "lean", "docs": "think"}

LINES = {
    "code": ["coding again? don't forget to commit 👀", "ooh, what are we building?",
             "that bug doesn't stand a chance", "remember to drink something, coder",
             "I believe in your code. mostly."],
    "video": ["ooh, what are we watching?", "save me a seat!", "is it good? no spoilers",
              "one more episode, right? 😏"],
    "browser": ["whatcha looking up?", "so many tabs…", "find anything good?", "don't fall down a rabbit hole"],
    "mynotion": ["studying? I'm proud of you", "notes time! you've got this", "want me to quiz you later?",
                 "your notes look so tidy"],
    "terminal": ["ooh, hacker mode", "careful with that sudo", "the terminal looks so cool", "type faster, hacker"],
    "music": ["what are we listening to?", "good song choice", "turn it up a little?", "ooh, I like this one"],
    "chat": ["say hi from me!", "who are you talking to?", "gossip time?", "tell them I said hey"],
    "docs": ["reading something smart?", "that looks like homework…", "need help with that?",
             "don't forget to take breaks"],
}


def next_test(cards, now: dt.datetime, span):
    """The first coming test (TestPrep card dicts, nearest first) that isn't over: one dated today is over once
    school is."""
    for card in cards or []:
        if card.get("days") == 0 and school_over(now, span):
            continue
        return card
    return None


class Reactions:
    """Picks her reaction to the app in front: a gesture now and then, and rarely a line. Remembers what she did,
    so lines come at most every 30 min, never twice in a row about the same kind, and never repeat until that
    kind's lines are all used."""

    def __init__(self, rng=random):
        self.rng = rng
        self.body_at = self.line_at = None
        self.line_kind = None
        self._left = {}             # kind -> lines not used yet in this round

    def _line(self, kind):
        left = self._left.get(kind) or list(LINES[kind])
        line = self.rng.choice(left)
        left.remove(line)
        self._left[kind] = left
        return line

    def pick(self, kind, now: float, in_app_s: float, body_every: float = BODY_EVERY_S, lines: bool = True):
        """(gesture or None, line or None) for `kind` in front since `in_app_s` seconds, at time `now` (s).
        `body_every`: seconds between gestures; `lines`: False on free days, where openers take the lines' place."""
        if kind not in BODY or in_app_s < SETTLE_S:
            return None, None
        if self.body_at is not None and now - self.body_at < body_every:
            return None, None
        self.body_at = now
        line = None
        if lines and kind in LINES and kind != self.line_kind and (self.line_at is None or now - self.line_at >= LINE_EVERY_S):
            line, self.line_at, self.line_kind = self._line(kind), now, kind
        return BODY[kind], line


def wake_line(now: dt.datetime, test, rain) -> str:
    """Her line when she wakes herself: school's done (or hello), the next test, an umbrella if rain is coming."""
    first = "school's done!" if now.weekday() < 5 and now.hour < 18 else \
        "good evening!" if now.hour >= 18 else "hey, you're here!"
    parts = [first]
    if test:
        when = test.get("when") or ""
        parts.append(f"{test['subject']} test {when}, btw" if when not in ("today", "tomorrow")
                     else f"{test['subject']} test {when}!")
    if rain:
        parts.append("take an umbrella later ☔")
    return " ".join(parts)


# ── the loop ──

import os                                                       # noqa: E402
import threading                                                # noqa: E402
import time                                                     # noqa: E402
from dataclasses import dataclass                               # noqa: E402
from typing import Callable                                     # noqa: E402

TICK_S = 3
GLANCE_S = 2.5
SLOW_S = 10 * 60            # timetable and tests are asked again at most this often


def _cached(fn, ttl, clock=time.monotonic):
    box = []

    def get():
        if not box or clock() - box[0] >= ttl:
            box[:] = [clock(), fn()]
        return box[1]
    return get


@dataclass
class Probes:
    """What the companion looks at. Each is a no-argument callable; any of them may raise or return None."""
    idle_s: Callable
    active_window: Callable         # -> (wm_class, title)
    active_rect: Callable           # -> (left, top, right, bottom) of the window in front, or None
    fullscreen: Callable
    on_call: Callable
    locked: Callable
    quiet: Callable
    school_span: Callable           # -> (start, end) HHMM, None (no lessons), or UNKNOWN
    tests: Callable                 # -> TestPrep card dicts, nearest first
    rain_soon: Callable             # -> True / False / None
    today_items: Callable = lambda: []  # -> [(text, "HH:MM")]: events and reminders still ahead today

    @classmethod
    def real(cls, aria):
        from Engines import Desk
        from Engines.Activity import active_window
        from ui.desktop_windows import active_window_rect

        def span():
            untis = getattr(aria, "untis", None)
            if not untis:
                return UNKNOWN
            try:
                return untis.school_span(dt.date.today())
            except Exception:
                return UNKNOWN

        def tests():
            prep = getattr(aria, "test_prep", None)
            return prep.cards() if prep else []

        def rect():
            w = active_window_rect()
            return (w.left, w.top, w.right, w.bottom) if w else None

        def today_items():
            rem = getattr(aria, "reminders", None)
            if not rem:
                return []
            now, out = dt.datetime.now(), []
            for r in sorted(rem.pending(("event", "reminder", "due")), key=lambda r: r["due"]):
                at = dt.datetime.fromtimestamp(r["due"])
                if at.date() == now.date() and at > now:
                    out.append((r["text"], at.strftime("%H:%M")))
            return out

        weather = getattr(aria, "weather", None)
        return cls(today_items=_cached(today_items, 60),idle_s=Desk.idle_seconds, active_window=active_window, active_rect=rect,
                   fullscreen=Desk.fullscreen_app, on_call=Desk.mic_in_use_by_others, locked=Desk.screen_locked,
                   quiet=Desk.in_quiet_hours, school_span=_cached(span, SLOW_S), tests=_cached(tests, SLOW_S),
                   rain_soon=weather.rain_soon if weather else (lambda: None))


def opener_enabled() -> bool:
    """Weekend openers on (ARIA_WEEKEND_CHAT=0 in Engines/.env turns them off)."""
    return os.environ.get("ARIA_WEEKEND_CHAT", "1") != "0"


def free_day_voice() -> bool:
    """On free days she speaks her lines (ARIA_FREE_DAY_VOICE=0 in Engines/.env keeps them as bubbles only)."""
    return os.environ.get("ARIA_FREE_DAY_VOICE", "1") != "0"


def _ask(probe, default=None):
    try:
        return probe()
    except Exception:
        return default


class Companion:
    """Shows Aria's avatar while she sleeps, after school and while the laptop is used. After school she never
    speaks, never opens the microphone and never calls the model; on a free day she says her lines out loud (_say).
    Never touches the UI while Aria is awake (her conversation owns it)."""

    def __init__(self, aria, ui, probes: Probes, clock=time.time, now=dt.datetime.now):
        self.aria, self.ui, self.probes, self.clock, self.now = aria, ui, probes, clock, now
        self.reactions = Reactions()
        self.on = False             # she's on screen as the companion
        self.was_on = False         # she was, until Aria woke for a conversation: she comes back after it
        self.last_wake = None       # when she last greeted (a self-wake, or a conversation after school)
        self.dismissed_day = None   # "go to sleep" was said that day: off until away a long while
        self._longest_idle = 0.0    # the longest idle seen since the last input
        self.away_s = 0.0           # how long the user was away before the latest input
        self._app, self._app_since = None, 0.0
        self._test_sent = False         # the test last sent to her page (False: none sent yet)
        self._rain_sent = None          # whether rain is coming, as last sent (None: not sent yet)
        self._lock = threading.RLock()  # the loop's thread and Aria's (dismissed, after_conversation)
        self.openers = Openers()
        self._opener_busy = False       # an opener is being worded (in its own thread)
        self._answering = False         # Aria woke while an opener was up: talking now answers it
        self._watch_since = None        # when video in front started (for the break nudge)
        self._run = lambda fn: threading.Thread(target=fn, daemon=True).start()

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("ARIA_COMPANION", "1") != "0"

    def start(self):
        """Runs the loop. Switched off (ARIA_COMPANION=0) it only keeps her page told about the next test, for the
        card she holds up while awake."""
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not getattr(self.aria, "_shutting_down", False):
            try:
                self.tick()
            except Exception as e:
                print(f"[Companion] {type(e).__name__}: {e}")
            time.sleep(TICK_S)

    def dismissed(self):
        """The user sent her to sleep: no companion until they were away a long while, or tomorrow."""
        with self._lock:
            self.on = self.was_on = False
            self.dismissed_day = self.now().date()
            self.away_s = 0.0

    def after_conversation(self, talked: bool = False) -> bool:
        """Aria is going back to sleep by herself after a conversation (called from her loop, right then): should
        her avatar stay as the companion? Then Aria shows "companion" instead of "sleeping", with no fade between.
        A conversation after school, while the user is at the laptop, counts as the day's greeting. `talked`: the user
        said something in it, so they saw her (reading her reply leaves the mouse still for more than ACTIVE_S)."""
        p = self.probes
        with self._lock:
            was = self.on or self.was_on
            self.on = self.was_on = False
            answering, self._answering = self._answering, False
            if answering and talked:
                self.openers.answered()
            if self.dismissed_day is not None:
                return False
            now = self.now()
            idle = _ask(p.idle_s)
            if not school_over(now, _ask(p.school_span, UNKNOWN)) or idle is None \
                    or should_doze(idle, over=True, busy_quiet=False) \
                    or any(_ask(probe, True) for probe in (p.quiet, p.locked, p.fullscreen, p.on_call)):
                return False
            if not was:
                if idle > ACTIVE_S and not talked:
                    return False                    # nobody saw that wake (a reminder while away): greet later
                self.last_wake = now                # talking after school counts as the greeting
            self.on = True
            self._app, self._app_since = None, self.clock()
            self.openers.woke(self.clock())         # no opener right on top of the conversation
            return True

    def _track_idle(self, idle):
        if idle is None:
            return
        self._longest_idle = max(self._longest_idle, idle)
        if idle <= ACTIVE_S:
            if self._longest_idle > ACTIVE_S:
                self.away_s = self._longest_idle
            self._longest_idle = idle

    def tick(self):
        with self._lock:
            if not self.enabled():
                self._send_test()
                self._send_rain()
                return
            self._tick()

    def _tick(self):
        p = self.probes
        self._send_test()
        self._send_rain()
        if getattr(self.aria, "awake", False):
            if self.on:
                self.on, self.was_on = False, True      # her conversation owns the screen now
                self._answering = self.openers.open_since(self.clock())
            return
        now = self.now()
        idle = _ask(p.idle_s)
        self._track_idle(idle)
        if self.on:
            if self.aria._sleep_request.is_set():          # the menu's "go to sleep" while only the companion is up
                self.aria._sleep_request.clear()
                self.on, self.was_on = False, False
                self.dismissed_day, self.away_s = now.date(), 0.0
                self.ui.set_state("sleeping")
                return
            over = school_over(now, _ask(p.school_span, UNKNOWN))
            if should_doze(idle, over=over, busy_quiet=bool(_ask(p.quiet, True) or _ask(p.locked, True))):
                self.on = False
                self.ui.set_state("sleeping")
                print("[Companion] dozed off")
                return
            self._react()
            return

        self.was_on = False
        if self.dismissed_day is not None:
            if self.dismissed_day == now.date() and self.away_s < AWAY_S:
                return
            self.dismissed_day = None
        if idle is None:
            return
        over = school_over(now, _ask(p.school_span, UNKNOWN))
        if not over:
            return
        busy = any(_ask(probe, True) for probe in (p.quiet, p.locked, p.fullscreen, p.on_call))
        if may_self_wake(now, over=over, idle_s=idle, away_s=self.away_s, last_wake=self.last_wake, busy=busy):
            self.last_wake, self.away_s = now, 0.0
            self._show()
            self.openers.woke(self.clock())
            self._say(wake_line(now, self._next_test(now), _ask(p.rain_soon)), now)
            print("[Companion] woke")

    def _say(self, line, now):
        """One line of hers: a bubble after school; on a free day she says it out loud as well (Aria.speak: the
        bubble and her voice, or only the bubble when the voice is muted or missing). Speaking takes a while, so it
        runs off the loop; afterwards her avatar goes back to keeping you company."""
        speak = getattr(self.aria, "speak", None)
        if not (speak and free_day_voice() and free_day(now, _ask(self.probes.school_span, UNKNOWN))):
            self.ui.message("aria", line)
            return

        def work():
            try:
                speak(line)
            except Exception as e:
                print(f"[Companion] couldn't say it: {type(e).__name__}: {e}")
                self.ui.message("aria", line)
            with self._lock:
                if self.on and not getattr(self.aria, "awake", False):
                    self.ui.set_state("companion")      # (her voice switched the avatar to "speaking")
        self._run(work)

    def _next_test(self, now):
        return next_test(_ask(self.probes.tests, []), now, _ask(self.probes.school_span, UNKNOWN))

    def _send_test(self):
        """The next test goes to her page (for the card she holds up now and then) whenever it changes. Data, not a
        state change: also while Aria is awake."""
        card = self._next_test(self.now())
        test = {"subject": card["subject"], "when": card.get("when", "")} if card and card.get("subject") else None
        if test != self._test_sent:
            self._test_sent = test
            self.ui.set_test(test)

    def _send_rain(self):
        """Whether rain is coming goes to her page (her umbrella) whenever it changes; can't tell = no."""
        rain = bool(_ask(self.probes.rain_soon))
        if rain != self._rain_sent:
            self._rain_sent = rain
            self.ui.set_rain(rain)

    def _show(self):
        self.on = True
        self._app, self._app_since = None, self.clock()
        self.ui.set_state("companion")

    def _react(self):
        p = self.probes
        wm, title = _ask(p.active_window, (None, "")) or (None, "")
        kind = app_kind(wm, title)
        t = self.clock()
        if kind != self._app:
            self._app, self._app_since = kind, t
        if kind == "video":
            self._watch_since = self._watch_since or t
        elif kind is not None:
            self._watch_since = None                # (a moment on Aria herself doesn't end a video stretch)
        if kind in ("call", "game") or _ask(p.fullscreen, True) or _ask(p.on_call, True):
            return
        now = self.now()
        free = free_day(now, _ask(p.school_span, UNKNOWN)) and opener_enabled()
        if free and kind is not None and t - self._app_since >= SETTLE_S and self._opener(kind, t, now):
            return
        if kind is None:
            return
        gesture, line = self.reactions.pick(kind, t, t - self._app_since,
                                            body_every=BODY_EVERY_S / 2 if free else BODY_EVERY_S, lines=not free)
        if not gesture:
            return
        self.ui.avatar_act(gesture)
        rect = _ask(p.active_rect)
        if rect:
            self.ui.glance((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2, GLANCE_S)
        if line:
            self.ui.message("aria", line)

    def _opener_facts(self, kind, t, now):
        """What an opener may be about, right now (Engines/Openers.py pick)."""
        p = self.probes
        return {"kind": kind, "hour": now.hour, "test": self._next_test(now), "today": _ask(p.today_items, []) or [],
                "watch_min": (t - self._watch_since) / 60 if self._watch_since else 0, "rain": bool(_ask(p.rain_soon))}

    def _opener(self, kind, t, now) -> bool:
        """Starts an opener if one is due: picked here, worded off the lock (the model may take a while), shown only if
        she is still up as the companion. True when one was started."""
        if self._opener_busy or not self.openers.due(t, now.date()):
            return False
        topic = self.openers.pick(self._opener_facts(kind, t, now))
        self._opener_busy = True

        def work():
            try:
                write = getattr(self.aria, "write_opener", None)
                line = clean_line(_ask(lambda: write(prompt_for(topic))) if write else None, topic.fallback)
                with self._lock:
                    if not self.on or getattr(self.aria, "awake", False):
                        return                          # she went to sleep, or a conversation started meanwhile
                    self.openers.shown(self.clock(), topic, self.now().date())
                    self.reactions.body_at = self.clock()   # the opener's gesture counts as this round's
                    self.ui.avatar_act(topic.gesture)
                    self._say(line, self.now())
                    remember = getattr(self.aria, "remember_said", None)
                    if remember:
                        _ask(lambda: remember(line))
                    print(f"[Companion] opener ({topic.name}): {line}")
            finally:
                self._opener_busy = False
        self._run(work)
        return True

