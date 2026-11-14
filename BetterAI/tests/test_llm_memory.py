"""The chat model must sit fully on the graphics card: squeezed partly onto the CPU it wrote 31 instead of 46 tokens/s.
That happened when it was loaded back while the picture model (screen, camera) was still in memory."""
import types

import llm_engine as L


def fake_ollama(monkeypatch, ps_models=()):
    calls = []
    fake = types.SimpleNamespace(
        chat=lambda **k: calls.append(("chat", k.get("model"), k.get("keep_alive"))) or {"message": {"content": "a desk"}},
        generate=lambda **k: calls.append(("generate", k.get("model"), k.get("keep_alive"))),
        ps=lambda: types.SimpleNamespace(models=list(ps_models)))
    monkeypatch.setattr(L, "ollama", fake)
    monkeypatch.setattr(L, "_in_background", lambda fn: fn())
    return calls


def test_picture_model_leaves_the_card_before_the_chat_model_comes_back(monkeypatch):
    calls = fake_ollama(monkeypatch)
    out = L.vision_chat("qwen2.5vl:3b", [{"role": "user", "content": "what is this", "images": ["x"]}])
    assert out["message"]["content"] == "a desk"
    assert calls == [("chat", "qwen2.5vl:3b", 0), ("generate", L.LLM_MODEL_DEFAULT, L.KEEP_ALIVE)]


# ── the same prompt start every turn ──
# Ollama reuses what it already read when a request starts like the last one: measured, the first word then comes
# after 0.1 s instead of 1.3 s. The clock time near the top of the system prompt made every turn start differently.

def test_system_prompt_has_no_clock(memory):
    import re
    from ContextBuilder import ContextBuilder
    cb = ContextBuilder(memory)
    stable = cb.build_system_prompt("BASE", moment=False)
    assert not re.search(r"\d{1,2}:\d{2}", stable) and cb._time_apart_str(memory.get_last_seen()) not in stable
    assert re.search(r"\d{1,2}:\d{2}", cb.moment())
    assert "BASE" in cb.build_system_prompt("BASE") and re.search(r"\d{1,2}:\d{2}", cb.build_system_prompt("BASE"))


def test_the_moment_goes_after_the_message(aria):
    aria.context.moment = lambda: "It is evening on Saturday, 19:42."
    aria.handle_turn("hey", check_state=False)
    assert aria.llm.prompts[-1].startswith("hey")
    # marked as background: the bigger model otherwise answered a command with "I'm glowing on your desk, how was
    # your day?" ("…the very first time you're meeting")
    assert aria.llm.prompts[-1].endswith("[Right now (background, only mention it if it matters): "
                                         "It is evening on Saturday, 19:42.]")
    assert "19:42" not in aria.llm.systems[-1]


def test_tools_always_start_in_the_same_order():
    from tests.test_routing import Any
    from Engines.Tool_Engine import ToolEngine
    a = Any()
    t = ToolEngine(spotify=a, arduino=a, vision=a, ha=a, reminders=a, focus=a, screen=a, laptop=a, files=a, notion=a,
                   memory_note=a, activity=a, weather=a, undo=a, recall=a, health=a, posture=a, quiz=a,
                   face_learner=lambda name='': 'ok', mail=a)
    order = lambda text: [s["function"]["name"] for s in t.schemas_for(text)]
    small, music, mail = order("how are you"), order("play no excuses by NF"), order("any new emails?")
    assert music[:len(small)] == small and mail[:len(small)] == small


# ── which model is her brain: one setting (Engines/.env ARIA_MODEL) ──

def test_model_comes_from_aria_model(monkeypatch):
    import importlib
    try:
        monkeypatch.setenv("ARIA_MODEL", "qwen3:8b")
        assert importlib.reload(L).LLM_MODEL_DEFAULT == "qwen3:8b"
        monkeypatch.delenv("ARIA_MODEL")
        assert importlib.reload(L).LLM_MODEL_DEFAULT == "qwen3:30b-a3b-instruct-2507-q4_K_M"
    finally:
        importlib.reload(L)


def test_engine_defaults_to_the_configured_model():
    assert L.LLMEngine().model == L.LLM_MODEL_DEFAULT



# ── follow-through: after a tool, "I'll open it for you now" means it isn't done yet ──

def _scripted(monkeypatch, replies):
    """The model answers from `replies` in order: a str is a text reply, a (name, args) tuple a tool call."""
    seen = []

    def chat(**k):
        seen.append(list(k["messages"]))           # a snapshot: the list grows afterwards
        r = replies[len(seen) - 1]
        calls = [types.SimpleNamespace(function=types.SimpleNamespace(name=r[0], arguments=r[1]))] if isinstance(r, tuple) else None
        return types.SimpleNamespace(message=types.SimpleNamespace(content="" if calls else r, tool_calls=calls))
    monkeypatch.setattr(L, "ollama", types.SimpleNamespace(chat=chat))
    return seen


def test_an_announced_next_step_after_a_tool_is_carried_out(monkeypatch):
    seen = _scripted(monkeypatch, [("find_app", {"app": "packet tracer"}),
                                   "Packet Tracer is installed! I'll open it for you now.",
                                   ("open_app", {"app": "packet tracer"}), "Opened Packet Tracer."])
    reply, used = L.LLMEngine(model="m").chat_with_tools("open packet tracer", [], "sys", [{"function": {"name": "x"}}],
                                                         lambda name, args: "Done.")
    assert [n for n, _ in used] == ["find_app", "open_app"] and reply == "Opened Packet Tracer."
    assert "Do it now" in seen[2][-1]["content"]


