"""Was that said to Aria? While she's awake in voice mode, a person nearby or a video is still real speech.

What she hears counts as for her when:
  - it has her name in it, or she's waiting for an answer (a yes/no, the weekly review, a quiz, dictation,
    "did you say …?", or a conversation she started), or
  - you're at the desk (the camera saw your face, or the keyboard/mouse was used, in the last AT_DESK_S) and it's
    a command ("play some music", any time while she's awake) or it starts within the follow-up window:
    FOLLOWUP_S after she woke up or answered, ASKED_S if she asked a question.
Without a camera and with no idle info, only the follow-up window applies.
Two more signs of someone else (unless it has her name in it or she's waiting for an answer): Whisper is sure it's
not English (a conversation in the room), or it's much quieter than Lala usually is at the mic (QUIET_RATIO).
Anything else is logged and ignored; she stays awake until the normal sleep timeout.
"""
import re

FOLLOWUP_S = 30     # after she wakes or answers, you can just talk
ASKED_S = 45        # ...longer when she asked you something
AT_DESK_S = 20      # your face (or keyboard/mouse use) this recently = you're the one talking
QUIET_RATIO = 0.4    # this much quieter than Lala's usual level at the mic = someone further away, or a video
OTHER_LANGUAGE_P = 0.8
NAME_RE = re.compile(r"\b(?:aria|arya|ariya|ariah)\b", re.I)


def not_for_aria(text: str, since_s: float, asked: bool = False, expecting: bool = False,
                 face_age_s: float | None = None, idle_s: float | None = None, command: bool = False,
                 language: tuple | None = None, level_ratio: float | None = None) -> str | None:
    """None when it's for her, else why not ("nobody at the desk", "not addressed").
    face_age_s: seconds since the camera last saw a face (None: no camera). idle_s: seconds since keyboard/mouse use."""
    if expecting or NAME_RE.search(text or ""):
        return None
    if language and language[0] != "en" and language[1] >= OTHER_LANGUAGE_P:
        return "not English"
    if level_ratio is not None and level_ratio < QUIET_RATIO:
        return "quieter than you usually are"
    signs = [s for s in (face_age_s, idle_s) if s is not None]
    if signs and min(signs) > AT_DESK_S:
        return "nobody at the desk"
    if not command and since_s > (ASKED_S if asked else FOLLOWUP_S):
        return "not addressed"
    return None
