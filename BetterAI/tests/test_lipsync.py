"""Her mouth from the sounds she says (Engines/LipSync.py): no model, Kokoro's output is written out by hand."""
from Engines import LipSync
from Engines.LipSync import STEP_S


def shapes(tl):
    return [seg[2] for seg in tl]


def test_closed_lips_round_vowels_and_diphthongs():
    # "maybe": m, ˈ (stress), A (eɪ, two parts), b, i  -- durations with one step at each end
    tl = LipSync.timeline([("mˈAbi", [1, 2, 2, 2, 3, 4, 1])])
    assert shapes(tl) == [None, "ee", "ih", None, "ih", None]
    start, m = tl[0], tl[1]
    assert start[0] == 0 and abs(start[1] - 3 * STEP_S) < 1e-6           # the lead-in and the "m": lips together
    # the stress mark's time goes to the vowel after it, and the vowel carries the stress
    assert abs((tl[2][1] - tl[1][0]) - 4 * STEP_S) < 1e-6
    assert m[4] == 1.0 and tl[2][4] == 0 and tl[4][4] == 0
    assert abs(tl[-1][1] - 15 * STEP_S) < 1e-6                           # all of it, end included


def test_pauses_shut_the_mouth_and_spaces_extend_the_sound_before():
    tl = LipSync.timeline([("tu, ju", [1, 2, 4, 3, 2, 2, 4, 1])])
    assert shapes(tl) == [None, "ee", "ou", None, "ih", "ou", None]
    ou = tl[2]
    assert abs((ou[1] - ou[0]) - 4 * STEP_S) < 1e-6
    # the space after the comma has no sound before it to extend: it goes to the next one
    assert abs((tl[4][1] - tl[4][0]) - 4 * STEP_S) < 1e-6


def test_lift_and_offset_move_the_timeline_with_the_audio():
    plain = LipSync.timeline([("ɑ", [2, 10, 2])])
    lifted = LipSync.timeline([("ɑ", [2, 10, 2])], rate=1.12246, offset=0.1)
    rate = round(1000 * 1.12246) / 1000
    assert abs(lifted[1][0] - (plain[1][0] / rate + 0.1)) < 1e-3
    assert abs(lifted[-1][1] - (plain[-1][1] / rate + 0.1)) < 1e-3
    # trimmed off the front: what is left starts at 0, nothing before it
    trimmed = LipSync.timeline([("ɑ", [2, 10, 2])], offset=-0.06)
    assert trimmed[0][0] == 0 and all(seg[1] > 0 for seg in trimmed)


def test_unknown_sounds_and_bad_input():
    tl = LipSync.timeline([("x", [1, 2, 1])])
    assert tl[1][2:4] == ["ee", 0.3]
    try:
        LipSync.timeline([("ab", [1, 2])])
    except ValueError:
        pass
    else:
        raise AssertionError("durations that don't fit the phonemes must be refused")
    assert LipSync.shape_at(tl, 0.03)[2] == "ee" and LipSync.shape_at(tl, 9) is None


def test_several_chunks_follow_one_another():
    tl = LipSync.timeline([("ɑ", [1, 4, 1]), ("u", [1, 4, 1])])
    assert shapes(tl) == [None, "aa", None, "ou", None]
    assert abs(tl[3][0] - 7 * STEP_S) < 1e-6
