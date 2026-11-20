"""
What a short cancel command means, decided in code: "cancel", "stop the timer", "end the focus session", "cancel the
tea timer", and, right after she set something, "no don't do that" / "never mind". The small model got these wrong:
it cancelled a reminder when asked to "exit the timer" (it guessed the text to match), couldn't stop a running focus
session (the reminder tool doesn't see those, and "cancel" alone doesn't route the focus tools), and answered "Got
it, I won't set the timer" while the timer kept running.

Only short commands that are clearly about her timers, reminders or the focus session are taken here; anything else
("cancel my meeting tomorrow", "stop the music", "stop it, you're annoying") goes to the model as before. main.py
carries the result out (Aria._cancel_command).
"""
import re

UNDO_AFTER_S = 120              # "no, don't do that" takes back what she set this recently, nothing older

_FILLER = r"(?:(?:no+|nah|ok(?:ay)?|hey|aria|please|um+|uh+)[,.!]?\s+)*"
_VERB = r"(?:cancel|stop|end|exit|quit|kill|abort|turn off|switch off|remove|delete|clear|scrap)"
_TAIL = r"(?:\s+(?:please|now|for me|thanks?|thank you))*[.!]*"
_NOUN = (r"(?P<noun>timers?|alarms?|countdown|reminders?|focus(?: session| mode| time)?|pomodoro|"
         r"(?:study |work |focus )?session|break)")
# a verb, then nothing / it / that, or (a few words naming it and) one of her things
COMMAND_RE = re.compile(
    rf"^{_FILLER}{_VERB}(?:\s+(?P<pronoun>it|that|this)"
    rf"|\s+(?:the |my |that |this |a |an )?(?P<name>[a-z' -]{{0,30}}?)\s*{_NOUN})?{_TAIL}$", re.I)
UNDO_RE = re.compile(
    rf"^(?:no+[,.!]?\s*)?(?:don'?t(?: do (?:that|it))?|do not(?: do (?:that|it))?|never ?mind|forget (?:it|that)|"
    rf"undo (?:it|that)|take (?:it|that) back){_TAIL}$", re.I)


def _kind(noun: str) -> str:
    noun = noun.lower()
    if noun.startswith(("timer", "alarm", "countdown")):
        return "timer"
    if noun.startswith("reminder"):
        return "reminder"
    return "focus"


def _newest(items):
    return max(items, key=lambda r: r["created"]) if items else None


def cancel_target(text: str, *, pending, focus_running: bool, just_set=None):
    """What `text` asks her to cancel, or None when it isn't a cancel command of hers (the model handles it).

    `pending`: her timers and reminders ({id, kind, text, created}); `focus_running`: a focus session (or its break)
    is on; `just_set`: what her last turn set ({kind: 'timer'|'reminder'|'focus', item, ago (seconds)}) or None.
    Returns ("item", reminder) | ("focus", None) | ("none", kind or None) when there is nothing of that kind."""
    text = (text or "").strip().lower().replace("’", "'")
    recent = just_set if just_set and just_set.get("ago", 1e9) <= UNDO_AFTER_S else None

    def what_was_just_set():
        if not recent:
            return None
        if recent["kind"] == "focus":
            return ("focus", None) if focus_running else None
        item = recent.get("item")
        return ("item", item) if item and any(r["id"] == item["id"] for r in pending) else None

    if UNDO_RE.match(text):
        return what_was_just_set()
    m = COMMAND_RE.match(text)
    if not m:
        return None
    noun, name = m.group("noun"), (m.group("name") or "").strip()
    if not noun:
        # "cancel" / "cancel it" (not "stop" or "stop it": that is as often about her talking or the music)
        if not re.match(rf"^{_FILLER}cancel\b", text):
            return None
        # what she just set, else the focus session, else the newest timer, else the newest reminder
        just = what_was_just_set()
        if just:
            return just
        if focus_running:
            return ("focus", None)
        if not pending:
            return ("none", None)
        return ("item", _newest([r for r in pending if r["kind"] == "timer"]) or _newest(pending))
    kind = _kind(noun)
    if kind == "focus":
        return ("focus", None)              # (main.py says so when none is running)
    of_kind = [r for r in pending if r["kind"] == kind]
    if name and name not in ("the", "my", "that", "this"):
        words = [w for w in re.findall(r"[a-z']+", name) if w not in ("the", "my", "that", "this", "a", "an")]
        named = [r for r in of_kind if words and all(w in r["text"].lower() for w in words)]
        if named:
            return ("item", _newest(named))
        if words:
            return None                     # a name she doesn't have: let the model sort it out
    just = what_was_just_set()
    if just and just[0] == "item" and just[1]["kind"] == kind:
        return just
    return ("item", _newest(of_kind)) if of_kind else ("none", kind)
