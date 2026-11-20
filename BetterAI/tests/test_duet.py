"""Aria and Claude talk together (Engines/Duet.py and Aria._duet)."""
import queue

import pytest

import main
from Engines import Duet


class RecordingUI(main.NullUI):
    def __init__(self):
        self.said = []

    def message(self, role, text):
        self.said.append((role, text))


class FakeBig:
    def __init__(self, lines):
        self.lines = list(lines)
        self.sent = []
        self.available = True

    def ask(self, prompt, label="task", system=""):
        self.sent.append((prompt, label, system))
        return self.lines.pop(0) if self.lines else None


@pytest.mark.parametrize("who,state,action", [("aria", "speaking", "listen"), ("claude", "listening", "talk")])
def test_silent_lines_still_choreograph_the_speaker_and_listener(aria, monkeypatch, who, state, action):
    a = aria
    a.voice = None
    a.ui = RecordingUI()
    states, commands = [], []
    a.ui.set_state = states.append
    a.ui.claude = lambda command, feeling="": commands.append(command)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    a._say_as(who, "That sounds interesting.", quiet=True)
    assert states == [state]
    assert commands[0] == action
    assert a.ui.said == [(who, "That sounds interesting.")]


@pytest.mark.parametrize("text", [
    "brainstorm with Claude about my birthday party", "you and Claude chat about cats",
    "let's talk with Claude", "bring Claude in, what should I cook", "du und Claude, redet über Musik"])
def test_a_duet_starts(text):
    assert Duet.wanted(text)


@pytest.mark.parametrize("text", ["ask Claude why the sky is blue", "what's the weather", "claude is cool"])
def test_other_messages_dont_start_one(text):
    assert not Duet.wanted(text)


def test_mode_and_topic():
    assert Duet.mode("brainstorm with Claude about my birthday party") == "ideas"
    assert Duet.mode("you and Claude chat about cats") == "fun"
    assert Duet.topic("you and Claude chat about cats!") == "cats"
    assert Duet.topic("let's talk with Claude") == "let's talk with Claude"


def test_stop_words():
    for t in ["stop", "ok that's enough", "thanks!", "genug"]:
        assert Duet.wants_stop(t), t
    assert not Duet.wants_stop("stop being so sure, I like the second idea")


def test_lines_are_cleaned_for_speaking():
    assert Duet.clean_line('Claude: **Pizza** party? Obviously.') == "Pizza party? Obviously."
    assert Duet.clean_line("One. Two. Three. Four.") == "One. Two. Three."
    assert Duet.clean_line("") is None


def _duet(aria, monkeypatch, claude, local, typed=()):
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    aria.ui = RecordingUI()
    aria.big = FakeBig(claude)
    aria.llm.chats = list(local)
    aria.text_inputs = queue.Queue()
    for t in typed:
        aria.text_inputs.put(t)
    aria._duet("brainstorm with Claude about my birthday party")
    return aria


def test_they_take_turns_and_aria_sums_up_ideas(aria, monkeypatch):
    a = _duet(aria, monkeypatch, ["A pirate party!", "Or a picnic.", "Karaoke, then."],
              ["Pirates, yes.", "Picnics have ants.", "Karaoke wins.", "Pirates or karaoke, your call."])
    roles = [r for r, _ in a.ui.said]
    assert roles == ["claude", "aria", "claude", "aria", "claude", "aria", "aria"]
    assert a.ui.said[-1] == ("aria", "Pirates or karaoke, your call.")
    assert a._recent[-1][0]["content"].startswith("(Claude and I just talked with you about my birthday party.)")


def test_claude_is_sent_only_this_conversation(aria, monkeypatch):
    aria.memory.save_message("user", "my secret mail from the bank")
    aria._recent.append([{"role": "user", "content": "SECRET HISTORY"}])
    a = _duet(aria, monkeypatch, ["A pirate party!", "Or a picnic.", "Karaoke."], ["Yes.", "Ants.", "Fine.", "Done."])
    prompt, label, system = a.big.sent[1]
    assert label == "duet" and system == Duet.CLAUDE_SYSTEM
    assert "SECRET" not in prompt and "bank" not in prompt
    assert "Claude: A pirate party!" in prompt and "Aria: Yes." in prompt


def test_lala_joins_and_can_stop_it(aria, monkeypatch):
    a = _duet(aria, monkeypatch, ["A pirate party!"], ["Yes."], typed=["stop"])
    assert a.ui.said == [("claude", "A pirate party!"), ("user", "stop"), ("aria", "Okay, back to just us.")]


def test_what_lala_says_goes_into_the_conversation(aria, monkeypatch):
    a = _duet(aria, monkeypatch, ["A pirate party!", "Pirates it is.", "Arr."], ["Yes.", "Ok.", "Ha.", "Sum."],
              typed=["I love pirates"])
    assert "Lala: I love pirates" in a.big.sent[1][0]


