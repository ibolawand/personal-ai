"""Bob to music: the beat is found from the sound's loudness pulses (no model, no audio stored)."""
import numpy as np
import pytest

from Engines.Beat import FPS, envelope, find_beat, others_playing

RATE = 8000


def clicks(bpm, seconds=8.0, offset=0.1, noise=0.02, seed=0):
    rng = np.random.default_rng(seed)
    x = noise * rng.standard_normal(int(RATE * seconds))
    period = 60 / bpm
    for k in range(int(seconds / period) + 1):
        i = int((offset + k * period) * RATE)
        n = int(0.03 * RATE)
        if i + n < len(x):
            x[i:i + n] += np.hanning(n) * np.sin(np.arange(n) * 0.9)       # a drum hit
    return (x * 12000).astype(np.int16)


@pytest.mark.parametrize("bpm", [90, 120, 150])
def test_finds_the_tempo_of_a_steady_beat(bpm):
    found, _, conf = find_beat(envelope(clicks(bpm), RATE), FPS)
    assert abs(found - bpm) < 3 and conf >= 0.35


def test_finds_where_the_beat_is():
    """phase: seconds from the end of the window to the next beat."""
    bpm, offset, seconds = 120, 0.1, 8.0
    _, next_in, _ = find_beat(envelope(clicks(bpm, seconds, offset), RATE), FPS)
    period = 60 / bpm
    expected = (offset - seconds) % period
    assert min(abs(next_in - expected), period - abs(next_in - expected)) < 0.06


def test_noise_or_talk_has_no_clear_beat():
    rng = np.random.default_rng(1)
    noise = (rng.standard_normal(RATE * 8) * 3000).astype(np.int16)
    assert find_beat(envelope(noise, RATE), FPS)[2] < 0.35
    assert find_beat(envelope(np.zeros(RATE * 8, np.int16), RATE), FPS)[2] == 0


PACTL = """Sink Input #41
\tCorked: no
\tProperties:
\t\tapplication.name = "spotify"
\t\tapplication.process.id = "5000"
Sink Input #42
\tCorked: no
\tProperties:
\t\tapplication.process.id = "777"
Sink Input #43
\tCorked: yes
\tProperties:
\t\tapplication.process.id = "6000"
"""


def test_another_app_playing_counts_her_own_voice_and_paused_streams_do_not():
    assert others_playing(PACTL, own_pids={777})
    assert not others_playing(PACTL.replace('Corked: no\n\tProperties:\n\t\tapplication.name = "spotify"',
                                            'Corked: yes\n\tProperties:\n\t\tapplication.name = "spotify"'),
                              own_pids={777})
    assert not others_playing("", own_pids={777})


class FakeUI:
    def __init__(self):
        self.beats = []

    def set_beat(self, bpm, next_in, conf):
        self.beats.append((bpm, next_in, conf))


def reader(may=True, playing=True, sound=None):
    from Engines.Beat import BeatReader
    ui = FakeUI()
    flags = {"may": may, "playing": playing}
    r = BeatReader(ui, lambda: flags["may"], playing=lambda: flags["playing"], clock=lambda: 0.0)
    r._open = lambda: None                              # no parec in tests: the sound is put in by hand
    r._buf = clicks(120) if sound is None else sound
    r.flags, r.ui_ = flags, ui
    r.wanted_fresh = lambda: setattr(r, "_checked", -1e9)
    return r


def test_tells_the_page_the_beat_while_music_plays():
    r = reader()
    r.step()
    [(bpm, next_in, conf)] = r.ui_.beats
    assert abs(bpm - 120) < 3 and 0 <= next_in < 0.5 and conf >= 0.35


def test_music_stopping_or_her_speaking_stops_the_bob_once():
    r = reader()
    r.step()
    r.flags["may"] = False                              # she speaks (or a lesson starts)
    r.step()
    r.step()
    assert r.ui_.beats[1:] == [(0, 0, 0)]
    r.flags["may"], r.flags["playing"] = True, False    # music paused
    r.wanted_fresh()
    r.step()
    assert r.ui_.beats[1:] == [(0, 0, 0)]


def test_no_clear_beat_no_bob():
    rng = np.random.default_rng(3)
    r = reader(sound=(rng.standard_normal(RATE * 8) * 3000).astype(np.int16))
    r.step()
    assert r.ui_.beats == []
