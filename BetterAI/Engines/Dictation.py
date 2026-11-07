"""
Dictation: "dictate into my trip note" … talk freely … "stop dictating".

While it's on, everything Lala says (or types) is written down instead of answered: Aria stays quiet and a card next
to the orb shows the text so far. Spoken commands, each said on its own:
  stop / done / that's it / stop dictating   → clean up and save
  scratch that / delete that                 → drop the last thing said
  new paragraph                              → start a new paragraph
  read it back / what do I have so far       → read the text so far aloud
  cancel dictation / throw it away           → discard (asks first)

On save the model fixes punctuation and capitals and removes filler words and stutters; it is told not to reword or
summarise, and if its version has noticeably fewer or more words than what was said, the plain transcript is used
(only lightly tidied) so nothing Lala said goes missing. Without a note name it goes into today's note.
"""

import json
import re
import time

import ollama

from llm_engine import KEEP_ALIVE, LLM_MODEL_DEFAULT, chat_options

_ARIA = r"(?:(?:hey |ok(?:ay)? )?aria,?\s*)?"
START_RE = re.compile(
    rf"^\s*{_ARIA}(?:can you |could you |please |let'?s |i want to |i'?d like to |i'?m going to |i'?ll )?"
    r"(?:start |begin )?(?:dictat(?:e|ing|ion)|take (?:a )?dictation|(?:take|write) down (?:what i say|notes?)(?: for me)?|"
    r"write (?:down )?what i say)"
    r"(?:\s+(?:something\s+)?(?:in|into|to|for|on)\s+(?:my |the |a )?(?P<title>.+?))?\s*[.!?]*\s*$", re.I)
STOP_RE = re.compile(rf"^\s*{_ARIA}(?:ok(?:ay)?,?\s*)?(?:stop(?: dictating| dictation| writing| now)?|done|i'?m done|"
                     r"(?:that'?s|that is) (?:it|all|everything)|finish(?:ed)?|end(?: dictation)?|save it|"
                     r"stop and save|that'?s the end)\s*[.!]*\s*$", re.I)
CANCEL_RE = re.compile(rf"^\s*{_ARIA}(?:cancel(?: the)?(?: dictation)?|throw (?:it|that|everything) away|"
                       r"discard (?:it|that|everything|all)|scrap (?:it|that|everything|all)|forget it|never ?mind)"
                       r"\s*[.!]*\s*$", re.I)
SCRATCH_RE = re.compile(r"^\s*(?:scratch that|delete that|strike that|remove that|undo that|"
                        r"delete (?:the )?last (?:sentence|bit|part|line|thing))\s*[.!]*\s*$", re.I)
READ_RE = re.compile(r"^\s*(?:read (?:it|that|this|everything) back|read back|what do i have(?: so far)?|"
                     r"where was i|what did i say(?: so far)?)\s*[?.!]*\s*$", re.I)
PARA_RE = re.compile(r"\b(?:new|next) paragraph\b[.,!]?", re.I)
FILLERS_RE = re.compile(r"\b(?:um+|uh+|er+m?|ah+|hmm+|mhm)\b[,.]?\s*", re.I)

PARA = "\n\n"
CARD_CHARS = 500


def light_tidy(text: str) -> str:
    """Without the model: drop um/uh, collapse stutters ('the the'), capitalise, end with a full stop."""
    t = FILLERS_RE.sub("", text)
    t = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,")
    if not t:
        return ""
    t = t[0].upper() + t[1:]
    t = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)
    t = re.sub(r"\bi\b", "I", t)
    return t if t[-1] in ".!?:" else t + "."


def _words(text):
    return re.findall(r"[\w']+", text.lower())


