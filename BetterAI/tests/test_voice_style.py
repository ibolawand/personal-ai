"""How Aria says each sentence (Engines/VoiceStyle.py): emotion, sounds, pauses."""
import random

import pytest

from Engines import VoiceStyle as V
from Engines.voice_engine import style_voices


def test_delivery_profiles_slow_and_soften_without_changing_words():
    def piece(profile):
        return V.Delivery(rand=random.Random(42), profile=profile).pieces("Wow, amazing!")[0]
    natural, calm, clear = [piece(p) for p in ("natural", "calm", "clear")]
    assert natural.text == calm.text == clear.text
    assert clear.speed < calm.speed < natural.speed
    assert calm.gain < natural.gain and calm.lift < natural.lift
    assert clear.pause_after > natural.pause_after
    assert piece("unknown") == natural


def test_delivery_profile_can_be_selected_from_environment(monkeypatch):
    monkeypatch.setenv("ARIA_VOICE_PROFILE", "clear")
    assert V.Delivery().profile == "clear"


@pytest.mark.parametrize("sentence,feeling", [
    ("Aw, I'm sorry to hear that.", "sad"), ("That sounds rough.", "soft"), ("Take your time.", "soft"),
    ("I miss you too.", "sad"), ("You caught me!", "teasing"), ("Wow, rude.", "teasing"),
    ("No way, you passed!", "excited"), ("That's so cool.", "happy"), ("Done, milk's on the list!", "happy"),
    ("Hmm, maybe the blue one.", "thinking"), ("What's on your mind?", "curious"),
    ("The meeting is at three.", "neutral"), ("Finally done 😊", "happy"), ("Oh really 😏", "teasing"),
])
def test_each_sentence_gets_its_feeling(sentence, feeling):
    assert V.emotion(sentence) == feeling


def test_a_plain_sentence_takes_the_conversations_mood():
    assert V.emotion("The meeting is at three.", "sad") == "soft"
    assert V.emotion("The meeting is at three.", "excited") == "happy"
    assert V.emotion("That's so cool.", "sad") == "happy"             # its own words win


def test_laughs_are_said_as_a_laugh_not_spelled():
    assert V.laugh_words("that was haha so bad") == "that was Ha ha! so bad"
    assert V.laugh_words("hehe") == "Heh heh!"


def _pieces(sentence, raw=None, mood="neutral"):
    return V.Delivery(mood, rand=random.Random(1)).pieces(sentence, raw)


def test_a_leading_laugh_is_said_on_its_own_then_the_rest_with_its_own_feeling():
    laugh, rest = _pieces("Haha, you caught me!")
    assert (laugh.text, laugh.style) == ("Ha ha!", "laugh")
    assert (rest.text, rest.style) == ("You caught me!", "teasing")
    assert laugh.pause_after < 0.25                      # just a beat


def test_hmm_and_oh_lead_but_oh_no_stays_whole():
    hmm, rest = _pieces("Hmm, maybe the blue one.")
    assert (hmm.text, hmm.style, rest.text) == ("Hmmm...", "thinking", "Maybe the blue one.")
    oh, rest = _pieces("Oh! That's your exam?")
    assert (oh.text, rest.style) == ("Oh!", "curious")
    assert [p.text for p in _pieces("Oh no, that sounds rough.")] == ["Oh no, that sounds rough."]


def test_emojis_still_count_after_cleaning():
    (piece,) = _pieces("Oh really", raw="Oh really 😏")
    assert piece.style == "teasing"


def test_a_heartfelt_sentence_after_another_gets_a_breath_first():
    d = V.Delivery(rand=random.Random(1))
    first, = d.pieces("I read your message.")
    soft, = d.pieces("That sounds really hard.")
    assert first.pause_before == 0 and soft.pause_before > 0
    assert soft.speed < 1 and soft.gain < 1 and soft.lift < 0


def test_no_two_sentences_have_exactly_the_same_cadence():
    d = V.Delivery(rand=random.Random(3))
    speeds = {d.pieces("The meeting is at three.")[0].speed for _ in range(5)}
    assert len(speeds) > 1 and all(0.96 <= s <= 1.04 for s in speeds)


def test_happy_is_quicker_and_brighter_than_sad():
    happy, = _pieces("That's so cool.")
    sad, = _pieces("I miss you too.")
    assert happy.speed > sad.speed and happy.lift > sad.lift and happy.pause_after < sad.pause_after


def test_every_style_has_all_settings():
    for name, s in V.STYLES.items():
        assert set(s) == {"accent", "lift", "speed", "gain", "pause"}, name


def test_aria_defaults_to_expressive_delivery(monkeypatch):
    monkeypatch.delenv("ARIA_VOICE_PROFILE", raising=False)
    assert V.Delivery().profile == "expressive"


def test_thought_changes_get_distinct_delivery_without_losing_words():
    text = "I thought that was a pretty good plan, but honestly, your idea sounds more fun!"
    pieces = V.Delivery(profile="expressive", rand=random.Random(42)).pieces(text)
    assert len(pieces) == 2
    assert " ".join(p.text for p in pieces) == text
    assert pieces[0].style == "neutral" and pieces[1].style == "happy"
    assert pieces[0].pause_after < pieces[1].pause_after


@pytest.mark.parametrize("text", ["Done, milk's on the list.", "The total is 1,234.50 euros.",
                                 "We need apples, oranges, bananas, bread, butter, milk and eggs for breakfast."])
def test_expressive_delivery_does_not_chop_up_lists_or_short_answers(text):
    pieces = V.Delivery(profile="expressive").pieces(text)
    assert len(pieces) == 1 and pieces[0].text == text


def test_teasing_and_questions_linger_but_soft_speech_stays_conversational():
    def say(text):
        return V.Delivery(profile="expressive", rand=random.Random(42)).pieces(text)[0]
    assert say("You caught me.").speed < say("That's so cool.").speed
    assert say("What's your plan?").speed < 1
    soft = say("That sounds rough.")
    assert .93 < soft.speed < 1 and soft.gain < 1


def test_expressive_voice_preserves_base_identity():
    class Pipeline:
        def load_single_voice(self, name): return 0.0
    voices = style_voices(Pipeline(), 1.0, max_share=.22)
    assert voices and all(v >= .78 for v in voices.values())
