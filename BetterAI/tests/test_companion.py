"""Aria's companion mode: she wakes herself after school, stays while the laptop is used and reacts to apps."""
import datetime as dt

import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

from Engines.Companion import school_over, may_self_wake, should_doze, UNKNOWN

D = dt.datetime(2026, 11, 16, 15, 0)        # a Monday


def test_school_over_after_last_lesson_only():
    assert not school_over(D.replace(hour=13, minute=20), (755, 1325))
    assert school_over(D.replace(hour=13, minute=25), (755, 1325))
    assert not school_over(D.replace(hour=7), (755, 1325))          # morning before school isn't "after school"
    assert school_over(D, None)                                     # no lessons today (holiday)


def test_unknown_timetable_is_school_until_four_on_weekdays():
    assert not school_over(D.replace(hour=15, minute=59), UNKNOWN)
    assert school_over(D.replace(hour=16), UNKNOWN)
    assert school_over(dt.datetime(2026, 11, 15, 10, 0), UNKNOWN)  # Sunday


def test_self_wake_once_a_day_or_after_two_hours_away():
    kw = dict(over=True, idle_s=2, away_s=0, busy=False)
    assert may_self_wake(D, last_wake=None, **kw)
    assert not may_self_wake(D, last_wake=D.replace(hour=14), **kw)
    assert may_self_wake(D, last_wake=D.replace(hour=14), **{**kw, "away_s": 2 * 3600})
    assert may_self_wake(D, last_wake=D - dt.timedelta(days=1), **kw)


def test_no_self_wake_in_school_idle_busy_or_unknown_idle():
    kw = dict(away_s=0, last_wake=None)
    assert not may_self_wake(D, over=False, idle_s=2, busy=False, **kw)
    assert not may_self_wake(D, over=True, idle_s=60, busy=False, **kw)    # not using the laptop right now
    assert not may_self_wake(D, over=True, idle_s=2, busy=True, **kw)      # fullscreen / call / locked / quiet hours
    assert not may_self_wake(D, over=True, idle_s=None, busy=False, **kw)  # can't tell


def test_doze_after_ten_idle_minutes_a_lesson_or_quiet_hours():
    assert not should_doze(599, over=True, busy_quiet=False)
    assert should_doze(600, over=True, busy_quiet=False)
    assert should_doze(5, over=False, busy_quiet=False)
    assert should_doze(5, over=True, busy_quiet=True)
    assert should_doze(None, over=True, busy_quiet=False)


from Engines.Companion import app_kind, Reactions, LINES, wake_line  # noqa: E402


def test_app_kinds():
    assert app_kind("code", "main.py - BetterAI - Visual Studio Code") == "code"
    assert app_kind("firefox", "Lofi beats - YouTube — Mozilla Firefox") == "video"
    assert app_kind("firefox", "Stack Overflow — Mozilla Firefox") == "browser"
    assert app_kind("mynotion", "MyNotion") == "mynotion"
    assert app_kind("zoom", "Zoom Meeting") == "call"
    assert app_kind("firefox", "Meet - abc-defg-hij — Mozilla Firefox") == "call"
    assert app_kind("aria", "") is None and app_kind("python3", "Aria") is None and app_kind(None, "") is None


def test_reaction_rules():
    r = Reactions()
    assert r.pick("code", 0, in_app_s=30) == (None, None)            # just switched: wait
    g, line = r.pick("code", 100, in_app_s=100)
    assert g == "think" and line in LINES["code"]
    assert r.pick("code", 200, in_app_s=200) == (None, None)          # body cooldown
    g, line = r.pick("video", 100 + 6 * 60, in_app_s=90)
    assert g and line is None                                         # body ok, line still cooling down
    _, line = r.pick("video", 100 + 31 * 60, in_app_s=90)
    assert line in LINES["video"]
    assert r.pick("call", 10**6, in_app_s=999) == (None, None)
    assert r.pick(None, 2 * 10**6, in_app_s=999) == (None, None)


def test_same_kind_never_gets_two_lines_in_a_row():
    r = Reactions()
    _, first = r.pick("code", 1000, in_app_s=999)
    g, line = r.pick("code", 1000 + 31 * 60, in_app_s=999)
    assert first and g == "think" and line is None


def test_lines_do_not_repeat_until_bank_used():
    r, seen, t = Reactions(), [], 0
    for i in range(len(LINES["code"]) * 2):
        t += 31 * 60
        kind = "code" if i % 2 == 0 else "video"
        _, line = r.pick(kind, t, in_app_s=999)
        if kind == "code":
            seen.append(line)
    n = len(LINES["code"])
    assert None not in seen and len(set(seen[:n])) == n


