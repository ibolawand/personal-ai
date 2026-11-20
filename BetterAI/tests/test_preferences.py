import types

import pytest

from Engines.Preferences import Preferences


def test_saved_preferences_override_defaults_and_apply_live(tmp_path, monkeypatch):
    from Engines import Desk
    monkeypatch.setattr(Desk, "QUIET", "")
    path = tmp_path / "settings.json"
    prefs = Preferences(option=2, path=path)
    values = {**prefs.values, "claude": False, "autonomous_chats": False, "muted": True,
              "quiet_hours": "23:00-07:00", "microphone": "typing"}
    prefs.save(values)
    loaded = Preferences(option=2, path=path)
    assert loaded.values == values
    aria = types.SimpleNamespace(big=types.SimpleNamespace(enabled=True))
    loaded.apply(aria)
    assert aria.muted and not aria.autonomous_chats and not aria.big.enabled
    assert Desk.QUIET == "23:00-07:00"


@pytest.mark.parametrize("quiet", ["25:00-08:00", "08:65-12:00", "08:00-08:00", "nonsense"])
def test_invalid_settings_leave_saved_preferences_unchanged(tmp_path, quiet):
    prefs = Preferences(path=tmp_path / "settings.json")
    prefs.save(prefs.values)
    before = prefs.path.read_text()
    with pytest.raises(ValueError):
        prefs.save({**prefs.values, "quiet_hours": quiet})
    assert prefs.path.read_text() == before


def test_corrupt_file_falls_back_to_environment(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"claude": "false"}')
    monkeypatch.setenv("ARIA_BIG_MODEL", "0")
    assert Preferences(path=path).values["claude"] is False
