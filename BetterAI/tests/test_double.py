"""Two messages in a row (Engines/Double.py and its use in main.py)."""
import threading

import main
from Engines import Double


class RecordingUI(main.NullUI):
    def __init__(self):
        self.said = []

    def message(self, role, text):
        self.said.append((role, text))


def test_a_reaction_and_a_question_become_two_bubbles():
    assert Double.split_reply("Haha no way. Did you actually finish it?") == ["Haha no way.", "Did you actually finish it?"]


def test_a_short_reaction_first_is_its_own_bubble():
    assert Double.split_reply("Oh nice! That sounds like a fun weekend.") == ["Oh nice!", "That sounds like a fun weekend."]


def test_one_sentence_lists_and_long_replies_stay_whole():
    assert Double.split_reply("Fair enough.") == ["Fair enough."]
    assert Double.split_reply("Here:\n- milk\n- eggs") == ["Here:\n- milk\n- eggs"]
    long = "That was a long and rather detailed day at school for you. You learned quite a lot of things today."
    assert Double.split_reply(long) == [long]


def test_follow_up_only_after_casual_chat_that_asked_nothing():
    yes = lambda: 0.0
    assert Double.want_follow_up("Sounds fun.", True, [], 5, rand=yes)
    assert not Double.want_follow_up("What are you up to?", True, [], 5, rand=yes)
    assert not Double.want_follow_up("Sounds fun.", False, [], 5, rand=yes)
    assert not Double.want_follow_up("Done.", True, [("set_volume", {})], 5, rand=yes)
    assert not Double.want_follow_up("Sounds fun.", True, [], 1, rand=yes)          # one just happened
    assert not Double.want_follow_up("Sounds fun.", True, [], 5, rand=lambda: 0.9)  # not every time


def test_bad_follow_ups_are_dropped():
    assert Double.clean_follow_up("SKIP", "x") is None
    assert Double.clean_follow_up("Sounds fun.", "Sounds fun.") is None
    assert Double.clean_follow_up("Let me know if you need anything!", "ok", main.ROBOTIC_RE) is None
    assert Double.clean_follow_up(" ".join(["word"] * 30), "ok") is None
    assert Double.clean_follow_up('"wait, was that the new one?"', "Sounds fun.") == "wait, was that the new one?"


def test_typed_small_talk_is_shown_as_two_bubbles(aria, monkeypatch):
    aria.ui = RecordingUI()
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(aria, "handle_turn", lambda text: ("Haha no way. Did you finish it?", []))
    aria._turn_and_speak("i played games all day")
    assert aria.ui.said == [("aria", "Haha no way."), ("aria", "Did you finish it?")]


def test_commands_stay_one_bubble(aria, monkeypatch):
    aria.ui = RecordingUI()
    monkeypatch.setattr(aria, "handle_turn", lambda text: ("Done. Want it louder?", [("set_volume", {})]))
    aria._turn_and_speak("turn the volume down")
    assert aria.ui.said == [("aria", "Done. Want it louder?")]


def _no_wait(monkeypatch):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(Double, "FOLLOW_UP_DELAY", (0, 0))


def test_follow_up_is_written_and_queued(aria, monkeypatch):
    _no_wait(monkeypatch)
    aria.llm.chats = ["wait, was it the new zelda?"]
    aria._write_follow_up("i played games all day", "Sounds like a chill day.", aria._turn_count())
    assert aria._follow_ups_queue().get_nowait()[1] == "wait, was it the new zelda?"


def test_follow_up_is_dropped_when_lala_writes_first(aria, monkeypatch):
    _no_wait(monkeypatch)
    aria.llm.chats = ["wait, was it the new zelda?"]
    turn = aria._turn_count()
    aria._turns_done = turn + 1                         # another turn started meanwhile
    aria._write_follow_up("i played games all day", "Sounds like a chill day.", turn)
    assert aria._follow_ups_queue().empty()
    assert aria.llm.prompts == []                       # not even written


def test_queued_follow_up_is_said_and_remembered(aria):
    aria.ui = RecordingUI()
    aria._turns_done = 4
    aria._follow_ups_queue().put((4, "wait, was it the new zelda?"))
    assert aria._say_follow_up() == "wait, was it the new zelda?"
    assert aria.ui.said == [("aria", "wait, was it the new zelda?")]
    assert aria._recent[-1] == [{"role": "assistant", "content": "wait, was it the new zelda?"}]


def test_stale_follow_up_is_not_said(aria):
    aria.ui = RecordingUI()
    aria._turns_done = 5
    aria._follow_ups_queue().put((4, "too late"))
    assert aria._say_follow_up() is None
    assert aria.ui.said == []
