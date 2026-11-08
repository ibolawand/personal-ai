import time
import types

import pytest

import Engines.FocusMode as F
from Engines.Reminders import Reminders


@pytest.fixture
def focus(memory, monkeypatch, tmp_path):
    monkeypatch.setattr(F, "STATE_FILE", str(tmp_path / "focus.json"))
    reminders = Reminders(memory, on_due=lambda r: None)
    calls = []
    spotify = types.SimpleNamespace(play_playlist=lambda q: calls.append(("play", q)) or "Playing playlist 'lofi'",
                                    pause=lambda: calls.append(("pause",)))
    fm = F.FocusMode(reminders, spotify=spotify, memory=memory)
    fm.calls = calls
    return fm


def finish_block(fm, kind="focus", minutes_ago=25):
    """Pretend the current block started `minutes_ago` and its reminder just fired."""
    block = fm._block((kind,))
    fm.reminders.cancel_id(block["id"])
    fm.state["block_start"] = time.time() - minutes_ago * 60
    return fm.finish() if kind == "focus" else fm.end_break()


def test_single_session_pauses_and_restores_notifications(focus, fake_gsettings):
    msg = focus.start(25, "databases")
    assert "notifications paused" in msg and "lo-fi on" in msg
    assert fake_gsettings["display-notifications"] == "false"
    assert focus.active
    done = finish_block(focus)
    assert done.startswith("Focus session done — 25 minutes on databases")
    assert fake_gsettings["display-notifications"] == "true" and not focus.in_session
    assert ("pause",) in focus.calls


def test_notifications_stay_off_if_they_were_off(focus, fake_gsettings):
    fake_gsettings["display-notifications"] = "false"
    focus.start(25)
    finish_block(focus)
    assert fake_gsettings["display-notifications"] == "false"


def test_pomodoro_rounds_and_breaks(focus):
    assert "2 rounds of 25 minutes with 5 minute breaks" in focus.start(25, "c#", rounds=2)
    msg = finish_block(focus)
    assert msg.startswith("Round 1 of 2 done. Take a 5 minute break")
    assert not focus.active and focus.in_session                    # a break isn't "focus time"
    assert focus.status().startswith("On a break (round 1 of 2)")
    assert finish_block(focus, "focusbreak") == "Break's over — round 2 of 2. Back to it!"
    assert focus.active
    assert finish_block(focus).startswith("That's all 2 rounds — 50 minutes of focus on c#")
    assert not focus.in_session


def test_focus_stats(focus):
    focus.start(25, "databases")
    finish_block(focus, minutes_ago=30)
    focus.start(25, "c#")
    finish_block(focus, minutes_ago=50)
    out = focus.stats("today")
    assert out.startswith("1 h 20 min of focus in 2 blocks today") and "c# (50 min)" in out


def test_stop_early(focus, fake_gsettings):
    focus.start(25)
    assert focus.stop().startswith("Focus session ended early")
    assert fake_gsettings["display-notifications"] == "true" and not focus.in_session


def test_distraction_nudge_once_per_round(focus):
    said = []
    focus.on_nudge = said.append
    focus.activity = types.SimpleNamespace(current=lambda: ("Discord", 3), watching=lambda: False)
    focus.start(25)
    assert focus.check_distraction().startswith("Psst, it's still focus time — Discord can wait")
    assert focus.check_distraction() is None and len(said) == 1


def test_no_nudge_for_work_apps_or_videos_outside_focus(focus):
    focus.on_nudge = lambda t: None
    focus.activity = types.SimpleNamespace(current=lambda: ("PyCharm", 30), watching=lambda: False)
    focus.start(25)
    assert focus.check_distraction() is None
    focus.stop()
    focus.activity = types.SimpleNamespace(current=lambda: ("Firefox", 10), watching=lambda: True)
    assert focus.check_distraction() is None          # not in a session


# ── away from the desk ──

def _away(fm, minutes_ago):
    fm.idle_seconds = lambda: 600          # keyboard untouched
    fm.user_left(time.time() - minutes_ago * 60)


def test_leaving_pauses_the_block_and_coming_back_continues_it(focus):
    focus.spotify.play = lambda: focus.calls.append(("resume",))
    focus.start(25, "databases")
    due = focus._block()["due"]
    _away(focus, 4)
    focus.check_away()
    assert focus.paused and focus._block() is None and focus.active and focus.in_session
    assert abs(focus.paused["left"] - (due - (time.time() - 240))) < 2      # counted from when they left
    assert ("pause",) in focus.calls
    assert "paused while you're away" in focus.status()
    msg = focus.user_back()
    assert msg.startswith("Welcome back! I paused your focus on databases") and "29 minutes to go" in msg
    assert not focus.paused and focus._block() is not None and ("resume",) in focus.calls


def test_short_absences_and_typing_dont_pause(focus):
    focus.start(25)
    _away(focus, 2)                                  # under 3 minutes
    focus.check_away()
    assert not focus.paused
    _away(focus, 5)
    focus.idle_seconds = lambda: 10                  # camera lost the face, but they're typing
    focus.check_away()
    assert not focus.paused


def test_typing_resumes_a_paused_block(focus):
    focus.start(25)
    _away(focus, 5)
    focus.check_away()
    focus.idle_seconds = lambda: 5
    assert "Welcome back" in focus.check_away()
    assert focus._block() is not None


def test_time_away_is_not_logged(focus, memory):
    focus.start(25, "c#")
    focus.state["block_start"] = time.time() - 30 * 60       # started 30 min ago...
    _away(focus, 20)                                         # ...left after 10
    focus.check_away()
    assert focus.stop() == "Focus session ended early after 10 minutes."
    assert not focus.in_session


def test_paused_for_hours_ends_the_session(focus):
    focus.start(25)
    _away(focus, 5)
    focus.check_away()
    focus.check_away(now=time.time() + 3 * 3600)
    assert not focus.in_session


def test_breaks_are_not_paused(focus):
    focus.start(25, rounds=2)
    finish_block(focus)
    _away(focus, 5)
    focus.check_away()
    assert not focus.paused and focus._block(("focusbreak",))


def test_lights_are_only_mentioned_when_the_strip_is_plugged_in(focus, fake_gsettings):
    """She said "lights dimmed" with no LED strip connected (the controller exists even unplugged)."""
    led = []
    focus.arduino = types.SimpleNamespace(is_connected=False, set_rgb=lambda *a: led.append(a),
                                          set_effect=lambda e: led.append(e), set_brightness=lambda v: led.append(v))
    assert "lights" not in focus.start(25)
    focus.stop()
    focus.arduino.is_connected = True
    assert "lights dimmed" in focus.start(25)
