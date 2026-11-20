"""Two messages in a row in casual chat, so Aria doesn't only react. Everything here is decided in code.

A. split_reply: a short small-talk reply made of a reaction and a question ("Haha no way. Did you finish it?")
   is shown as two chat bubbles, a moment apart.
B. A follow-up: sometimes, a few seconds after a small-talk reply that didn't ask anything, she adds one short
   line of her own (an afterthought, a related question). main.py writes it with the local model in a background
   thread and drops it as soon as you type, talk or another turn starts. Never sent to the big model.
"""
import random
import re

FOLLOW_UP_CHANCE = 0.25           # after a small-talk reply that didn't ask anything
FOLLOW_UP_GAP = 3                 # at least this many turns between two follow-ups
FOLLOW_UP_DELAY = (2.0, 4.0)      # seconds she "thinks" before the second message
SPLIT_PAUSE = (0.7, 1.4)          # seconds between the two halves of a split reply
FOLLOW_UP_MAX_WORDS = 18

_SENT_RE = re.compile(r"(?<=[.!?…])\s+")


def _sentences(text: str):
    return [s for s in _SENT_RE.split((text or "").strip()) if s]


def split_reply(text: str):
    """A short casual reply as one or two bubbles. Split only when it is plain prose of 2-3 sentences:
    a short reaction first ("Haha, nice!") or a question last. Anything with lines, code or lists stays whole."""
    text = (text or "").strip()
    if not text or "\n" in text or "```" in text or len(text) > 260 or re.search(r"^\s*[-*•\d]", text):
        return [text] if text else []
    parts = _sentences(text)
    if not 2 <= len(parts) <= 3:
        return [text]
    if parts[-1].endswith("?") and not parts[-2].endswith("?"):
        return [" ".join(parts[:-1]), parts[-1]]
    if len(parts[0].split()) <= 5 and parts[0][-1] in "!.":
        return [parts[0], " ".join(parts[1:])]
    return [text]


def want_follow_up(reply: str, small_talk: bool, used, turns_since_last: int, rand=random.random) -> bool:
    """Whether to try a second message after this reply. Only after casual chat with no tools, when her reply
    didn't already ask something, not too often and only by chance."""
    reply = (reply or "").strip()
    if not small_talk or used or not reply or reply.endswith("?") or turns_since_last < FOLLOW_UP_GAP:
        return False
    return rand() < FOLLOW_UP_CHANCE


def follow_up_prompt(user_input: str, reply: str) -> str:
    return (f"Lala wrote: \"{user_input}\"\nYou answered: \"{reply}\"\n\n"
            "Now send ONE more short chat message right after it, the way a friend sends a second text: an "
            "afterthought, a small related question, or a reaction to your own answer. Under 15 words. Don't "
            "repeat what you said, don't offer help, no greeting. If nothing natural comes to mind, write only SKIP.")


def clean_follow_up(line: str, reply: str, robotic_re=None):
    """The model's follow-up, or None when it should not be sent: SKIP, empty, too long, an assistant line or
    mostly what she already said."""
    line = (line or "").strip().strip('"').strip()
    if not line or line.upper().startswith("SKIP") or line.startswith("Error:") or "\n" in line:
        return None
    if len(line.split()) > FOLLOW_UP_MAX_WORDS or (robotic_re and robotic_re.search(line)):
        return None
    words = set(re.findall(r"[a-z']+", line.lower()))
    said = set(re.findall(r"[a-z']+", (reply or "").lower()))
    if words and len(words & said) / len(words) > 0.7:
        return None
    return line
