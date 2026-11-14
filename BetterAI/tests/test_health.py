import types
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

from Engines.Health import Health


def test_report_names_problems_and_fixes(aria, monkeypatch):
    import ollama
    import llm_engine
    monkeypatch.setattr(llm_engine, "LLM_MODEL_DEFAULT", "qwen3:8b")     # installed here: only the picture model is missing
    monkeypatch.setattr(ollama, "list", lambda: types.SimpleNamespace(models=[types.SimpleNamespace(model="qwen3:8b")]))
    aria.spotify = None
    aria.vision = types.SimpleNamespace(_camera_index=None, is_present=False)
    aria.weather = types.SimpleNamespace(state={})
    out = Health(aria).report()
    assert "need attention" in out
    assert "missing model(s): qwen2.5vl:3b — run: ollama pull qwen2.5vl:3b" in out
    assert "PROBLEM — Spotify: not connected" in out
    assert "PROBLEM — Weather: no home city" in out
    assert "OK — MyNotion" in out


def test_a_crashing_check_is_reported_not_raised(aria, monkeypatch):
    import ollama

    def boom():
        raise ConnectionError("ollama is not running")
    monkeypatch.setattr(ollama, "list", boom)
    rows = {name: (ok, detail) for name, ok, detail in Health(aria).checks()}
    assert rows["Language and vision models"] == (False, "ollama is not running")


def test_a_switched_off_camera_is_not_a_problem(aria, monkeypatch):
    aria.vision = types.SimpleNamespace(_camera_index=None, is_present=False)
    monkeypatch.delenv("ARIA_CAMERA", raising=False)
    rows = {name: (ok, detail) for name, ok, detail in Health(aria).checks()}
    assert rows["Camera"] == (True, "switched off (ARIA_CAMERA=1 in Engines/.env turns it on)")
    monkeypatch.setenv("ARIA_CAMERA", "1")
    rows = {name: (ok, detail) for name, ok, detail in Health(aria).checks()}
    assert rows["Camera"] == (False, "no camera found (set CAMERA_INDEX if you have one)")


def test_the_avatar_is_reported_with_its_reason(aria):
    def row(status):
        aria.ui = types.SimpleNamespace(avatar_status=status)
        return {name: (ok, detail) for name, ok, detail in Health(aria).checks()}.get("Avatar")
    assert row("ready to load (built-in figure)") == (True, "ready to load (built-in figure)")
    assert row("switched off (ARIA_AVATAR=0)") == (True, "switched off (ARIA_AVATAR=0)")
    assert row("no avatar file at /x/aria.vrm") == (False, "no avatar file at /x/aria.vrm")
    assert row("no WebGL") == (False, "no WebGL")
    aria.ui = main.NullUI()
    assert "Avatar" not in {name for name, _, _ in Health(aria).checks()}       # no overlay, nothing to report


def test_a_missing_chat_model_is_named_with_how_to_get_it(aria, monkeypatch):
    """Her brain is a setting (ARIA_MODEL): if that model isn't downloaded, the start-up check says which and how."""
    import ollama
    import llm_engine
    monkeypatch.setattr(llm_engine, "LLM_MODEL_DEFAULT", "qwen3:30b-a3b-instruct-2507-q4_K_M")
    monkeypatch.setattr(ollama, "list", lambda: types.SimpleNamespace(
        models=[types.SimpleNamespace(model=m) for m in ("qwen3:8b", "qwen2.5vl:3b")]))
    rows = {name: (ok, text) for name, ok, text in Health(aria).checks()}
    ok, text = rows["Language and vision models"]
    assert not ok and "ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M" in text
