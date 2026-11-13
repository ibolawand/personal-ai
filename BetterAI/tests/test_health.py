import types
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

from Engines.Health import Health


def test_report_names_problems_and_fixes(aria, monkeypatch):
    import ollama
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
