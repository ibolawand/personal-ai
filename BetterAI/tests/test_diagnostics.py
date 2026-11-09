"""The speed and problem log (Engines/Diagnostics.py) and where Aria writes to it."""
import json
import time

import pytest

import main
from Engines import Diagnostics as D


@pytest.fixture
def log(monkeypatch, tmp_path):
    path = tmp_path / "diagnostics.jsonl"
    monkeypatch.setattr(D, "LOG_FILE", str(path))
    return path


def entries(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_timing_adds_up_from_when_you_stop_talking(log):
    D.timing(silence_wait=1.2, transcribe=0.2, first_sentence=0.6, first_audio=0.9, tools=["get_weather"])
    e = entries(log)[0]
    assert e["type"] == "timing" and e["starts_after"] == 2.3 and e["tools"] == ["get_weather"]


def test_report(log):
    for s in (2.0, 2.2, 6.5):
        D.timing(silence_wait=1.2, transcribe=0.2, first_sentence=0.4, first_audio=s - 1.4)
    D.problem("misheard", "turn of the lights (0.31)")
    D.problem("misheard", "play no excuse (0.40)")
    D.problem("woke_for_nothing")
    out = D.report(7)
    assert "3 spoken replies, 3 problems" in out
    assert "her voice starts   2.2 s typical, 6.5 s slow" in out
    assert "2× unsure what you said" in out and "1× woke up but nobody said anything" in out
    assert "misheard: play no excuse (0.40)" in out


def test_old_entries_are_left_out(log):
    log.write_text(json.dumps({"at": time.time() - 30 * 86400, "type": "problem", "kind": "crash"}) + "\n")
    assert "0 problems" in D.report(7)


def test_empty_report(log):
    assert D.report(7).startswith("Aria, the last 7 days: 0 spoken replies, 0 problems.")


@pytest.mark.parametrize("text,hit", [("no, I said turn it up", True), ("that's not what I said", True),
                                      ("you misheard me", True), ("no not that one", True), ("wrong", True),
                                      ("no thanks", False), ("I said hi to mum today", True),
                                      ("what's wrong with my code", False), ("nope", False)])
def test_corrections(text, hit):
    assert bool(main.CORRECTION_RE.search(text)) is hit


def test_claimed_action_is_logged(aria, log):
    aria.llm.replies = [("I'll turn it down for you.", []), ("", [("change_laptop_volume", "Volume 40%")])]
    aria.handle_turn("turn the volume down", check_state=False)
    assert [e["kind"] for e in entries(log)] == ["claimed_no_tool"]


def test_misheard_is_logged(aria, log):
    aria.speak = lambda text: None
    assert aria._check_heard("turn of the lights", 0.2) is None
    assert entries(log)[0]["kind"] == "misheard"


def test_a_failing_tool_is_logged(log):
    from Engines.Tool_Engine import ToolEngine
    tools = ToolEngine.__new__(ToolEngine)
    tools.owner_check = lambda: True
    tools._registry = {"boom": {"handler": lambda: 1 / 0, "schema": {"function": {"name": "boom"}}}}
    tools.PROTECTED = set()
    assert "boom failed" in tools.execute("boom", {})
    assert entries(log)[0]["kind"] == "tool_error"


def test_every_chat_model_call_keeps_the_model_loaded():
    """A call without the same num_ctx reloads the model (~3 s); one without keep_alive lets it unload."""
    import pathlib
    import re
    root = pathlib.Path(main.__file__).parent
    for f in ["llm_engine.py", "Engines/Quiz.py", "Engines/UserStateEngine.py"]:
        src = (root / f).read_text()
        for call in re.findall(r"ollama\.chat\((.*?)\)(?:\.message|\n|:)", src, re.S):
            if "VISION_MODEL" in call or "keep_alive=0" in call:
                continue                    # the picture model (vision_chat) leaves memory right after answering
            assert "keep_alive=KEEP_ALIVE" in call and "options=" in call, f"{f}: {call[:120]}"


def test_whisper_falls_back_to_the_cpu(monkeypatch):
    import speech_to_text as S
    made = []

    def fake_model(size, device, compute_type):
        if device == "cuda":
            raise RuntimeError("Library libcublas.so.12 is not found")
        made.append((device, compute_type))
        return object()
    monkeypatch.setattr(S, "WhisperModel", fake_model)
    model, device = S.STTEngine._load("medium", "auto")
    assert device == "cpu" and made == [("cpu", "int8")]


@pytest.mark.parametrize("heard,ok", [("Hey Aria.", True), ("Hey, Arya!", True), ("hey area", True),
                                      ("Aria, what's the time?", True), ("in the area", False),
                                      ("Hey Maria, how are you", False), ("Thanks for watching!", False),
                                      ("Hey Aaron", False), ("Hey Jarvis", False), ("", False)])
def test_wake_confirmation(heard, ok):
    assert bool(main.WAKE_HEARD_RE.search(heard)) is ok


def test_wake_detector_asks_whisper(monkeypatch):
    import types
    import wakeworddetector as W
    d = W.WakeWordDetector.__new__(W.WakeWordDetector)
    d._recent = __import__("collections").deque([b"\x00\x00" * 1280] * 3)
    d.verify = lambda audio: (False, "Hey Maria")
    logged = []
    monkeypatch.setattr(D, "problem", lambda kind, detail="": logged.append((kind, detail)))
    assert d._confirmed(0.8) is False and logged == [("wake_unconfirmed", "0.80: Hey Maria")]
    d.verify = lambda audio: (True, "Hey Aria")
    assert d._confirmed(0.8) is True
    d.verify = None
    assert d._confirmed(0.8) is True
