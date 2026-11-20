"""Aria plays the piano while piano music plays (Engines/Piano.py)."""
from Engines import Piano


def test_piano_music_turns_it_on_and_other_music_or_pause_off():
    assert Piano.wanted([("play_genre", {"genre": "piano"})], "play a piano music on spotify") is True
    assert Piano.wanted([("play_playlist", {"query": "chill"})], "spiel Klaviermusik") is True
    assert Piano.wanted([("play_artist", {"artist": "Ludovico Einaudi"})], "play einaudi piano") is True
    assert Piano.wanted([("play_genre", {"genre": "pop"})], "play something") is False
    assert Piano.wanted([("pause_music", {})], "pause") is False
    assert Piano.wanted([("set_volume", {"level": 30})], "quieter") is None
    assert Piano.wanted([], "hi") is None
    # how a turn really records it: what the tool answered, as text (this crashed: 'str' has no attribute 'values')
    assert Piano.wanted([("play_genre", "Playing piano music")], "play the piano") is True
    assert Piano.wanted([("play_playlist", "Playing playlist 'Peaceful Piano'")], "something calm") is True
    assert Piano.wanted([("play_genre", "Playing pop music")], "play something") is False


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _mode(playing):
    shown, clock = [], Clock()

    def sleep(s):
        clock.t += s
    mode = Piano.PianoMode(shown.append, lambda: playing.pop(0) if playing else False, clock, sleep)
    return mode, shown


def test_it_stops_once_spotify_has_been_quiet_twice():
    mode, shown = _mode([True, True, False, False])
    mode.on, mode._run = True, 1
    mode._watch(1)
    assert shown == [False] and not mode.on


def test_a_new_song_or_pause_takes_over():
    mode, shown = _mode([])
    mode.start = lambda: (setattr(mode, "on", True), shown.append(True))   # no watcher thread in the test
    mode.update([("play_genre", {"genre": "piano"})], "piano please")
    mode.update([("play_genre", {"genre": "rock"})], "now rock")
    assert shown == [True, False] and not mode.on


def test_stop_it_stops_her_playing_however_the_model_stopped_the_music(monkeypatch):
    # (from the log: "stop it stop it" -> media_control({'action': 'stop'}) and her keyboard kept going)
    monkeypatch.setattr(Piano.PianoMode, "_watch", lambda self, run: None)   # (only what was said decides here)
    assert Piano.wanted([("media_control", "Stopped.")], "stop it stop it") is False
    assert Piano.wanted([("media_control", "Paused.")], "stop it") is False
    assert Piano.wanted([("media_control", "Skipped to the next track.")], "next one") is None
    mode, shown = _mode([True] * 10)
    mode.start()
    mode.update([], "stop it")                      # the model called no tool at all
    assert shown == [True, False] and not mode.on
    mode.start()
    mode.update([], "stop the piano please")
    assert not mode.on
    mode.start()
    for said in ["play it louder", "what is this song", "don't stop"]:
        mode.update([], said)
        assert mode.on, said
    off, shown2 = _mode([])
    off.update([], "stop it")                       # not playing: nothing to stop, nothing shown
    assert shown2 == [] and not off.on
