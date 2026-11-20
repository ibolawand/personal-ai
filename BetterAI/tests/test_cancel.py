"""Short cancel commands ("cancel", "stop the timer", "no don't do that") are decided in code (Engines/Cancel.py):
the model picked the wrong thing to cancel, couldn't see a running focus session and said "I won't set the timer"
while leaving it running."""
import types

import pytest

import main  # noqa: F401  (imported here, before the sandbox replaces subprocess, as the other tests do)
from Engines.Cancel import cancel_target

TIMER = {"id": 7, "kind": "timer", "text": "sleep", "created": 100.0}
TEA = {"id": 8, "kind": "timer", "text": "tea", "created": 50.0}
STUDY = {"id": 3, "kind": "reminder", "text": "study for exam", "created": 120.0}


def target(text, pending=(), focus=False, just_set=None):
    return cancel_target(text, pending=list(pending), focus_running=focus, just_set=just_set)


def test_exit_the_timer_cancels_the_timer_not_a_reminder():
    # (from the log: "exit the timer" cancelled the reminder 'study for exam')
    assert target("exit the timer", [TIMER, STUDY]) == ("item", TIMER)


def test_a_bare_cancel_stops_the_focus_session_that_is_running():
    # (from the log: "cancel" during round 3 of 4 went to the reminder tool, which can't see focus sessions)
    assert target("cancel", [STUDY], focus=True) == ("focus", None)
    assert target("stop the pomodoro", [TIMER], focus=True) == ("focus", None)
    assert target("end the focus session") == ("focus", None)            # nothing running: said so in main.py


def test_no_dont_do_that_takes_back_what_she_just_set():
    # (from the log: she set a 'sleep' timer, "no don't do that", and she only said she wouldn't)
    just = {"kind": "timer", "item": TIMER, "ago": 20}
    assert target("no don't do that", [TIMER, STUDY], just_set=just) == ("item", TIMER)
    assert target("never mind", [TIMER], just_set=just) == ("item", TIMER)
    assert target("cancel that", [TEA, TIMER, STUDY], just_set=just) == ("item", TIMER)
    focus = {"kind": "focus", "item": None, "ago": 10}
    assert target("no, don't", [], focus=True, just_set=focus) == ("focus", None)


def test_dont_do_that_without_anything_just_set_is_left_to_the_model():
    assert target("no don't do that", [TIMER]) is None
    assert target("never mind", [TIMER], just_set={"kind": "timer", "item": TIMER, "ago": 600}) is None
    assert target("no") is None


def test_cancel_with_a_name_picks_that_one():
    assert target("cancel the tea timer", [TIMER, TEA]) == ("item", TEA)
    assert target("stop the reminder", [TIMER, STUDY]) == ("item", STUDY)


def test_a_bare_cancel_prefers_what_was_just_set_then_the_newest_timer():
    assert target("cancel", [TEA, TIMER, STUDY]) == ("item", TIMER)
    assert target("cancel", [STUDY]) == ("item", STUDY)
    assert target("cancel it", [TEA, STUDY], just_set={"kind": "reminder", "item": STUDY, "ago": 5}) == ("item", STUDY)


def test_nothing_to_cancel_is_an_answer_too():
    assert target("cancel the timer", [STUDY]) == ("none", "timer")
    assert target("cancel", []) == ("none", None)


def test_other_cancels_are_left_to_the_model():
    for text in ["cancel my meeting tomorrow", "cancel the dentist appointment", "delete the shopping list",
                 "stop the music", "stop it, you're annoying", "can you cancel the timer and tell me a joke",
                 "how do I cancel a subscription", "stop talking", "remove milk from the list"]:
        assert target(text, [TIMER, STUDY], focus=True) is None, text


# ── in a turn (main.Aria._cancel_command): done in code, the model never sees these ──

@pytest.fixture
def cancelling(aria, memory):
    from Engines.Reminders import Reminders
    aria.reminders = Reminders(memory, on_due=lambda r: None)
    aria.focus = types.SimpleNamespace(in_session=False, stopped=0)

    def stop():
        aria.focus.stopped += 1
        aria.focus.in_session = False
        return "Focus session ended early after 12 minutes."
    aria.focus.stop = stop
    return aria


def kinds(aria):
    return [(r["kind"], r["text"]) for r in aria.reminders.pending(("timer", "reminder"))]


def test_exit_the_timer_cancels_the_timer_and_the_model_is_not_asked(cancelling):
    a = cancelling
    a.reminders.set_reminder("study for exam", in_minutes=60)
    a.reminders.set_timer(7, "sleep")
    reply, used = a._handle_turn("exit the timer")
    assert reply == "Okay, cancelled the sleep timer."
    assert kinds(a) == [("reminder", "study for exam")]
    assert used == [("cancel", reply)] and a.llm.prompts == []


def test_cancel_during_a_focus_session_stops_it(cancelling):
    a = cancelling
    a.focus.in_session = True
    a.reminders.set_reminder("study for exam", in_minutes=60)
    reply, _ = a._handle_turn("cancel")
    assert reply.startswith("Focus session ended early") and a.focus.stopped == 1
    assert kinds(a) == [("reminder", "study for exam")], "the reminder is left alone"


def test_no_dont_do_that_takes_back_the_timer_she_just_set(cancelling):
    a = cancelling
    a.reminders.set_timer(7, "sleep")
    a._note_what_was_set([("set_timer", "Timer set for 7 minutes (sleep).")])
    reply, _ = a._handle_turn("no don't do that")
    assert reply == "Okay, cancelled the sleep timer." and kinds(a) == []
    # long after, "no don't do that" is just conversation again (the model answers)
    a.reminders.set_timer(5, "tea")
    a._note_what_was_set([("set_timer", "")])
    a._just_set["at"] -= 600
    a.llm.replies = [("Okay.", [])]
    a._handle_turn("no don't do that")
    assert kinds(a) == [("timer", "tea")]
