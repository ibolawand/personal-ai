import types

import pytest

import main  # noqa: F401  (imported before the fixtures stub out subprocess)

from Engines.Confirm import Confirmer
from Engines.Dictation import Dictation, light_tidy
from Engines.NotionEngine import daily_title, html_to_text


@pytest.mark.parametrize("text, title", [
    ("dictate into my trip note", "trip"),
    ("Aria, start dictating into the Lisbon ideas note.", "Lisbon ideas"),
    ("can you take dictation", ""),
    ("let's dictate something for today's note", ""),
    ("dictate", ""),
    ("write down what I say", ""),
])
def test_wants_to_start(text, title):
    assert Dictation.wants_to_start(text) == title


@pytest.mark.parametrize("text", ["what's dictation", "the dictator was awful", "write me a poem about dictation"])
def test_other_messages_dont_start_it(text):
    assert Dictation.wants_to_start(text) is None


def make(cleanup=lambda paras: paras, confirm=None):
    saved, cards = [], []
    d = Dictation(lambda text, title: saved.append((text, title)) or "ok", confirm=confirm,
                  on_card=cards.append, cleanup=cleanup)
    return d, saved, cards


def test_quiet_while_dictating_and_saves_on_stop():
    d, saved, cards = make()
    d.start("trip")
    assert d.feed("we could go to lisbon in spring") == ""
    assert d.feed("new paragraph") == ""
    assert d.feed("and porto for two days") == ""
    assert cards[-1]["type"] == "dictation" and cards[-1]["words"] == 12
    assert d.feed("stop dictating") == "Saved 12 words to your trip note."
    assert saved == [("we could go to lisbon in spring.\nand porto for two days.", "trip")]
    assert d.active is None and cards[-1] == {"type": "clear", "kind": "dictation"}


def test_new_paragraph_inside_a_sentence_and_scratch_that():
    d, saved, _ = make()
    d.start("")
    d.feed("first idea new paragraph second idea")
    d.feed("this was a mistake")
    assert d.feed("scratch that") == "Took out: this was a mistake"
    assert d.text_so_far() == "first idea\n\nsecond idea"
    d.feed("done")
    assert saved == [("first idea.\nsecond idea.", "")]


def test_read_back():
    d, _, _ = make()
    d.start("")
    assert d.feed("read it back") == "Nothing yet. Go ahead."
    d.feed("um buy a new lamp")
    assert d.feed("what do I have so far") == "So far: Buy a new lamp."


def test_cleanup_that_rewrites_too_much_is_not_used():
    d, saved, _ = make(cleanup=lambda paras: ["Summary: trip."])
    d.start("")
    d.feed("so um I think we should go to lisbon in the spring because it's warm")
    d.feed("stop")
    assert saved[0][0] == "So I think we should go to lisbon in the spring because it's warm."


def test_cleanup_is_used_when_it_only_tidies():
    d, saved, _ = make(cleanup=lambda paras: ["I think we should go to Lisbon in the spring."])
    d.start("")
    d.feed("i think um we should go to lisbon in the spring")
    d.feed("that's it")
    assert saved[0][0] == "I think we should go to Lisbon in the spring."


def test_cancel_asks_first():
    confirm = Confirmer()
    d, saved, _ = make(confirm=confirm)
    d.start("")
    d.feed("a few words here")
    assert "throw away the 4 words" in d.feed("cancel dictation")
    assert confirm.resolve("yes") == "Okay, threw it away."
    assert d.active is None and saved == []


def test_light_tidy():
    assert light_tidy("um the the plan is uh simple. we go") == "The plan is simple. We go."


def test_handle_turn_writes_into_todays_note(aria, notion):
    aria.tools = types.SimpleNamespace(schemas=[], execute=lambda name, args: getattr(notion, name)(**args))
    aria.dictation = Dictation(aria._save_dictation, confirm=aria.confirm, cleanup=lambda p: p)
    reply, used = aria.handle_turn("dictate", check_state=False)
    assert "today's note" in reply and used[0][0] == "start_dictation"
    assert aria.handle_turn("call the bank about the card", check_state=False)[0] == ""
    assert aria.llm.prompts == []                                  # the model never saw it
    reply, _ = aria.handle_turn("stop", check_state=False)
    assert reply == "Saved 6 words to today's note."
    note = next(n for n in notion._notes() if n["title"] == daily_title())
    assert "call the bank about the card" in html_to_text(note["content"])


def test_falling_asleep_saves_what_was_dictated(aria, notion):
    aria.tools = types.SimpleNamespace(schemas=[], execute=lambda name, args: getattr(notion, name)(**args))
    aria.dictation = Dictation(aria._save_dictation, confirm=aria.confirm, cleanup=lambda p: p)
    aria._initiative_active = None
    aria._sleep_request = __import__("threading").Event()
    aria._remember_session = lambda *a, **k: None
    aria.handle_turn("dictate into my ideas note", check_state=False)
    aria.handle_turn("a lamp that follows the sun", check_state=False)
    aria._go_to_sleep()
    assert "a lamp that follows the sun" in html_to_text(notion._find_note("ideas")["content"])