def test_wake_line():
    test = {"subject": "Maths", "when": "Thursday", "days": 3}
    assert "Maths" in wake_line(D, test, rain=False)
    assert "umbrella" in wake_line(D, None, rain=True)
    assert len(wake_line(D, None, rain=None).split()) <= 12
    assert len(wake_line(D, test, rain=True).split()) <= 14


# ── the loop ──

import threading  # noqa: E402

import pytest  # noqa: E402

from Engines.Companion import Companion, Probes, ACTIVE_S, AWAY_S  # noqa: E402


class FakeAria:
    def __init__(self, option=1):
        self.awake, self.option = False, option
        self._sleep_request = threading.Event()
        self._wake_event = threading.Event()

    def speak(self, text):
        raise AssertionError(f"companion must never speak: {text!r}")


class FakeUI:
    def __init__(self):
        self.log, self.tests, self.rains = [], [], []

    def set_state(self, s): self.log.append(("state", s))
    def message(self, role, text): self.log.append(("message", role, text))
    def avatar_act(self, name): self.log.append(("act", name))
    def glance(self, x, y, s): self.log.append(("glance", x, y))
    def set_mic_open(self, on): self.log.append(("mic", on))
    def set_test(self, card): self.tests.append(card)       # data for the card, kept apart from what she shows
    def set_rain(self, on): self.rains.append(on)           # and for the umbrella

    def of(self, kind):
        return [e for e in self.log if e[0] == kind]


@pytest.fixture
def world():
    """A Monday 15:00 after school (lessons 7:55-13:25), someone using VS Code, nothing busy."""
    w = type("W", (), {})()
    w.now = D
    w.t = 10_000.0
    w.idle = 2.0
    w.window = ("code", "main.py - Visual Studio Code")
    w.flags = {"fullscreen": False, "on_call": False, "locked": False, "quiet": False}
    w.span = (755, 1325)
    w.test = {"subject": "Maths", "when": "Thursday", "days": 3}
    w.more = []                                     # later tests (TestPrep's cards, nearest first)
    w.rain = False
    probes = Probes(idle_s=lambda: w.idle, active_window=lambda: w.window,
                    active_rect=lambda: (100, 100, 900, 700),
                    fullscreen=lambda: w.flags["fullscreen"], on_call=lambda: w.flags["on_call"],
                    locked=lambda: w.flags["locked"], quiet=lambda: w.flags["quiet"],
                    school_span=lambda: w.span, tests=lambda: [c for c in (w.test, *w.more) if c],
                    rain_soon=lambda: w.rain)
    w.aria, w.ui = FakeAria(), FakeUI()
    w.c = Companion(w.aria, w.ui, probes, clock=lambda: w.t, now=lambda: w.now)

    def step(seconds=3, **change):
        for k, v in change.items():
            setattr(w, k, v)
        w.t += seconds
        w.now += dt.timedelta(seconds=seconds)
        w.c.tick()
    w.step = step
    return w


def test_wakes_quietly_after_school_with_a_line(world):
    world.step()
    assert world.ui.of("state") == [("state", "companion")]
    [(_, role, line)] = world.ui.of("message")
    assert role == "aria" and "Maths" in line
    assert world.ui.of("act") == []                 # the overlay waves by itself when she appears


def test_no_wake_during_a_lesson_or_when_busy(world):
    world.step(span=(755, 1600))
    assert world.ui.log == []
    world.span = (755, 1325)
    for flag in world.flags:
        world.flags[flag] = True
        world.step()
        world.flags[flag] = False
    assert world.ui.log == []


def test_no_wake_while_not_using_the_laptop(world):
    world.step(idle=ACTIVE_S + 5)
    assert world.ui.log == []


def test_dozes_after_ten_idle_minutes(world):
    world.step()
    world.step(idle=599)
    assert world.ui.of("state")[-1] == ("state", "companion")
    world.step(idle=600)
    assert world.ui.of("state")[-1] == ("state", "sleeping")


def test_dozes_when_an_afternoon_lesson_starts(world):
    world.step()
    world.step(span=(755, 1700))
    assert world.ui.of("state")[-1] == ("state", "sleeping")


def test_returns_after_a_conversation_without_a_line_or_a_fade(world):
    """Review I2: Aria's _go_to_sleep asks right away, so the state goes listening -> companion (no orb between)."""
    world.step()
    world.aria.awake = True
    n = len(world.ui.log)
    world.step()
    assert len(world.ui.log) == n                   # never touches the UI while she's awake
    world.aria.awake = False
    assert world.c.after_conversation() is True and world.c.on
    world.step()
    assert world.ui.of("state")[-1] == ("state", "companion") and len(world.ui.of("message")) == 1


def test_a_conversation_after_school_counts_as_the_greeting(world):
    world.aria.awake = True
    world.step()
    world.aria.awake = False
    assert world.c.after_conversation() is True
    world.step()
    assert world.ui.of("message") == []


