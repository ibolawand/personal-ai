"""How Aria says each sentence: the emotion, her voice's colour, pace and loudness, the pauses, and her little sounds
(a laugh, "hmm", "aww"). Kokoro has no emotion control, so the feeling is made from what it does have, all decided
here in code:

  - colour: each emotion mixes a little of another Kokoro voice into her own (brighter af_bella when happy, the
    softer, breathier af_nicole when comforting or sad) and lifts or lowers her a fraction of a semitone;
  - pace and loudness per emotion, plus a small random change per sentence so no two have the same cadence;
  - pauses: shorter between happy sentences, longer before a heartfelt one, a beat after a laugh or "hmm";
  - sounds: "haha" / "lol" is said as a short bright laugh, not spelled out; a laugh or "hmm" at the start of a
    sentence is said on its own, with its own tone.

The emotion of a sentence comes from its words, punctuation and emojis, and from the mood of the conversation
(Engines/Emotionengine.py) when the sentence itself is plain. Engines/voice_engine.py applies it.
"""
import random
import re
import os
from dataclasses import dataclass

# per emotion: (accent voice, how much of it), pitch change in semitones, pace, loudness, extra pause after (s)
STYLES = {
    "neutral":  {"accent": None,            "lift": 0.0,  "speed": 1.0,  "gain": 1.0,  "pause": 0.0},
    "happy":    {"accent": ("af_bella", .35), "lift": 0.5,  "speed": 1.05, "gain": 1.05, "pause": -0.08},
    "excited":  {"accent": ("af_bella", .55), "lift": 1.0,  "speed": 1.09, "gain": 1.1,  "pause": -0.1},
    "teasing":  {"accent": ("af_bella", .25), "lift": 0.4,  "speed": 1.02, "gain": 1.0,  "pause": 0.05},
    "curious":  {"accent": None,            "lift": 0.3,  "speed": 1.02, "gain": 1.0,  "pause": 0.0},
    "thinking": {"accent": None,            "lift": -0.2, "speed": 0.93, "gain": 0.95, "pause": 0.1},
    "soft":     {"accent": ("af_nicole", .3), "lift": -0.3, "speed": 0.92, "gain": 0.85, "pause": 0.15},
    "sad":      {"accent": ("af_nicole", .4), "lift": -0.7, "speed": 0.88, "gain": 0.8,  "pause": 0.25},
    "laugh":    {"accent": ("af_bella", .5),  "lift": 1.2,  "speed": 1.15, "gain": 1.0,  "pause": 0.0},
}

SENTENCE_PAUSE_S = 0.35     # between sentences
COMMA_PAUSE_S = 0.12        # after a clause (a long first sentence is said in two parts)
SOUND_PAUSE_S = 0.16        # the beat after a laugh, "hmm" or "oh!" said on its own
HEARTFELT_PAUSE_S = 0.15    # extra breath before a soft or sad sentence that follows another
MIN_PAUSE_S = 0.1
SPEED_WOBBLE = 0.03         # each sentence's pace varies this much either way
PAUSE_WOBBLE = 0.05

# Character comes from phrasing, not a bigger pitch shift. Keep excitement light and
# comforting lines conversational instead of stretching them into a solemn voice.
EXPRESSIVE = {
    "neutral": (0.99, 0.10, 1.0, -0.04),
    "happy": (1.03, 0.35, 1.02, -0.03),
    "excited": (1.07, 0.70, 1.05, -0.02),
    "teasing": (0.96, 0.25, 0.98, 0.08),
    "curious": (0.97, 0.45, 0.98, 0.08),
    "thinking": (0.95, -0.15, 0.96, 0.06),
    "soft": (0.96, -0.25, 0.90, 0.07),
    "sad": (0.93, -0.45, 0.87, 0.10),
    "laugh": (1.08, 0.65, 1.0, 0.0),
}
TURN_RE = re.compile(r"\s+[—–]\s+|;\s+|,\s+(?=(?:but|actually|honestly|aber|ehrlich)\b)", re.I)
GREETING_RE = re.compile(r"^\s*(?:hey|hi|hello|morning|hallo|na)[!, .]", re.I)

