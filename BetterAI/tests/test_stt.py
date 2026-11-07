"""When the microphone counts as someone talking: the voice detector decides, not loudness."""
import types

import numpy as np

import speech_to_text as S


class FakeStream:
    """Plays a list of (seconds, loudness, is_speech) parts, then silence."""
    def __init__(self, parts, **_):
        self.blocks = []
        for seconds, loud, speech in parts:
            for _ in range(int(seconds * 16000 / 1024)):
                self.blocks.append(np.full((1024, 1), loud if not speech else -loud, dtype=np.float32))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        return (self.blocks.pop(0) if self.blocks else np.zeros((n, 1), np.float32)), False


def make_stt(monkeypatch, parts):
    stt = S.STTEngine.__new__(S.STTEngine)
    stt.sample_rate, stt.silence_threshold, stt.silence_duration = 16000, 0.01, 1.2
    stt.max_duration, stt.on_level = 30.0, None
    # the fake detector: negative samples are "speech" (loud noise is positive, so loudness alone fools nothing)
    stt.vad = lambda window: np.array([0.9 if window[-1] < 0 else 0.05] * 2)
    monkeypatch.setattr(S.sd, "InputStream", lambda **kw: FakeStream(parts))
    return stt


def test_loud_noise_is_not_speech(monkeypatch):
    stt = make_stt(monkeypatch, [(5, 0.2, False)])           # a fan / music, well above the old threshold
    assert stt._record(start_timeout=3) is None


def test_records_speech_and_ends_on_silence_despite_noise(monkeypatch):
    stt = make_stt(monkeypatch, [(1, 0.2, False), (2, 0.1, True), (4, 0.2, False), (5, 0.1, True)])
    audio = stt._record(start_timeout=3)
    seconds = len(audio) / 16000
    assert 3.0 < seconds < 4.0                 # pre-roll + 2 s of speech + 1.2 s of quiet, not the later talking
    assert audio[0] > 0                        # a bit of what came before the first word is kept


def test_stop_ends_the_wait_but_not_someone_talking(monkeypatch):
    stt = make_stt(monkeypatch, [(3, 0.1, True)])
    assert stt._record(start_timeout=5, stop=lambda: True) is not None
    stt = make_stt(monkeypatch, [(3, 0.0, False)])
    assert stt._record(start_timeout=5, stop=lambda: True) is None


def test_whisper_loops_and_guesses_are_dropped():
    stt = S.STTEngine.__new__(S.STTEngine)
    stt.vocabulary = lambda: []
    seg = lambda text, cr=1.2, lp=-0.3: types.SimpleNamespace(text=text, compression_ratio=cr, avg_logprob=lp,
                                                               no_speech_prob=0.1)
    stt.model = types.SimpleNamespace(transcribe=lambda *a, **k: ([
        seg(" open my notes"), seg(" open my notes"), seg(" who said who said who said", cr=3.1),
        seg(" mumble", lp=-1.4)], None))
    text, _ = stt.transcribe(np.zeros(16000, np.float32))
    assert text == "open my notes"


def test_her_own_voice_and_unsure_guesses_dont_interrupt():
    from Engines.voice_engine import VoiceEngine, _words
    v = VoiceEngine.__new__(VoiceEngine)
    v._spoken_words = _words("I didn't miss you either, I've been glowing right here.")
    assert v._is_echo("i didn't miss you either. i've been glowing right here.")
    assert not v._is_echo("aria stop")


def test_speech_level_is_measured(monkeypatch):
    stt = make_stt(monkeypatch, [(1, 0.01, False), (2, 0.12, True)])
    stt._record(start_timeout=3)
    assert abs(stt.last_level - 0.12) < 0.02          # only the speech counts, not the quiet before it


def test_language_is_detected():
    stt = S.STTEngine.__new__(S.STTEngine)
    stt.vocabulary = lambda: []
    seg = types.SimpleNamespace(text=" hallo zusammen", compression_ratio=1.1, avg_logprob=-0.2, no_speech_prob=0.1)
    stt.model = types.SimpleNamespace(transcribe=lambda *a, **k: ([seg], None),
                                      detect_language=lambda audio, **k: ("de", 0.93, []))
    stt._record = lambda *a, **k: np.zeros(16000, np.float32)
    stt.silence_duration, stt.sample_rate = 1.2, 16000
    assert stt.listen() == "hallo zusammen"
    assert stt.last_language == ("de", 0.93)


def test_a_long_first_sentence_starts_at_its_first_clause():
    from Engines.voice_engine import first_chunks
    assert first_chunks("Planes don't crash from the weight of clouds, because clouds are made of tiny droplets.") == [
        "Planes don't crash from the weight of clouds,", "because clouds are made of tiny droplets."]
    assert first_chunks("Done, milk's on the list.") == ["Done, milk's on the list."]           # short: as is
    assert first_chunks("A sentence without any comma that is long enough to matter here for sure.") == [
        "A sentence without any comma that is long enough to matter here for sure."]