def test_a_wake_nobody_saw_does_not_use_up_the_greeting(world):
    """Review I4: a reminder woke her while the user was away; when they come back she still greets them."""
    world.aria.awake = True
    world.step(idle=900)
    world.aria.awake = False
    assert world.c.after_conversation() is False and not world.c.on
    world.step(idle=900)
    world.step(idle=1)
    assert world.ui.of("state")[-1] == ("state", "companion") and len(world.ui.of("message")) == 1


def test_a_conversation_you_took_part_in_keeps_her_on_screen_while_you_read(world):
    """She fell back to the orb a minute after her reply: reading it, you hadn't touched the mouse for 10 s, so the
    "nobody saw that wake" rule sent her away. Talking to her means you saw her."""
    world.aria.awake = True
    world.step(idle=60)
    world.aria.awake = False
    assert world.c.after_conversation(talked=True) is True and world.c.on
    world.step(idle=61)
    assert world.c.on and ("state", "sleeping") not in world.ui.of("state")


def test_no_return_after_a_conversation_when_school_starts_or_busy(world):
    world.step()
    world.aria.awake = True
    world.step()
    world.aria.awake = False
    world.flags["fullscreen"] = True
    assert world.c.after_conversation() is False and not world.c.on


def test_only_one_greeting_a_day_unless_away_two_hours(world):
    world.step()
    world.step(idle=600)                            # dozes
    world.step(idle=2)
    assert world.ui.of("state")[-1] == ("state", "sleeping")
    world.step(seconds=AWAY_S, idle=AWAY_S)
    world.step(idle=1)
    assert world.ui.of("state")[-1] == ("state", "companion") and len(world.ui.of("message")) == 2


def test_dismissed_stays_off_until_two_hours_away(world):
    world.step()
    world.c.dismissed()
    world.ui.set_state("sleeping")
    world.step(seconds=4 * 3600, idle=2)            # later that day, using the laptop: still off
    assert world.ui.of("state")[-1] == ("state", "sleeping")
    world.step(seconds=AWAY_S, idle=AWAY_S)
    world.step(idle=1)
    assert world.ui.of("state")[-1] == ("state", "companion")


def test_the_menus_go_to_sleep_ends_companion_and_counts_as_dismissed(world):
    world.step()
    world.aria._sleep_request.set()
    world.step()
    assert world.ui.of("state")[-1] == ("state", "sleeping") and not world.aria._sleep_request.is_set()
    world.step(seconds=600, idle=2)
    assert world.ui.of("state")[-1] == ("state", "sleeping")


def test_reacts_to_the_app_with_gesture_glance_and_line(world):
    world.step()
    for _ in range(25):                             # 75 s in VS Code
        world.step()
    assert world.ui.of("act") == [("act", "think")]
    assert world.ui.of("glance") == [("glance", 500, 400)]
    assert world.ui.of("message")[-1][2] in LINES["code"]


def test_no_reactions_during_a_call_or_fullscreen(world):
    world.step()
    world.flags["fullscreen"] = True
    for _ in range(30):
        world.step()
    world.flags["fullscreen"] = False
    world.window = ("zoom", "Zoom Meeting")
    for _ in range(30):
        world.step()
    assert world.ui.of("act") == []


def test_probe_failures_never_crash(world):
    def boom():
        raise OSError("no dbus")
    for name in ("idle_s", "active_window", "active_rect", "fullscreen", "on_call", "locked", "quiet",
                 "school_span", "tests", "rain_soon"):
        setattr(world.c.probes, name, boom)
    world.step()
    assert world.ui.log == []


def test_voice_mode_never_opens_the_mic_or_wakes_her(world):
    world.aria.option = 2
    world.step()
    assert world.ui.of("mic") == [] and not world.aria._wake_event.is_set()


def test_switched_off_in_env_she_never_wakes_but_the_card_still_gets_its_test(world, monkeypatch):
    """Review (piece 2): the test card is part of her idle life while awake too, not only of the companion."""
    monkeypatch.setenv("ARIA_COMPANION", "0")
    assert not world.c.enabled()
    world.step()
    world.step()
    assert world.ui.log == [] and world.ui.tests == [{"subject": "Maths", "when": "Thursday"}]


def test_go_to_sleep_by_the_user_dismisses_the_companion(aria):
    told = []
    aria.companion = type("C", (), {"dismissed": lambda self: told.append("off"),
                                    "after_conversation": lambda self, **_: False})()
    aria._sleep_request = threading.Event()
    aria._go_to_sleep()
    assert told == []                               # dozing off after a quiet minute: she comes back as companion
    aria._go_to_sleep(by_user=True)
    assert told == ["off"]


