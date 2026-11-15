"""Looking at the screen: what gets photographed and what the picture model is told is decided in code."""
from PIL import Image

from Engines import ScreenEngine as se
from ui.desktop_windows import Shown, Win

LEFT, RIGHT = (0, 0, 1920, 1080), (1920, 0, 3840, 1080)


def win(left, top, right, bottom, title="notes.md - Code", app="com.microsoft.VSCode"):
    return Shown(Win(1, left, top, right, bottom), title, app)


def test_only_the_monitor_with_the_front_window_is_photographed():
    plan = se.plan_look([win(2000, 0, 3840, 1040)], [LEFT, RIGHT])
    assert plan == {"monitor": RIGHT, "close_up": None}                 # nearly fills it: one picture
    assert se.plan_look([win(100, 0, 1900, 1040)], [LEFT, RIGHT])["monitor"] == LEFT


def test_a_small_front_window_gets_a_close_up_kept_inside_its_monitor():
    plan = se.plan_look([win(1500, 200, 2300, 800), win(0, 0, 1920, 1040)], [LEFT, RIGHT])
    assert plan["monitor"] == LEFT and plan["close_up"] == (1500, 200, 1920, 800)
    assert se.plan_look([win(10, 10, 60, 40)], [LEFT])["close_up"] is None      # a sliver isn't worth a picture


def test_without_window_facts_she_still_looks():
    assert se.plan_look([], [LEFT]) == {"monitor": LEFT, "close_up": None}
    assert se.plan_look([], [LEFT, RIGHT]) == {"monitor": None, "close_up": None}
    assert se.plan_look([win(0, 0, 800, 600)], []) == {"monitor": None, "close_up": None}


def test_the_model_is_told_which_window_is_in_front_and_to_ignore_aria():
    windows = [win(0, 0, 800, 600, "Traceback - Terminal", "gnome-terminal-server"), win(0, 0, 1920, 1040, "YouTube", "firefox")]
    text = se.look_prompt("what's this error?", windows, se.plan_look(windows, [LEFT]))
    assert "what's this error?" in text
    assert 'in front, the one Lala is using, is "Traceback - Terminal" (gnome-terminal-server)' in text
    assert 'behind it: "YouTube" (firefox)' in text and "close-up" in text
    assert "Aria" in text and "too small to read" in text
    bare = se.look_prompt("what's on my screen?", [], se.plan_look([], [LEFT]))
    assert "in front" not in bare and "close-up" not in bare


def test_a_look_sends_the_monitor_and_the_close_up(monkeypatch):
    import llm_engine
    grabbed, sent = [], {}
    engine = se.ScreenEngine(clipboard=object())
    monkeypatch.setattr(engine, "_model_available", lambda: True)
    monkeypatch.setattr(engine, "_desktop", lambda: ([win(2100, 100, 2900, 700)], [LEFT, RIGHT]))
    monkeypatch.setattr(engine, "grab", lambda box=None: grabbed.append(box) or Image.new("RGB", (400, 300)))
    monkeypatch.setattr(llm_engine, "vision_chat",
                        lambda model, messages: sent.update(messages[0]) or {"message": {"content": " A terminal. "}})
    reply = engine.look_at_screen("what is this?")
    assert grabbed == [RIGHT, (2100, 100, 2900, 700)]
    assert len(sent["images"]) == 2 and "what is this?" in sent["content"]
    assert reply == llm_engine.FINAL_PREFIX + "A terminal."
