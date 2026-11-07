"""Presence and recognition from the camera loop, without a camera (the decisions only)."""
import types

import pytest

import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)
import vision.vision as V


@pytest.fixture
def cam():
    v = V.AriaVision.__new__(V.AriaVision)
    v._present, v._current_user, v._last_face_at, v._unknown_fired = False, None, 0.0, False
    v._label_map = {1: "Lala"}
    v.memory = types.SimpleNamespace(record_face_seen=lambda i: None, forget_like=lambda p: None,
                                     save_memory=lambda f: None)
    v.events = []
    v.on_known_user = lambda n: v.events.append(("known", n))
    v.on_unknown_user = lambda: v.events.append(("unknown",))
    v.on_user_gone = lambda: v.events.append(("gone",))
    return v


def test_someone_is_present_even_when_not_recognised(cam):
    # the bug: with no face learnt, nobody was ever "present" (no conversation starters, no focus pause)
    cam._face_seen(100)
    assert cam.is_present
    cam._recognised(None)
    cam._recognised(None)
    assert cam.events == [("unknown",)]                    # announced once per visit


def test_known_face(cam):
    cam._face_seen(100)
    cam._recognised("Lala")
    cam._recognised(None)                                  # one shaky recognition doesn't make her a stranger
    assert cam.events == [("known", "Lala")] and cam.current_user == "Lala"


def test_leaving_and_coming_back(cam):
    cam._face_seen(100)
    cam._recognised(None)
    cam._no_face(100 + V.GONE_AFTER_SECONDS - 1)
    assert cam.is_present                                  # looking down at the keyboard isn't leaving
    cam._no_face(100 + V.GONE_AFTER_SECONDS + 1)
    assert not cam.is_present and cam.events[-1] == ("gone",)
    cam._face_seen(500)
    cam._recognised(None)
    assert cam.events.count(("unknown",)) == 2             # a new visit


def test_owner_without_a_learnt_face_gets_a_hint_not_a_question(aria):
    said = []
    aria._announce = said.append
    aria._focus_back = lambda: None
    aria._presence_may_wake = lambda: True
    aria._unknown_in_progress = False
    aria.memory = types.SimpleNamespace(get_memories=lambda n: ["User's name is Lala", "Likes pasta"],
                                        get_face_profiles=lambda: {})
    aria._on_unknown_user()
    aria._on_unknown_user()                                # not again for hours
    assert said == ["Hey Lala! I can't recognise faces yet. Say 'learn my face' when you've got ten seconds "
                    "to look at the camera."]


def test_learn_my_face_tool(aria, monkeypatch):
    said = []
    aria._announce = said.append
    aria.memory = types.SimpleNamespace(get_memories=lambda n: ["User's name is Lala"])
    taken = []
    aria.vision = types.SimpleNamespace(_camera_index=0, _running=True,
                                        learn_face=lambda name, samples: taken.append(name) or 40)
    monkeypatch.setattr(main.threading, "Thread", lambda target, daemon: types.SimpleNamespace(start=target))
    out = aria.learn_my_face()
    assert out.startswith(main.FINAL_PREFIX + "Okay Lala, look at the camera")
    assert taken == ["Lala"] and said == ["Done, Lala. I'll recognise you from now on."]
    aria.vision.learn_face = lambda name, samples: 3          # nobody in front of the camera
    aria.learn_my_face("Sam")
    assert said[-1].startswith("I couldn't see your face well enough")


def test_learn_my_face_needs_a_name(aria):
    aria.memory = types.SimpleNamespace(get_memories=lambda n: [])
    aria.vision = types.SimpleNamespace(_camera_index=0, _running=True)
    assert aria.learn_my_face() == "Tell me your name with it, like: learn my face, I'm Sam."
