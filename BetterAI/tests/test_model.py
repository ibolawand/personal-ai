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


class Stub:
    menu = None

    def __getattr__(self, name):
        return lambda *a, **k: "Done."


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
    aria.tools = ToolEngine(spotify=s, vision=s, reminders=aria.reminders, focus=s, screen=s, laptop=s,
                            files=FilesEngine(aria.confirm, roots=[str(tmp_path)]), notion=aria.notion,
                            initiative=s, memory_note=s, activity=s, weather=s, recall=s, health=s, posture=s, quiz=s)
    return aria


COMMANDS = [
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
]


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