def test_when_claude_cant_be_reached_she_says_so(aria, monkeypatch):
    a = _duet(aria, monkeypatch, [], [])
    assert a.ui.said == [("aria", "Claude isn't answering right now, sorry.")]
    aria.big.available = False
    aria.ui.said.clear()
    aria._duet("let's talk with Claude")
    assert aria.ui.said == [("aria", "Claude can't join right now, I can't reach him.")]


# ── chats of their own ──

class ModelBig(FakeBig):
    def ask(self, prompt, label="task", system="", model=None, cancel=None):
        self.sent.append((prompt, label, model))
        return self.lines.pop(0) if self.lines else None


def _chat(aria, monkeypatch, claude, local, talked_ago=3600):
    import threading
    from Engines import Desk
    monkeypatch.setattr(Desk, "in_quiet_hours", lambda: False)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    aria.ui = RecordingUI()
    aria.big = ModelBig(claude)
    aria.llm.chats = list(local)
    aria.text_inputs = queue.Queue()
    aria._wake_event = threading.Event()
    aria.last_talked = main.time.time() - talked_ago
    return aria


def test_their_chats_come_at_random_times_on_light_topics():
    assert 30 * 60 <= Duet.next_chat_in(lambda: 0.0) < Duet.next_chat_in(lambda: 0.99) <= 120 * 60
    first = Duet.random_topic(lambda: 0.0)
    assert first in Duet.TOPICS and Duet.random_topic(lambda: 0.0, recent=[first]) != first


def test_they_chat_by_themselves_with_haiku_about_nothing_personal(aria, monkeypatch):
    a = _chat(aria, monkeypatch, ["Pineapple belongs on pizza.", "Fine, olives then."], ["Absolutely not.", "Deal."])
    assert a._chat_with_claude()
    assert [r for r, _ in a.ui.said] == ["claude", "aria", "claude", "aria"]
    assert all(model == "haiku" and label == "duet chat" for _, label, model in a.big.sent)
    assert "Lala:" not in a.big.sent[0][0]
    assert a._recent[-1][0]["content"].startswith("(Claude and I chatted about ")


def test_not_over_a_conversation_with_lala(aria, monkeypatch):
    a = _chat(aria, monkeypatch, ["Hi."], ["Hey."])
    a.awake = True
    assert not a._chat_with_claude() and a.big.sent == []
    a.awake = False
    a.text_inputs.put("hey aria")
    assert not a._chat_with_claude() and a.big.sent == []


def test_waking_her_ends_their_chat_at_once(aria, monkeypatch):
    a = _chat(aria, monkeypatch, ["Pineapple belongs on pizza.", "More."], ["No.", "More."])
    real_say = a._say_as

    def say_then_wake(who, text, quiet=False):
        real_say(who, text, quiet)
        a._wake_event.set()                     # Lala clicks her while Claude talks
    a._say_as = say_then_wake
    a._chat_with_claude()
    assert a.ui.said == [("claude", "Pineapple belongs on pizza.")]


def test_quiet_unless_lala_talked_to_her_lately(aria, monkeypatch):
    spoken = []
    a = _chat(aria, monkeypatch, ["Hi.", "Bye."], ["Hey.", "Bye."], talked_ago=3600)
    a.voice = type("V", (), {"speak": lambda self, text, speaker="aria": spoken.append(text)})()
    a._chat_with_claude()
    assert spoken == []
    a = _chat(aria, monkeypatch, ["Hi.", "Bye."], ["Hey.", "Bye."], talked_ago=60)
    a._chat_with_claude()
    assert spoken == ["Hi.", "Hey.", "Bye.", "Bye."]


def test_background_chats_respect_settings_and_quiet_hours(aria, monkeypatch):
    from Engines import Desk
    a = _chat(aria, monkeypatch, ["Hi."], ["Hello."])
    a.autonomous_chats = False
    assert not a._chat_with_claude()
    a.autonomous_chats = True
    monkeypatch.setattr(Desk, "in_quiet_hours", lambda: True)
    assert not a._chat_with_claude()
    assert a.big.sent == []


def test_background_call_receives_live_cancellation(aria, monkeypatch):
    a = _chat(aria, monkeypatch, [], [])
    def ask(*args, cancel=None, **kwargs):
        assert not cancel()
        a._wake_event.set()
        assert cancel()
        return None
    a.big.ask = ask
    assert not a._chat_with_claude()
    assert a.ui.said == []


def test_local_reply_finished_after_interruption_is_discarded(aria, monkeypatch):
    a = _chat(aria, monkeypatch, ["Hi."], [])
    def chat(*args, **kwargs):
        a._wake_event.set()
        return "A late reply."
    a.llm.chat = chat
    a._chat_with_claude()
    assert a.ui.said == [("claude", "Hi.")]