EMOJI_MOODS = [
    ("sad", "😢😭🥺😞😔💔"), ("teasing", "😏😜😛🙃😈"), ("thinking", "🤔"),
    ("excited", "🤩🥳🎉"), ("happy", "😂🤣😄😁😊😆☺🙂😃❤💜✨"),
]
SAD_RE = re.compile(r"\b(sad|i miss|miss (?:you|them|her|him)|that sucks|unfortunately|heartbreaking|i'?m so sorry|"
                    r"sorry (?:to hear|for your loss)|that'?s awful|lonely|cry(?:ing)?)\b", re.I)
SOFT_RE = re.compile(r"\b(sorry|aw+|oh no|that sounds (?:really |so |pretty )?(?:rough|hard|tough|awful|annoying|frustrating|unfair|exhausting)|"
                     r"i'?m here for you|take (?:it easy|care|a break|your time)|it'?s (?:okay|ok|alright)|"
                     r"you'?ll be (?:fine|okay)|get some rest|breathe|i'?m proud|that must|good night|sleep well)\b",
                     re.I)
EXCITED_RE = re.compile(r"\b(wow|yay|omg|oh my god|let'?s go+|woo+|no way|amazing|incredible|congrats|"
                        r"congratulations)\b", re.I)
HAPPY_RE = re.compile(r"\b(haha+|hehe+|lol|nice|awesome|love|great|cool|yes+|fun|glad|cute|ooh+|knew you could|so proud)\b", re.I)
TEASING_RE = re.compile(r"\b(rude|sure you did|nice try|suspicious|caught you|you caught me|i knew it|"
                        r"oh really|bold of you|told you so|admit it)\b", re.I)
THINKING_RE = re.compile(r"^\s*(hmm+|well,|let me think|i guess|maybe|i'?m not sure)\b", re.I)

# a laugh, "hmm" or "oh!" leading a sentence: said by itself, then the rest
LAUGH_RE = re.compile(r"(?:\*laughs\*|\b(?:ha(?:ha)+h?|he(?:he)+|lol|lmao)\b)[!.]*", re.I)
# ("Oh no, …" stays whole: "oh" and "aw" only count with a mark after them, "Oh! …", "Aww, …")
LEAD_SOUND_RE = re.compile(r"^\s*(?:(ha(?:ha)+h?|he(?:he)+|lol|lmao|hmm+)\b[!.,]*|(ooh+|oh|aw+)[!.,]+)\s+(?=\S)", re.I)

MOOD_LEANS = {"sad": "soft", "angry": "soft", "excited": "happy"}   # the conversation's mood colours plain sentences


def emotion(sentence: str, mood: str = "neutral") -> str:
    """The emotion a sentence is said with. Its own words win; a plain sentence takes the conversation's mood."""
    text = sentence or ""
    for name, emojis in EMOJI_MOODS:
        if any(e in text for e in emojis):
            return name
    if SAD_RE.search(text):
        return "sad"
    if SOFT_RE.search(text):
        return "soft"
    if TEASING_RE.search(text):
        return "teasing"
    if EXCITED_RE.search(text) or text.rstrip().endswith("!!"):
        return "excited"
    if HAPPY_RE.search(text) or text.rstrip().endswith("!"):
        return "happy"
    if THINKING_RE.search(text):
        return "thinking"
    if text.rstrip().endswith("?"):
        return "curious"
    return MOOD_LEANS.get(mood, "neutral")


def laugh_words(text: str) -> str:
    """Readable text for a laugh piece; the voice engine renders its breath pulses separately."""
    def say(m):
        word = m.group(0).rstrip("!.").lower()
        return ("Heh heh" if word.startswith("he") else "Ha ha") + "!"
    return LAUGH_RE.sub(say, text)


def sound_style(sound: str) -> str:
    s = sound.lower()
    if s.startswith(("ha", "he", "lol", "lm")):
        return "laugh"
    if s.startswith("hm"):
        return "thinking"
    if s.startswith("aw"):
        return "soft"
    return "excited" if s.startswith("oo") else "happy"


def sound_text(sound: str) -> str:
    s = sound.lower()
    if s.startswith("hm"):
        return "Hmmm..."
    if s.startswith("aw"):
        return "Awww."
    if s.startswith("oo"):
        return "Oooh!"
    if s.startswith("oh"):
        return "Oh!"
    return laugh_words(sound)


@dataclass
class Piece:
    text: str
    style: str
    speed: float
    lift: float
    gain: float
    pause_before: float
    pause_after: float


