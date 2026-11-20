"""
Her mouth follows what she actually says. Kokoro reports every phoneme it speaks and how long it lasts (`pred_dur`,
600 samples at 24 kHz a step), so the shape of her mouth is decided here from the sounds themselves: lips together
on "m", "b" and "p", rounded on "oo" and "w", spread on "ee", wide open on "ah", and diphthongs ("eye", "how") move
from one shape to the next. The avatar's page plays the result on its own clock (ui/avatar/logic.mjs speechShapes);
how far her mouth opens still follows the loudness of the audio, so a quiet word stays small.

Shapes are the five VRM mouth shapes: aa (あ, open), ih (い, spread), ou (う, round), ee (え, half open, spread), oh (お,
round and open). A segment is [start s, end s, shape or None for closed, how open 0…1, stress]: stress is 1 on the
vowel of a stressed syllable, 0.5 on a secondary one, else 0 (her head moves on those beats). Nothing here needs the
model. Laugh syllables may append a sixth field, "laugh", to drive the body on the same clock.
"""

STEP_S = 600 / 24000            # one step of Kokoro's phoneme durations

SILENT = None                   # lips together, or simply shut between phrases

# misaki's phonemes (Kokoro's English) -> the mouth's parts in order; a diphthong has two
SHAPES = {
    # vowels
    "ɑ": [("aa", 1.0)], "ɒ": [("aa", 1.0)], "æ": [("aa", 0.85)], "ʌ": [("aa", 0.75)], "ɐ": [("aa", 0.7)],
    "ə": [("aa", 0.4)], "ᵊ": [("aa", 0.3)], "ᵻ": [("ih", 0.35)],
    "ɚ": [("ou", 0.45)], "ɝ": [("ou", 0.5)], "ɜ": [("ou", 0.5)],
    "ɛ": [("ee", 0.75)], "e": [("ee", 0.7)], "ɪ": [("ih", 0.55)], "i": [("ih", 0.8)],
    "ʊ": [("ou", 0.55)], "u": [("ou", 0.8)], "ɔ": [("oh", 0.85)], "o": [("oh", 0.8)],
    # diphthongs (misaki writes each as one capital letter)
    "A": [("ee", 0.75), ("ih", 0.5)], "I": [("aa", 0.95), ("ih", 0.5)], "W": [("aa", 0.95), ("ou", 0.65)],
    "Y": [("oh", 0.8), ("ih", 0.5)], "O": [("oh", 0.8), ("ou", 0.6)], "Q": [("aa", 0.4), ("ou", 0.6)],
    # consonants: the lips close, or the teeth show, or they round, or the jaw drops a little
    "m": [(SILENT, 0)], "b": [(SILENT, 0)], "p": [(SILENT, 0)],
    "f": [("ih", 0.15)], "v": [("ih", 0.15)],
    "w": [("ou", 0.6)], "ɹ": [("ou", 0.35)], "j": [("ih", 0.45)],
    "θ": [("ee", 0.3)], "ð": [("ee", 0.3)],
    "s": [("ih", 0.3)], "z": [("ih", 0.3)], "ʃ": [("ou", 0.35)], "ʒ": [("ou", 0.35)], "ʧ": [("ou", 0.35)],
    "ʤ": [("ou", 0.35)],
    "t": [("ee", 0.3)], "d": [("ee", 0.3)], "n": [("ee", 0.3)], "l": [("ee", 0.35)], "ɾ": [("ee", 0.3)],
    "k": [("aa", 0.3)], "ɡ": [("aa", 0.3)], "g": [("aa", 0.3)], "ŋ": [("aa", 0.3)], "h": [("aa", 0.35)],
    "ʔ": [(SILENT, 0)],
}
STRESS = {"ˈ": 1.0, "ˌ": 0.5, "ː": 0.0}   # marks with a duration of their own: it belongs to the sound after them
VOWELS = set("ɑɒæʌɐəᵊᵻɚɝɜɛeɪiʊuɔoAIWYOQ")
PAUSE = set(",.!?;:—…-\"'()[]“”")
UNKNOWN = [("ee", 0.3)]         # anything else: a half-open neutral mouth


def timeline(chunks, rate=1.0, offset=0.0):
    """The mouth through a piece of speech. `chunks`: Kokoro's results in order, each (phonemes, durations) with the
    durations for the phonemes plus one at each end (pred_dur). `rate`: how much faster the audio was played
    afterwards (the voice lift); `offset`: seconds of audio before the speech starts (negative: trimmed off).
    Returns segments [start, end, shape, open, stress] in seconds of the final audio, merged where nothing changes."""
    segments, at = [], 0.0

    def put(length, shape, amount, stress=0.0):
        nonlocal at
        if length <= 0:
            return
        last = segments[-1] if segments else None
        if last and last[2:] == [shape, amount, stress] and not stress and abs(last[1] - at) < 1e-9:
            last[1] = at + length
        else:
            segments.append([at, at + length, shape, amount, stress])
        at += length

    for phonemes, durations in chunks:
        durations = [float(d) for d in durations]
        if len(durations) != len(phonemes) + 2:
            raise ValueError("durations must cover every phoneme plus one at each end")
        put(durations[0] * STEP_S, SILENT, 0)
        carry = 0.0                                     # a stress mark's time, handed to the sound after it
        stress = 0.0                                    # ...and its stress, handed to the next vowel
        for ch, steps in zip(phonemes, durations[1:-1]):
            length = steps * STEP_S
            if ch in STRESS:
                carry += length
                stress = max(stress, STRESS[ch])
                continue
            if ch == " ":                               # between words: the sound before it lasts a little longer
                if segments and segments[-1][2] is not SILENT and abs(segments[-1][1] - at) < 1e-9:
                    segments[-1][1] += length
                    at += length
                else:
                    carry += length
                continue
            parts = [(SILENT, 0)] if ch in PAUSE else SHAPES.get(ch, UNKNOWN)
            length += carry
            carry = 0.0
            beat = stress if ch in VOWELS else 0.0
            if ch in VOWELS or ch in PAUSE:
                stress = 0.0
            for i, (shape, amount) in enumerate(parts):
                share = (0.55 if i == 0 else 0.45) if len(parts) == 2 else 1.0
                put(length * share, shape, amount, beat if i == 0 else 0.0)
        put(carry + durations[-1] * STEP_S, SILENT, 0)

    rate = round(1000 * rate) / 1000 if rate else 1.0   # the same rounding as voice_engine.lift
    out = []
    for start, end, shape, amount, stress in segments:
        start, end = start / rate + offset, end / rate + offset
        if end <= 0:
            continue
        out.append([round(max(0.0, start), 3), round(end, 3), shape, amount, stress])
    return out


def shape_at(segments, t):
    """The segment playing at `t` seconds (or None)."""
    for seg in segments or []:
        if seg[0] <= t < seg[1]:
            return seg
    return None


def shift_timeline(segments, seconds):
    """Move every sound and optional laugh cue by the playback padding minus trimmed silence."""
    return [[round(max(0.0, a + seconds), 3), round(b + seconds, 3), *rest]
            for a, b, *rest in segments if b + seconds > 0]
