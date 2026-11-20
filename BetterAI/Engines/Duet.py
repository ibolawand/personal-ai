"""Aria and Claude talk together, with Lala: brainstorming ideas or just chatting for fun.

"brainstorm with Claude about my birthday party", "you and Claude chat about cats", "let's talk with Claude": Aria
(the local model) and Claude (the big model through `claude -p`, Engines/BigModel.py) take turns, a few lines each,
in their own voices and bubbles. Lala can jump in at any time (typed, or said in the short pause after each round)
and "stop" / "that's enough" ends it. In "ideas" mode Aria sums up the best ideas at the end.

Everything is decided here in code: when it starts, the mode, how many turns, when it ends, and what Claude is sent.
Claude gets the topic and the lines said in this conversation, nothing else: never Aria's memory, the history, mail,
the calendar or anything from the laptop (the rules in Engines/BigModel.py).
"""
import re

MAX_ROUNDS = 3                  # a round: Claude says something, then Aria
CHAT_ROUNDS = 2                 # a chat of their own is shorter
CHAT_MODEL = "haiku"            # their own chats: the cheapest, quickest Claude; brainstorms keep the usual model
CHAT_GAP_MIN = (30, 120)        # minutes between their own chats: a random time in this range

# what they chat about by themselves: light and general, never anything about Lala
TOPICS = [
    "the best pizza topping", "would you rather fly or be invisible", "whether cats secretly run the world",
    "the weirdest animal in the ocean", "what music sounds like to an AI", "the perfect lazy Sunday",
    "if you could live in any video game world", "the moon", "the most overrated food", "dreams and why we have them",
    "what you'd name a pet dragon", "time travel: past or future", "the coziest weather", "aliens: real or not",
    "the best snack for studying", "a superpower that would be secretly useless", "black holes",
    "the funniest word in English", "robots taking up hobbies", "breakfast for dinner",
]
LINE_SENTENCES = 3
LINE_CHARS = 320

START_RE = re.compile(
    r"\b(?:brainstorm(?:ing)?\s+with\s+claude|(?:talk|chat|discuss)\s+(?:this\s+)?with\s+claude|"
    r"you\s+and\s+claude|claude\s+and\s+you|(?:invite|bring|get)\s+claude\b|let\s+claude\s+(?:join|in|talk)|"
    r"(?:let'?s|can we)\s+(?:all\s+)?(?:talk|chat|brainstorm)\s+(?:with|to)\s+claude|"
    r"mit\s+claude\s+(?:reden|quatschen|brainstormen|plaudern)|du\s+und\s+claude)\b", re.I)
IDEAS_RE = re.compile(r"\b(brainstorm\w*|ideas?|plan\w*|how (?:could|should|can) (?:i|we)|project|"
                      r"help me (?:think|decide|figure)|suggest\w*|ideen|planen)\b", re.I)
TOPIC_RE = re.compile(r"\b(?:about|on|regarding|über)\s+(.+?)[.?!]*$", re.I)
STOP_RE = re.compile(r"^\s*(?:ok(?:ay)?[, ]+)?(?:stop|enough|that'?s enough|that'?s it|end|quit|bye|thanks?(?: you)?|"
                     r"thank you both|genug|hör auf|danke)\b[\s.!]*$", re.I)
SPEAKER_RE = re.compile(r"^\s*\**(?:aria|claude|lala)\**\s*:\s*", re.I)

CLAUDE_SYSTEM = (
    "You are Claude, made by Anthropic, appearing on Lala's laptop next to Aria, Lala's playful desk assistant "
    "(a small local AI with an anime-girl avatar). The three of you are having a spoken conversation. Your lines are "
    "read aloud by a voice, so write plain spoken English: 1 to 3 short sentences, no lists, no markdown, no emojis, "
    "no stage directions, never start with your name. Be warm, curious and a bit witty. Bring something new each time "
    "instead of agreeing: an idea, a twist, a question, a friendly disagreement. Talk to Aria and Lala by name now "
    "and then. You know nothing about Lala beyond what is said here; don't pretend to. You have no tools.")

MODE_GUIDE = {
    "ideas": "This is a brainstorm: offer concrete, specific ideas and build on or challenge the others' ideas.",
    "fun": "This is just for fun: banter, play with the topic, tease Aria a little, keep it light.",
}


def next_chat_in(rand) -> float:
    """Seconds until they chat by themselves again (`rand` gives 0…1)."""
    low, high = CHAT_GAP_MIN
    return 60 * (low + (high - low) * rand())


def random_topic(rand, recent=()) -> str:
    """A topic for a chat of their own, not one of the last few (`rand` gives 0…1)."""
    fresh = [t for t in TOPICS if t not in recent] or TOPICS
    return fresh[min(len(fresh) - 1, int(rand() * len(fresh)))]


def wanted(text: str) -> bool:
    return bool(START_RE.search(text or ""))


def mode(text: str) -> str:
    return "ideas" if IDEAS_RE.search(text or "") else "fun"


def topic(text: str) -> str:
    """What they'll talk about: what comes after "about …", or the whole message."""
    m = TOPIC_RE.search(text or "")
    return (m.group(1) if m else (text or "")).strip().rstrip(".?!") or "anything"


def wants_stop(text: str) -> bool:
    return bool(STOP_RE.match(text or ""))


def transcript(lines) -> str:
    return "\n".join(f"{who}: {said}" for who, said in lines)


def claude_prompt(subject: str, how: str, lines) -> str:
    """Everything Claude is sent: the topic, the mode and this conversation's lines. Nothing else."""
    so_far = transcript(lines) if lines else "(nobody has spoken yet: you start)"
    return (f"Topic: {subject}\n{MODE_GUIDE[how]}\n\nConversation so far:\n{so_far}\n\n"
            "Write only your next line.")


def aria_prompt(subject: str, how: str, lines) -> str:
    return (f"You're in a spoken three-way chat with Lala and Claude (a bigger AI from Anthropic, a friend of yours, "
            f"appearing next to you on the screen). Topic: {subject}. {MODE_GUIDE[how]}\n\n"
            f"Conversation so far:\n{transcript(lines)}\n\n"
            "Write only your next line: 1 to 3 short spoken sentences, in your own playful voice. React to what Claude "
            "just said (agree, disagree, joke, add an idea), and sometimes ask Lala or Claude something. No lists, no "
            "name at the start.")


def summary_prompt(subject: str, lines) -> str:
    return (f"You, Lala and Claude just brainstormed about {subject}:\n{transcript(lines)}\n\n"
            "Sum up the best 2 or 3 ideas for Lala in one or two short spoken sentences. No lists.")


def clean_line(text: str):
    """A spoken line: no "Claude:" prefix, no markdown, at most a few sentences. None when nothing is left."""
    text = SPEAKER_RE.sub("", (text or "").strip().strip('"'))
    text = re.sub(r"[*_`#>]+", "", text)
    text = " ".join(text.split())
    if not text or text.startswith("Error:"):
        return None
    sentences = re.split(r"(?<=[.!?])\s+", text)[:LINE_SENTENCES]
    text = " ".join(sentences)
    if len(text) > LINE_CHARS:
        text = text[:LINE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text
