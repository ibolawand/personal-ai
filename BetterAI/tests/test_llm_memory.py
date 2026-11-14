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
    assert aria.llm.prompts[-1].startswith("hey") and aria.llm.prompts[-1].endswith("[Right now: It is evening on Saturday, 19:42.]")
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
