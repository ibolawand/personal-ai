import main
import random
import numpy as np
import pytest
from Engines import VoiceStyle
from Engines.voice_engine import VoiceEngine, normalize_for_tts


@pytest.mark.parametrize('text', ['haha', 'Hehe!', 'lol', '*laughs*', 'Well, haha, you caught me.'])
def test_real_laugh_is_a_separate_piece(text):
    pieces = VoiceStyle.Delivery(rand=random.Random(1)).pieces(normalize_for_tts(text), text)
    assert sum(p.style == 'laugh' for p in pieces) == 1


@pytest.mark.parametrize('text', ['That is lovely! 😊', '*smiles* Nice!', 'A laughing bird.', 'The lollipop is great.'])
def test_happy_words_do_not_create_a_laugh(text):
    pieces = VoiceStyle.Delivery().pieces(normalize_for_tts(text), text)
    assert all(p.style != 'laugh' for p in pieces)


def test_a_laugh_is_one_short_hah_and_its_vowel_drives_the_laugh_movement():
    engine = VoiceEngine.__new__(VoiceEngine)
    calls = []
    def synth(text, **kwargs):
        calls.append(text)
        return (np.sin(np.arange(12000) * .06).astype(np.float32) * .2, 24000,
                [[0, .05, None, 0, 0], [.05, .3, 'aa', .9, 1]])
    engine._synthesize = synth
    piece = VoiceStyle.Delivery().pieces('haha')[0]
    audio, sr, mouth = engine._synthesize_piece(piece)
    assert calls == ['Hah!'], "Kokoro says one 'Hah!', never 'haha' or spliced copies"
    assert mouth == [[0, .05, None, 0, 0], [.05, .3, 'aa', .9, 1, 'laugh']]
    # without a timeline from the voice engine, the whole sound is the laugh
    engine._synthesize = lambda text, **kw: (np.zeros(2400, dtype=np.float32), 24000, None)
    assert engine._synthesize_piece(piece)[2] == [[0.0, 0.1, 'aa', 0.85, 0, 'laugh']]


def test_playback_padding_and_trim_move_laugh_cues_with_the_sound():
    from Engines.LipSync import shift_timeline
    original = [[0, .17, 'aa', .85, 0, 'laugh'], [.225, .415, 'aa', .85, 0, 'laugh']]
    assert shift_timeline(original, .12 - .04) == [
        [.08, .25, 'aa', .85, 0, 'laugh'], [.305, .495, 'aa', .85, 0, 'laugh']]
    assert shift_timeline(original, -.2) == [[.025, .215, 'aa', .85, 0, 'laugh']]
    assert original[0][0] == 0


def test_small_talk_keeps_laughs_through_completed_and_streamed_cleanup():
    raw = "*laughs* You caught me!"
    completed = main.humanize(raw, "That was funny.")
    spoken = []
    streamer = main.SentenceStreamer(spoken.append, chat_about="That was funny.")
    streamer.feed(raw)
    streamer.flush()
    for text in [completed, " ".join(spoken)]:
        assert any(p.style == 'laugh' for p in VoiceStyle.Delivery().pieces(normalize_for_tts(text)))


def test_preview_compares_readout_and_rendered_laugh_with_final_audio_cues():
    from tools.voice_preview import laugh_comparison
    engine = VoiceEngine.__new__(VoiceEngine)
    calls = []
    def synth(text, **kwargs):
        calls.append(text)
        # Leading silence must be trimmed from both the WAV and its cues.
        source = .2 * np.sin(2 * np.pi * 230 * np.arange(7200) / 24000)
        return (np.concatenate([np.zeros(2400), source]).astype(np.float32), 24000,
                [[0, .1, None, 0, 0], [.1, .4, 'aa', .8, 0]])
    engine._synthesize = synth
    before, after = list(laugh_comparison(engine, {}, 'test'))
    assert before[0] == 'before' and after[0] == 'after'
    assert calls == ['Ha ha!', 'You caught me.', 'Hah!', 'You caught me.']
    assert all(s[-1] != 'laugh' for s in before[3])
    cues = [s for s in after[3] if s[-1] == 'laugh']
    assert len(cues) == 1
    assert all(a[1] <= b[0] for a, b in zip(after[3], after[3][1:]))
    for a, b, *_ in cues:
        assert 0 <= a < b <= len(after[1]) / after[2]
        assert np.sqrt(np.mean(after[1][round(a * after[2]):round(b * after[2])] ** 2)) > .02