def test_a_finished_reply_after_a_tool_is_not_pushed(monkeypatch):
    seen = _scripted(monkeypatch, [("check_off", {"items": "eggs"}), "Ticked off the eggs."])
    reply, used = L.LLMEngine(model="m").chat_with_tools("I bought the eggs", [], "sys", [{"function": {"name": "x"}}],
                                                         lambda name, args: "Ticked off eggs.")
    assert reply == "Ticked off the eggs." and len(seen) == 2


def test_she_is_pushed_only_once(monkeypatch):
    seen = _scripted(monkeypatch, [("find_app", {"app": "x"}), "I'll open it now.", "I'll open it right away!"])
    reply, used = L.LLMEngine(model="m").chat_with_tools("open x", [], "sys", [{"function": {"name": "x"}}],
                                                         lambda name, args: "Done.")
    assert reply == "I'll open it right away!" and len(seen) == 3


def test_a_question_after_a_tool_is_never_pushed(monkeypatch):
    """Pushed, the model acted on its own guess: it reorganised the shopping list instead of asking which note."""
    seen = _scripted(monkeypatch, [("read_note", {"title": "this"}),
                                   "Let me check: do you want me to organise your shopping list, or another note?"])
    reply, used = L.LLMEngine(model="m").chat_with_tools("organise this note", [], "sys", [{"function": {"name": "x"}}],
                                                         lambda name, args: "Your notes: Shopping list.")
    assert reply.endswith("another note?") and len(seen) == 2


def test_a_tool_call_written_into_the_text_is_carried_out(monkeypatch):
    """The 30 B model sometimes writes the call as text ("<tool_call>{json}</tool_call>") instead of making it:
    shown as is, Lala saw raw JSON in her bubble."""
    seen = _scripted(monkeypatch, ['Let me try again.\n\n<tool_call>\n{"name": "start_quiz", "arguments": '
                                   '{"topic": "gear trains"}}\n</tool_call>', "Here's your first question."])
    done = []
    reply, used = L.LLMEngine(model="m").chat_with_tools("test me on the gear trains pdf", [], "sys",
                                                         [{"function": {"name": "start_quiz"}}],
                                                         lambda name, args: done.append((name, args)) or "Quiz started.")
    assert done == [("start_quiz", {"topic": "gear trains"})]
    assert reply == "Here's your first question." and "<tool_call>" not in reply


def test_the_open_note_is_named_so_this_note_means_it(aria, monkeypatch):
    """'translate this note': the bigger model guessed a title ('Saturday notes'); now it's told which note is open."""
    import Engines.NotionEngine as NE
    bio = aria.notion._create_note("Biology", "<p>Mitosis has four phases.</p>")
    aria.notion._set_state("open_note", str(bio))
    monkeypatch.setattr(NE, "mynotion_running", lambda: True)
    aria.handle_turn("translate this note into English", check_state=False)
    assert "[Open in MyNotion: 'Biology'" in aria.llm.prompts[-1]


def test_no_open_note_no_hint(aria, monkeypatch):
    import Engines.NotionEngine as NE
    monkeypatch.setattr(NE, "mynotion_running", lambda: False)
    aria.handle_turn("translate this note into English", check_state=False)
    assert "Open in MyNotion" not in aria.llm.prompts[-1]


def test_more_rounds_for_a_model_that_checks_first(monkeypatch):
    seen = _scripted(monkeypatch, [("find_files", {"query": "gear"}), ("read_file", {"which": "1"}),
                                   ("search_notes", {"q": "gear"}), ("start_quiz", {"topic": "gear trains"}),
                                   "First question: what is a gear ratio?"])
    reply, used = L.LLMEngine(model="m").chat_with_tools("test me on the gear trains pdf", [], "sys",
                                                         [{"function": {"name": "x"}}], lambda name, args: "ok")
    assert [n for n, _ in used][-1] == "start_quiz" and reply.startswith("First question")


def test_out_of_rounds_a_written_call_is_never_the_reply(monkeypatch):
    seen = _scripted(monkeypatch, [("a", {})] * 5 + ['<tool_call>\n{"name": "read_file", "arguments": {}}\n</tool_call>'])
    reply, used = L.LLMEngine(model="m").chat_with_tools("x", [], "sys", [{"function": {"name": "x"}}],
                                                         lambda name, args: "ok")
    assert "<tool_call>" not in reply and reply


def test_the_open_note_is_only_named_when_the_message_is_about_a_note(aria, monkeypatch):
    """Named on every turn, the bigger model talked about it every turn ("That Biology note's still open…")."""
    import Engines.NotionEngine as NE
    bio = aria.notion._create_note("Biology", "<p>Mitosis has four phases.</p>")
    aria.notion._set_state("open_note", str(bio))
    monkeypatch.setattr(NE, "mynotion_running", lambda: True)
    for text in ("just chilling with you", "are you with me", "play something"):
        aria.handle_turn(text, check_state=False)
        assert "Open in MyNotion" not in aria.llm.prompts[-1], text
    for text in ("organise this note", "mach aus den Tab-Spalten eine Tabelle", "is my solution for 4.15 right?",
                 "fix the spelling", "quiz me on this"):
        aria.handle_turn(text, check_state=False)
        assert "[Open in MyNotion: 'Biology'" in aria.llm.prompts[-1], text
