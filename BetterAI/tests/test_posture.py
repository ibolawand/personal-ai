"""Posture and screen-distance nudges, from synthetic face positions (no camera)."""
import pytest

import Engines.Posture as P
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

T0 = 1_800_000_000          # a fixed start time, on a minute boundary


@pytest.fixture
def posture(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "STATE_FILE", str(tmp_path / "posture.json"))
    monkeypatch.setenv("ARIA_POSTURE", "1")
    return P.Posture()


def sit(p, start_min, minutes, w, cy):
    """Feed one sample every 10 s for `minutes`, starting `start_min` minutes after T0."""
    for i in range(minutes * 6):
        p.add(w, cy, T0 + start_min * 60 + i * 10)
    return T0 + (start_min + minutes) * 60


def test_learns_the_reference_from_the_first_minutes(posture):
    sit(posture, 0, 5, 0.20, 0.45)
    ref = posture.state["ref"]
    assert ref["w"] == pytest.approx(0.20) and ref["cy"] == pytest.approx(0.45) and not ref["manual"]


def test_leaning_in_for_ten_minutes_gives_one_nudge(posture):
    sit(posture, 0, 5, 0.20, 0.45)                       # upright
    now = sit(posture, 5, 11, 0.27, 0.45)                # 35% closer
    line = posture.nudge(now)
    assert line in P.CLOSE_LINES
    assert posture.nudge(now + 60) is None               # not again right away


def test_slouching_is_noticed(posture):
    sit(posture, 0, 5, 0.20, 0.45)
    now = sit(posture, 5, 11, 0.20, 0.56)
    assert posture.nudge(now) in P.SLOUCH_LINES


def test_normal_sitting_and_short_leans_are_fine(posture):
    sit(posture, 0, 5, 0.20, 0.45)
    sit(posture, 5, 6, 0.21, 0.46)                       # tiny changes
    now = sit(posture, 11, 4, 0.30, 0.45)                # only 4 minutes leaning in
    assert posture.problem(now) is None


def test_a_set_reference_is_not_overwritten(posture):
    for i in range(20):                                  # the camera gives several samples a second
        posture.add(0.18, 0.40, T0 + i)
    assert "good posture" in posture.set_reference(T0 + 20)
    sit(posture, 20, 5, 0.25, 0.50)                      # a new sitting starts slouched
    ref = posture.state["ref"]
    assert ref["manual"] and ref["w"] == pytest.approx(0.18)


def test_set_reference_needs_a_face(posture):
    assert "can't see you" in posture.set_reference(T0)


def test_daily_limit_and_off_switch(posture, monkeypatch):
    sit(posture, 0, 5, 0.20, 0.45)
    monkeypatch.setattr(P, "NUDGES_PER_DAY", 1)
    now = sit(posture, 5, 11, 0.28, 0.45)
    assert posture.nudge(now)
    now = sit(posture, 50, 11, 0.28, 0.45)
    assert posture.nudge(now) is None                     # one a day here
    posture.enabled = False
    assert posture.nudge(now + 3600) is None


def test_camera_samples_reach_posture_and_nudges_respect_the_rules(aria, monkeypatch):
    import Engines.Initiative as I
    said = []
    aria.posture = fake = P.Posture.__new__(P.Posture)
    fake.nudge = lambda now: "Sit up a bit?"
    aria._announce = said.append
    aria.awake, aria.muted, aria._shutting_down = False, False, False
    aria.activity = None
    for name in ("in_quiet_hours", "screen_locked", "fullscreen_app", "mic_in_use_by_others"):
        monkeypatch.setattr(I, name, lambda: False)
    init = I.Initiative.__new__(I.Initiative)
    init.aria, init.enabled = aria, True
    init._posture(0, present=True)
    assert said == ["Sit up a bit?"]
    aria.muted = True
    init._posture(0, present=True)
    monkeypatch.setattr(I, "in_quiet_hours", lambda: True)
    aria.muted = False
    init._posture(0, present=True)
    assert said == ["Sit up a bit?"]