class Delivery:
    """Turns the sentences of one reply, as they arrive, into pieces to synthesise. Remembers the previous one,
    so a heartfelt sentence after another gets a breath first."""

    def __init__(self, mood: str = "neutral", rand=None, profile=None):
        self.mood = mood or "neutral"
        self.rand = rand or random.Random()
        self.count = 0
        profile = profile or os.environ.get("ARIA_VOICE_PROFILE", "expressive")
        self.profile = profile if profile in ("expressive", "natural", "calm", "clear") else "natural"
        self._pace_drift = 0.0

    def _piece(self, text, style, end_pause):
        s = STYLES[style]
        wobble = 1 + self.rand.uniform(-SPEED_WOBBLE, SPEED_WOBBLE)
        before = HEARTFELT_PAUSE_S if self.count and style in ("soft", "sad") else 0.0
        after = max(MIN_PAUSE_S, end_pause + s["pause"] + self.rand.uniform(-PAUSE_WOBBLE, PAUSE_WOBBLE))
        self.count += 1
        speed, pitch, gain = s["speed"] * wobble, s["lift"], s["gain"]
        if self.profile == "expressive":
            pace, pitch, gain, pause = EXPRESSIVE[style]
            self._pace_drift = self._pace_drift * 0.6 + (wobble - 1) * 0.4
            speed = pace * (1 + self._pace_drift)
            before = min(before, 0.08)
            after = max(MIN_PAUSE_S, end_pause + pause + self.rand.uniform(-0.025, 0.025))
            if GREETING_RE.match(text) and style == "neutral":
                speed *= 0.98
                pitch = 0.25
            # Short acknowledgements should land, without sounding like an announcement.
            if style == "neutral" and len(text.split()) <= 4 and text.endswith("."):
                speed *= 0.98
                pitch -= 0.15
        elif self.profile == "calm":
            speed = 0.94 + (speed - 1) * 0.45
            pitch *= 0.4
            gain = 0.85 + (gain - 1) * 0.4
            after += 0.08
        elif self.profile == "clear":
            speed = 0.9 + (speed - 1) * 0.25
            pitch *= 0.6
            after += 0.12
        return Piece(text, style, speed, pitch, gain, before, after)

    def pieces(self, sentence: str, raw: str = None):
        """`sentence` is the text as it will be spoken; `raw` the same before cleaning (it still has the emojis)."""
        sentence = (sentence or "").strip()
        if not sentence:
            return []
        # Isolate actual laugh tokens anywhere in the reply. Happy words and emojis
        # alone never create a sound or an animation cue.
        matches = list(LAUGH_RE.finditer(sentence))
        if matches:
            out, at = [], 0
            for match in matches:
                head = sentence[at:match.start()].strip(" ,.!;")
                if head:
                    out.extend(self.pieces(head, head))
                out.append(self._piece(laugh_words(match.group()), "laugh", SOUND_PAUSE_S))
                at = match.end()
            tail = sentence[at:].lstrip(" ,.!; ")
            if tail:
                out.extend(self.pieces(tail[:1].upper() + tail[1:], raw=tail))
            return out
        out = []
        lead = LEAD_SOUND_RE.match(sentence)
        if lead:
            sound = lead.group(1) or lead.group(2)
            out.append(self._piece(sound_text(sound), sound_style(sound), SOUND_PAUSE_S))
            sentence = sentence[lead.end():]
            sentence = sentence[:1].upper() + sentence[1:]
            # the rest is said with its own feeling ("Haha! You caught me." is a laugh, then teasing)
            emojis = "".join(c for c in (raw or "") if any(c in e for _, e in EMOJI_MOODS))
            style = emotion(sentence + emojis, self.mood)
        else:
            style = emotion(raw or sentence, self.mood)
        end = SENTENCE_PAUSE_S if sentence[-1:] in ".!?" else COMMA_PAUSE_S
        # At most one meaningful turn in a sentence, never every comma (numbers,
        # lists and short replies must retain their continuous intonation).
        if self.profile == "expressive" and len(sentence) >= 60:
            for match in TURN_RE.finditer(sentence):
                head, tail = sentence[:match.start()].strip(), sentence[match.end():].strip()
                if len(head.split()) >= 4 and len(tail.split()) >= 4:
                    head_style = emotion(head, self.mood)
                    out.append(self._piece(laugh_words(head + ","), head_style, 0.19))
                    out.append(self._piece(laugh_words(tail), emotion(tail, self.mood), end))
                    return out
        out.append(self._piece(laugh_words(sentence), style, end))
        return out