class Dictation:
    def __init__(self, save, confirm=None, model=LLM_MODEL_DEFAULT, on_card=None, cleanup=None):
        """save(text, title) -> what to say; title '' means today's note. cleanup(paragraphs) -> paragraphs
        replaces the model (tests)."""
        self.save = save
        self.confirm = confirm
        self.model = model
        self.on_card = on_card or (lambda card: None)
        self.cleanup = cleanup or self._model_cleanup
        self.active = None          # {"title", "chunks": [str | PARA], "started"}

    # ── starting ──

    @staticmethod
    def wants_to_start(text: str):
        """The note title (may be '') when text asks to start dictating, else None."""
        m = START_RE.match(text or "")
        if not m:
            return None
        title = (m.group("title") or "").strip().strip(".")
        title = re.sub(r"\s+note$", "", title, flags=re.I).strip()
        if re.fullmatch(r"(?:today'?s?|daily|day|my day|it|this|here|a note|notes?|something)", title, re.I):
            title = ""
        return title

    def start(self, title: str = ""):
        self.active = {"title": title, "chunks": [], "started": time.time()}
        self._show()
        where = f"your {title} note" if title else "today's note"
        return (f"Okay, I'm writing into {where}. Go ahead. Say 'stop' when you're done, "
                f"'scratch that' to take something back.")

    # ── while dictating ──

    def _paragraphs(self, chunks=None) -> list:
        paras = [[]]
        for c in (self.active or {}).get("chunks", []) if chunks is None else chunks:
            if c != PARA:
                paras[-1].append(c)
            elif paras[-1]:
                paras.append([])
        return [" ".join(p) for p in paras if p]

    def text_so_far(self) -> str:
        return PARA.join(self._paragraphs())

    def feed(self, text: str):
        """One thing said while dictating. Returns what to say ('' = stay quiet)."""
        a = self.active
        text = (text or "").strip()
        if not a or not text:
            return ""
        if STOP_RE.match(text):
            return self.finish()
        if CANCEL_RE.match(text):
            return self._cancel()
        if SCRATCH_RE.match(text):
            while a["chunks"] and a["chunks"][-1] == PARA:
                a["chunks"].pop()
            if not a["chunks"]:
                return "There's nothing to take back yet."
            gone = a["chunks"].pop()
            self._show()
            return f"Took out: {' '.join(gone.split()[:6])}{'…' if len(gone.split()) > 6 else ''}"
        if READ_RE.match(text):
            so_far = self.text_so_far()
            return f"So far: {light_tidy(so_far)}" if so_far else "Nothing yet. Go ahead."
        # "… new paragraph …" said inside a sentence splits it there
        for i, part in enumerate(PARA_RE.split(text)):
            if i:
                a["chunks"].append(PARA)
            if part.strip(" ,."):
                a["chunks"].append(part.strip())
        self._show()
        return ""

    def _cancel(self):
        words = len(_words(self.text_so_far()))

        def do():
            self.active = None
            self.on_card({"type": "clear", "kind": "dictation"})
            return "Okay, threw it away."
        if not words:
            return do()
        if self.confirm:
            return self.confirm.request(f"throw away the {words} words you dictated", do)
        return do()

    # ── saving ──

    def finish(self):
        a, self.active = self.active, None
        self.on_card({"type": "clear", "kind": "dictation"})
        if not a:
            return ""
        raw = self._paragraphs(a["chunks"])
        if not raw:
            return "You didn't say anything, so I didn't save anything."
        said = sum(len(_words(p)) for p in raw)
        try:
            cleaned = self.cleanup(raw)
        except Exception as e:
            print(f"[Dictation] cleanup failed: {e}")
            cleaned = None
        n = sum(len(_words(p)) for p in cleaned or [])
        if not cleaned or not (0.7 * said <= n <= 1.15 * said + 2):
            if cleaned:
                print(f"[Dictation] cleanup changed too much ({said} → {n} words), keeping the transcript")
            cleaned = [light_tidy(p) for p in raw]
        cleaned = [p.strip() if p.strip()[-1] in ".!?:…\"')" else p.strip() + "." for p in cleaned if p.strip()]
        result = self.save("\n".join(cleaned), a["title"])
        words = sum(len(_words(p)) for p in cleaned)
        where = f"your {a['title']} note" if a["title"] else "today's note"
        if "couldn't" in str(result).lower() or "failed" in str(result).lower():
            return str(result)
        return f"Saved {words} word{'s' if words != 1 else ''} to {where}."

    def _model_cleanup(self, paragraphs):
        prompt = (
            "This text was dictated out loud and written down by speech recognition. Make it read like a typed note: "
            "add punctuation and capital letters, remove filler words (um, uh, like and you know used as fillers), "
            "stutters, repeated words and false starts, and fix words the speech recognition obviously got wrong. "
            "Do NOT summarise, shorten, add anything, explain, or change the wording or the order otherwise. Keep "
            "the person's own voice (\"I\", \"we\"). Keep the same number of paragraphs.\n"
            'Answer with JSON: {"paragraphs": ["…", "…"]}\n\n'
            + json.dumps({"paragraphs": paragraphs}, ensure_ascii=False))
        resp = ollama.chat(model=self.model, think=False, format="json", keep_alive=KEEP_ALIVE,
                           options=chat_options(temperature=0.1),
                           messages=[{"role": "user", "content": prompt}])
        out = json.loads(resp["message"]["content"]).get("paragraphs")
        if not isinstance(out, list) or not all(isinstance(p, str) for p in out):
            return None
        return [p.strip() for p in out]

    # ── the card next to the orb ──

    def _show(self):
        a = self.active
        if not a:
            return
        text = self.text_so_far()
        shown = ("…" + text[-CARD_CHARS:]) if len(text) > CARD_CHARS else text
        self.on_card({"type": "dictation", "title": f"Dictating · {a['title'] or 'today’s note'}",
                      "text": shown, "words": len(_words(text))})
