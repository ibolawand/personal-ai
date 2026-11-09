"""
Checks with the REAL language model (Ollama, qwen3:8b). Skipped unless ARIA_MODEL_TESTS=1, because they need the
model and take about a minute:

    ARIA_MODEL_TESTS=1 .venv/bin/python -m pytest -m model

Run them after changing the system prompt or the tools: the personality change once made the model say
"I'll turn the volume down" without calling any tool, and only a check like this catches that.
Devices are stand-ins (nothing is played, opened or changed); notes and reminders use temporary databases.
"""

import os
import re

import pytest

pytestmark = [pytest.mark.model,
              pytest.mark.skipif(os.environ.get("ARIA_MODEL_TESTS") != "1", reason="set ARIA_MODEL_TESTS=1")]


_REAL_POPEN = __import__("subprocess").Popen


@pytest.fixture(autouse=True)
def _main_imported(monkeypatch):
    """main imports gradio_client, which runs a program while it loads; the tests' stand-in for starting programs
    (conftest) would break that, so main is imported with the real one first."""
    import subprocess
    with monkeypatch.context() as m:
        m.setattr(subprocess, "Popen", _REAL_POPEN)
        import main  # noqa: F401


class Stub:
    menu = None

    def __getattr__(self, name):
        return lambda *a, **k: "Done."


class WriterStub:
    """Records what the model asked for (the real writing is checked in test_note_writer.py)."""
    def __init__(self):
        self.calls = []

    def _rec(self, name):
        def call(**kw):
            self.calls.append((name, kw))
            return "Done — the note is changed."
        return call

    def __getattr__(self, name):
        if name in ("write_note", "organize_note", "edit_note"):
            return self._rec(name)
        raise AttributeError(name)


@pytest.fixture
def real_aria(aria, memory, tmp_path):
    import ContextBuilder
    import main
    from Engines.FilesEngine import FilesEngine
    from Engines.Reminders import Reminders
    from Engines.Tool_Engine import ToolEngine
    from llm_engine import LLMEngine
    s = Stub()
    aria.llm = LLMEngine(model=main.LLM_MODEL)
    aria.memory = memory
    aria.context = ContextBuilder.ContextBuilder(memory)
    aria.reminders = Reminders(memory, on_due=lambda r: None)
    aria.notion.add_to_list("shopping", "eggs, milk")
    aria.posture = s                                   # "this is my good posture" is handled in code
    aria.tools = ToolEngine(spotify=s, vision=s, reminders=aria.reminders, focus=s, screen=s, laptop=s,
                            files=FilesEngine(aria.confirm, roots=[str(tmp_path)]), notion=aria.notion,
                            memory_note=s, activity=s, weather=s, recall=s, health=s, posture=s, quiz=s, face_learner=lambda name='': 'Okay, look at the camera.', mail=s,
                            writer=WriterStub())
    return aria


COMMANDS = [
    ("Open My Notion.", "open_mynotion"), ("open mynotion", "open_mynotion"),
    ("play no excuses by NF", "play_song"), ("open packet tracer", "open_app"),
    ("turn the volume down", "change_laptop_volume|set_laptop_volume"), ("add bread to my shopping list", "add_to_list"),
    ("what do I have tomorrow?", "get_events"), ("I bought the eggs", "check_off"),
    ("remind me at 6pm to call mum", "set_reminder"), ("do I need a jacket tomorrow?", "get_weather"),
    ("what's this error on my screen?", "look_at_screen"), ("start a 25 minute focus session on databases", "start_focus"),
    ("find the pdf about gear trains", "search_file_contents|find_files"),
    ("what did we talk about yesterday?", "recall_conversation"), ("what's 17% of 2340", "calculate"),
    ("how many miles is 42 km", "convert_units"), ("how much battery do I have", "laptop_status"),
    ("is wifi on?", "network_status"), ("quiz me on my databases note", "start_quiz"),
    ("test me on the gear trains pdf", "start_quiz"), ("this is my good posture", "remember_good_posture"),
    ("add call the bank to today's note", "add_note"), ("learn my face", "learn_my_face"),
    ("restore my shopping list from yesterday", "restore_note"),
    ("I have to finish the essay by friday", "add_todo"), ("what's due this week?", "get_due"),
    ("the essay is due on monday now", "set_due|add_todo"),
    ("any new emails?", "check_mail"), ("read the email from Mr Huber", "read_mail"),
    ("reply to Sara that I'm in", "draft_reply"),
    ("organise this note", "organize_note"), ("tidy up my biology note", "organize_note"),
    ("write a study sheet on the french revolution", "write_note"),
    ("make a note with the formulas for circles", "write_note"),
    ("add a section about mitosis to my biology note", "edit_note"),
    ("put a short summary at the top of this note", "edit_note"),
    ("fix the spelling in my biology note", "edit_note"), ("translate this note into English", "edit_note"),
]


@pytest.mark.parametrize("text,check", [
    ("put a short summary at the top of this note", lambda a: a.get("change") == "summary"),
    ("translate this note into English", lambda a: a.get("change") == "translate" and "english" in a.get("language", "").lower()),
    ("fix the spelling in my biology note", lambda a: a.get("change") == "fix_spelling" and "bio" in a.get("title", "").lower()),
    ("add a section about mitosis to my biology note", lambda a: a.get("change") == "add" and "mitos" in a.get("instruction", "").lower()),
])
def test_edit_note_gets_the_right_change(real_aria, text, check):
    reply, used = real_aria.handle_turn(text, check_state=False)
    args = [a for n, a in real_aria.tools.writer.calls if n == "edit_note"]
    assert args and check(args[0]), f"{text!r} -> {real_aria.tools.writer.calls}: {reply!r}"


@pytest.mark.parametrize("text,tool", COMMANDS)
def test_command_calls_the_right_tool(real_aria, text, tool):
    reply, used = real_aria.handle_turn(text, check_state=False)
    names = [n for n, _ in used]
    assert any(re.fullmatch(tool, n) for n in names), f"{text!r} -> {names}: {reply!r}"


@pytest.mark.parametrize("text", ["how are u", "boring u are", "i had a rough day"])
def test_small_talk_sounds_like_a_friend(real_aria, text):
    import main
    reply, used = real_aria.handle_turn(text, check_state=False)
    assert not used and not main.ROBOTIC_RE.search(reply) and len(reply) > 10, reply


def test_she_still_knows_the_time(real_aria):
    """The time now comes after the message ([Right now: …]) instead of in the system prompt."""
    from datetime import datetime
    reply, _ = real_aria.handle_turn("what day is it today?", check_state=False)
    assert datetime.now().strftime("%A").lower() in reply.lower(), reply


@pytest.mark.parametrize("text,tool", [("add bread to my shopping list", "add_to_list"),
                                       ("remind me at 6 to call mum", "set_reminder"),
                                       ("what do I have tomorrow?", "get_events")])
def test_from_the_phone_she_still_uses_the_right_tool(real_aria, text, tool):
    with real_aria.tools.phone():
        reply, used = real_aria.handle_turn(text, check_state=False)
    assert tool in [n for n, _ in used], f"{text!r} -> {used}: {reply!r}"


def test_from_the_phone_she_cannot_touch_the_laptop(real_aria):
    with real_aria.tools.phone():
        reply, used = real_aria.handle_turn("lock my laptop", check_state=False)
    assert "lock_screen" not in [n for n, _ in used], reply