def test_a_phone_message_during_companion_keeps_her_on_screen(aria, monkeypatch):
    """Review I1: a Telegram turn while only the companion is up used to put the orb back ("sleeping")."""
    import contextlib
    shown = []
    aria.ui.set_state = shown.append
    aria._track_ui_state()
    aria.awake = False
    aria.ui.set_state("companion")
    monkeypatch.setattr(aria, "handle_turn", lambda text, **kw: (aria.ui.set_state("thinking") or "ok", []))
    monkeypatch.setattr(aria.tools, "phone", lambda: contextlib.nullcontext(), raising=False)
    aria.answer_phone("hi")
    assert shown[-1] == "companion"


def test_go_to_sleep_lands_on_the_companion_when_she_stays(aria):
    shown = []
    aria.ui.set_state = shown.append
    aria._sleep_request = threading.Event()
    aria.companion = type("C", (), {"after_conversation": lambda self, **_: True, "dismissed": lambda self: None,
                                    "on": True})()
    aria._go_to_sleep()
    assert shown[-1] == "companion" and "sleeping" not in shown
    aria._go_to_sleep(by_user=True)
    assert shown[-1] == "sleeping"


def test_menu_sleep_while_asleep_leaves_no_stale_request(aria):
    """Review M6 (re-graded): a "go to sleep" click while Aria sleeps must not end her next real wake at once;
    with only the companion up it sends the companion to sleep instead."""
    shown, told = [], []
    aria.ui.set_state = shown.append
    aria._sleep_request = threading.Event()
    aria.awake = False
    aria.companion = type("C", (), {"on": True, "dismissed": lambda self: told.append("off")})()
    aria.request_sleep()
    assert not aria._sleep_request.is_set() and told == ["off"] and shown[-1] == "sleeping"
    aria.companion.on = False
    aria.request_sleep()
    assert not aria._sleep_request.is_set()
    aria.awake = True
    aria.request_sleep()
    assert aria._sleep_request.is_set()


def test_next_test_is_sent_when_it_changes(world):
    world.aria.awake = True                         # data, not a state change: sent while she's awake too
    world.step()
    world.aria.awake = False
    world.step()
    world.step()
    assert world.ui.tests == [{"subject": "Maths", "when": "Thursday"}]
    world.test = None
    world.step()
    assert world.ui.tests[-1] is None


def test_a_test_written_this_morning_is_not_shown_after_school(world):
    """Review (piece 2): at 15:00, a test dated today is over; the card and the greeting show the next one."""
    world.test = {"subject": "Maths", "when": "today", "days": 0}
    world.more = [{"subject": "AM", "when": "Friday", "days": 4}]
    world.step()
    assert world.ui.tests[-1] == {"subject": "AM", "when": "Friday"}
    assert "Maths" not in world.ui.of("message")[0][2] and "AM" in world.ui.of("message")[0][2]


def test_a_test_today_is_shown_before_it_is_written(world):
    world.test = {"subject": "Maths", "when": "today", "days": 0}
    world.span = (755, 1600)                        # still at school at 15:00
    world.step()
    assert world.ui.tests[-1] == {"subject": "Maths", "when": "today"}


def test_rain_is_sent_when_it_changes(world, monkeypatch):
    world.rain = True
    world.step()
    world.step()
    assert world.ui.rains == [True]
    world.rain = None                               # can't tell: no umbrella
    world.step()
    assert world.ui.rains == [True, False]
    monkeypatch.setenv("ARIA_COMPANION", "0")       # the umbrella is part of her idle life while awake too
    world.rain = True
    world.step()
    assert world.ui.rains[-1] is True


def test_typing_keeps_the_conversation_going(aria):
    import time
    aria.ui.typed_at = 0.0
    assert not aria._typing_now()
    aria.ui.typed_at = time.monotonic() - 5
    assert aria._typing_now()
    aria.ui.typed_at = time.monotonic() - 60
    assert not aria._typing_now()


def test_only_while_she_shows_isnt_speaking_and_no_lesson(aria):
    import datetime as dt
    aria._track_ui_state()
    aria.awake = True
    from types import SimpleNamespace as NS
    aria.companion = NS(on=False, probes=NS(school_span=lambda: None), now=lambda: dt.datetime(2026, 11, 14, 17, 0))
    aria.ui.set_state("listening")
    assert aria._may_bob()
    aria.ui.set_state("speaking")
    assert not aria._may_bob()
    aria.ui.set_state("listening")
    aria.companion.probes.school_span = lambda: (800, 1800)    # a lesson until 18:00
    assert not aria._may_bob()
    aria.companion.probes.school_span = lambda: None
    aria.awake = False
    assert not aria._may_bob()                                  # asleep: the orb, nobody to bob
    aria.companion.on = True
    assert aria._may_bob()
