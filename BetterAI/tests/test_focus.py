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
