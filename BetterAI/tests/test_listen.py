"""The microphone only opens when Lala types that Aria should listen, and closes when she sleeps."""
import threading
import types

import pytest

import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)


@pytest.fixture
def typing_aria(aria):
    aria.option = 1
    aria._ears = False
    aria._wake_event = threading.Event()
    return aria


@pytest.mark.parametrize("text", ["listen", "Listen!", "listen to me", "aria, listen please", "start listening",
                                  "voice on", "mic on", "turn on the microphone", "hör zu", "Hör mir zu."])
def test_typing_listen_opens_the_microphone(typing_aria, text):
    reply, used = typing_aria._handle_turn(text)
    assert reply == "I'm listening." and used == [("listen", reply)]
    assert typing_aria._ears and typing_aria._uses_mic()
    assert typing_aria._wake_event.is_set()             # from MyNotion's panel she has to wake up to hear


@pytest.mark.parametrize("text", ["listen to this song", "can you listen to my idea later", "play voice on Spotify",
                                  "what does hör zu mean"])
def test_listen_inside_a_sentence_is_an_ordinary_message(typing_aria, text):
    typing_aria._handle_turn(text)
    assert not typing_aria._ears and not typing_aria._uses_mic()


@pytest.mark.parametrize("text", ["stop listening", "voice off", "mic off", "turn off the mic", "hör auf zuzuhören"])
def test_stop_listening_closes_it_at_once(typing_aria, text):
    typing_aria._ears = True
    reply, used = typing_aria._handle_turn(text)
    assert reply == "Okay, the microphone is off." and used == [("listen", reply)]
    assert not typing_aria._ears


def test_stop_listening_when_it_is_off_already(typing_aria):
    assert typing_aria._handle_turn("stop listening")[0] == "The microphone is already off."


def test_going_to_sleep_closes_the_microphone(typing_aria):
    typing_aria._ears = True
    typing_aria._sleep_request = threading.Event()
    typing_aria._remember_session = lambda: None
    typing_aria._go_to_sleep()
    assert not typing_aria._ears and not typing_aria._uses_mic()


def test_the_phone_can_never_open_the_microphone(typing_aria):
    typing_aria.tools._phone = True
    typing_aria._handle_turn("listen")
    assert not typing_aria._ears


def test_voice_mode_always_uses_the_microphone_and_ignores_the_phrases(typing_aria):
    typing_aria.option = 2
    assert typing_aria._uses_mic()
    reply, _ = typing_aria._handle_turn("stop listening")
    assert reply != "Okay, the microphone is off." and typing_aria._uses_mic()


def test_a_running_quiz_takes_listen_as_an_answer(typing_aria):
    typing_aria.quiz = types.SimpleNamespace(active=True, answer=lambda text: "Not quite, it's a join.")
    assert typing_aria._handle_turn("listen")[0] == "Not quite, it's a join."
    assert not typing_aria._ears


def test_while_dictating_the_words_are_not_a_command(typing_aria):
    typing_aria._ears = True
    typing_aria.dictation = types.SimpleNamespace(active=True)
    assert typing_aria._ears_command("stop listening") is None and typing_aria._ears
