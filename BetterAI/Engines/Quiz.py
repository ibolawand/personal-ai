"""
"Quiz me on my C# note" / "quiz me on the gear trains PDF" / "quiz me on my mistakes".

The source is a MyNotion note or a document from Lala's folders (the content index). The model writes short-answer
questions from a part of it; everything after that is handled in code: each reply is an
answer, unless it's "skip", "I don't know", "repeat", "hint" or "stop". Answers are checked in code first (the
expected words are in it) and only otherwise by the model, which is told the answer was heard by speech
recognition. Missed questions are kept (~/.cache/aria/quiz.json) for "quiz me on my mistakes".
"""

import json
import os
import random
import re
import time

import ollama

from llm_engine import FINAL_PREFIX, KEEP_ALIVE, LLM_MODEL_DEFAULT, chat_options

STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "quiz.json")
CHUNK_CHARS = 5000           # how much of the source one quiz is made from (fits the model's context)
KEEP_MISSES = 60
MISTAKES_RE = re.compile(r"\b(mistakes?|wrong|missed|got wrong|errors?)\b", re.I)
FILE_HINT_RE = re.compile(r"\b(pdf|file|document|doc|slides?|script|worksheet|pptx|docx)\b", re.I)

STOP_RE = re.compile(r"^\s*(?:ok(?:ay)?,?\s*)?(?:stop|end|quit|cancel|enough|that'?s enough|i'?m done|let'?s stop|"
                     r"no more|finish)(?: (?:the )?quiz| it| now| for now| here)?\s*[.!]?\s*$|"
                     r"\b(?:stop|end|quit|cancel) (?:the )?quiz\b", re.I)
SKIP_RE = re.compile(r"^\s*(?:skip|pass|next(?: one| question)?|i (?:don'?t|do not) know|no idea|dunno|idk|"
                     r"no clue|i forgot|tell me|what is it|give up|i give up)\b", re.I)
REPEAT_RE = re.compile(r"^\s*(?:repeat|again|say (?:it|that) again|what was the question|what\??|huh\??|pardon|"
                       r"come again|sorry\??)\s*[?.!]*\s*$", re.I)
HINT_RE = re.compile(r"^\s*(?:(?:give me |can i (?:get|have) )?a? ?hint|help me|clue)\b", re.I)

STOPWORDS = {"the", "a", "an", "of", "to", "in", "is", "it", "and", "or", "for", "on", "by", "with", "that", "its",
             "it's", "are", "be", "as", "at", "this", "from"}


def speakable(answer: str) -> bool:
    """An answer you can say out loud: mostly words, not symbols or code ("?.Invoke", "(object sender, EventArgs e)")."""
    a = answer.strip().rstrip(".")
    return 0 < len(a.split()) <= 6 and not re.search(r"[?(){}<>=;:\[\]/\\|&*^%$@!]|\.\w|^[^\w]", a)


def _words(text):
    return [w for w in re.findall(r"[a-z0-9#+]+", (text or "").lower()) if w not in STOPWORDS]


def quick_check(expected: str, given: str):
    """True when every important word of the expected answer is in what they said, else None (ask the model)."""
    need = set(_words(expected))
    got = set(_words(given))
    if need and need <= got:
        return True
    return None


class Quiz:
    def __init__(self, notion=None, files=None, model=LLM_MODEL_DEFAULT):
        self.notion = notion
        self.files = files
        self.model = model
        self.active = None       # {"title", "questions": [{"q","a"}], "i", "right", "missed": [...], "hinted"}

    # ── persistence of missed questions ──

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_misses(self, title, missed):
        data = self._load()
        misses = [m for m in data.get("misses", []) if m["q"] not in {x["q"] for x in missed}]
        misses += [{"q": m["q"], "a": m["a"], "source": title, "at": time.time()} for m in missed]
        data["misses"] = misses[-KEEP_MISSES:]
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _drop_misses(self, questions):
        data = self._load()
        qs = {q["q"] for q in questions}
        data["misses"] = [m for m in data.get("misses", []) if m["q"] not in qs]
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ── finding the material ──

    def _from_notes(self, topic, strict):
        if not self.notion:
            return None
        from Engines.NotionEngine import _match_score, html_to_text
        notes = self.notion._notes()
        best, score = None, 0
        for n in notes:
            s = _match_score(topic, n["title"])
            if s > score:
                best, score = n, s
        if best and score >= (60 if strict else 30):
            return best["title"], html_to_text(best["content"] or "")
        if strict:
            return None
        words = [w for w in _words(topic) if len(w) > 2]
        hits = []
        for n in notes:
            text = html_to_text(n["content"] or "")
            low = text.lower()
            s = sum(low.count(w) for w in words)
            if s and all(w in low for w in words):
                hits.append((s, n["title"], text))
        if hits:
            _, title, text = max(hits)
            return title, text
        return None

    def _from_files(self, topic):
        if not self.files:
            return None
        query = FILE_HINT_RE.sub(" ", topic)
        result = self.files.search_contents(query)
        paths = getattr(self.files, "last_results", []) or []
        if not paths or result.startswith(("No ", "What ")):
            return None
        p = paths[0]
        try:
            text = self.files._extract(p)
        except Exception as e:
            print(f"[Quiz] couldn't read {p}: {e}")
            return None
        return p.stem.replace("_", " "), text

    def find_source(self, topic):
        topic = (topic or "").strip()
        if FILE_HINT_RE.search(topic):
            return self._from_files(topic) or self._from_notes(topic, strict=False)
        return self._from_notes(topic, strict=True) or self._from_files(topic) or self._from_notes(topic, strict=False)

    @staticmethod
    def pick_chunk(text, size=CHUNK_CHARS):
        """A random part of a long text, starting at a paragraph, so repeated quizzes cover different parts."""
        text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
        if len(text) <= size:
            return text
        starts = [0] + [m.end() for m in re.finditer(r"\n\s*\n", text) if m.end() < len(text) - size // 2]
        start = random.choice(starts)
        return text[start:start + size]

    # ── the model's parts ──

    def make_questions(self, title, text, count):
        want = count + 3            # some get filtered out below
        prompt = f"""Write {want} quiz questions to help a student revise their notes titled "{title}".
Rules:
- Only ask about things that are actually in the text below. Cover different parts of it.
- Short-answer questions that can be answered aloud in a few words: a term, a name, a number, a short phrase.
  Best are "What is the name for…", "What does … do?", "How many…", "What is the difference…" in one phrase.
  No yes/no questions, no "which of these", no code, no symbols, operators or signatures as answers.
- The answer is 1 to 5 plain words, taken from the text.
- Each question has exactly ONE clear right answer. Ask for a specific fact, name, term or number, not
  "what is X used for" or "what is X" (too open). Good: "Which built-in delegate returns a bool?"
  Bad: "What is a delegate?"
- Questions must make sense on their own when heard (no "in the text", no "according to the passage").

Text:
\"\"\"
{text}
\"\"\"

Reply ONLY with JSON: {{"questions": [{{"q": "question?", "a": "short answer"}}]}}"""
        try:
            resp = ollama.chat(model=self.model, think=False, format="json", options=chat_options(temperature=0.4), keep_alive=KEEP_ALIVE,
                               messages=[{"role": "user", "content": prompt}])
            data = json.loads(resp["message"]["content"])
        except Exception as e:
            print(f"[Quiz] question writing failed: {e}")
            return []
        out = []
        for item in data.get("questions", []):
            q, a = str(item.get("q", "")).strip(), str(item.get("a", "")).strip()
            if q and a and speakable(a) and q.lower() not in {x["q"].lower() for x in out}:
                out.append({"q": q if q.endswith("?") else q.rstrip(".") + "?", "a": a})
        return out[:count]

    def judge(self, question, expected, given):
        """(correct, short note). Checked in code when the expected words were said, else by the model."""
        if quick_check(expected, given):
            return True, ""
        prompt = f"""A student answered a revision question out loud; their answer was written down by speech
recognition, so ignore small mishearings and spelling.
Question: {question}
Correct answer: {expected}
Student said: {given}
Is the student's answer essentially correct (same meaning, a synonym, or more detail is fine; vague or a different
thing is not)? Reply ONLY with JSON: {{"correct": true or false}}"""
        try:
            resp = ollama.chat(model=self.model, think=False, format="json", options=chat_options(temperature=0), keep_alive=KEEP_ALIVE,
                               messages=[{"role": "user", "content": prompt}])
            return bool(json.loads(resp["message"]["content"]).get("correct")), ""
        except Exception as e:
            print(f"[Quiz] judging failed: {e}")
            return False, ""

    # ── tool ──

    def start(self, topic: str = "", count=5):
        try:
            count = max(1, min(10, int(float(count or 5))))
        except (TypeError, ValueError):
            count = 5
        topic = (topic or "").strip()
        if MISTAKES_RE.search(topic) or not topic and self._load().get("misses"):
            misses = self._load().get("misses", [])
            if not misses:
                return "You haven't missed anything yet, there's nothing to retry."
            picked = random.sample(misses, min(count, len(misses)))
            return self._begin("your mistakes", [{"q": m["q"], "a": m["a"]} for m in picked], retry=True)
        if not topic:
            return "What should I quiz you on? A note or a document."
        source = self.find_source(topic)
        if not source:
            return f"I couldn't find a note or document about '{topic}'."
        title, text = source
        return self.start_on(title, text, count)

    def start_on(self, title: str, text: str, count=5):
        """A quiz on this text (MyNotion's "Quiz me" button gives the open note; no searching)."""
        try:
            count = max(1, min(10, int(float(count or 5))))
        except (TypeError, ValueError):
            count = 5
        chunk = self.pick_chunk(text)
        if len(chunk.split()) < 25:
            return f"'{title}' doesn't have enough in it to quiz you on yet."
        questions = self.make_questions(title, chunk, count)
        if not questions:
            return f"I couldn't come up with questions from '{title}', try again in a moment."
        return self._begin(title, questions)

    def _begin(self, title, questions, retry=False):
        self.active = {"title": title, "questions": questions, "i": 0, "right": 0, "missed": [], "hinted": False,
                       "retry": retry, "fixed": []}
        n = len(questions)
        intro = (f"Okay, {n} question{'s' if n != 1 else ''} from your mistakes. " if retry else
                 f"Quiz on {title}, {n} question{'s' if n != 1 else ''}. Say skip if you don't know, or stop to end. ")
        return FINAL_PREFIX + intro + f"First one: {questions[0]['q']}"

    # ── answers, handled in code ──

    def _current(self):
        a = self.active
        return a["questions"][a["i"]] if a and a["i"] < len(a["questions"]) else None

    def answer(self, text: str):
        """Lala's reply during a quiz. Returns what to say (never None while a quiz is running)."""
        cur = self._current()
        if not cur:
            self.active = None
            return None
        if STOP_RE.search(text):
            return self._finish(stopped=True)
        if REPEAT_RE.search(text):
            return cur["q"]
        if HINT_RE.search(text):
            self.active["hinted"] = True
            a = cur["a"]
            first = a.split()[0]
            hint = (f"It starts with '{first[0].upper()}', {len(a.split())} word{'s' if len(a.split()) > 1 else ''}."
                    if len(first) > 1 else f"It's {len(a.split())} words.")
            return f"{hint} {cur['q']}"
        if SKIP_RE.search(text):
            self.active["missed"].append(cur)
            said = random.choice(["No worries, it's {}.", "It's {}.", "The answer is {}."]).format(cur["a"])
        else:
            correct, _ = self.judge(cur["q"], cur["a"], text)
            if correct:
                self.active["right"] += 1
                if self.active["retry"]:
                    self.active["fixed"].append(cur)
                said = random.choice(["Yes!", "Correct.", "Exactly.", "That's it.", "Nice, right."])
                if not quick_check(cur["a"], text):
                    said += f" ({cur['a']})"
            else:
                self.active["missed"].append(cur)
                said = random.choice(["Not quite, it's {}.", "Close, but it's {}.", "No, it's {}."]).format(cur["a"])
        self.active["i"] += 1
        self.active["hinted"] = False
        nxt = self._current()
        if nxt:
            lead = "Last one" if self.active["i"] == len(self.active["questions"]) - 1 else "Next"
            return f"{said} {lead}: {nxt['q']}"
        return f"{said} {self._finish()}"

    def stop(self):
        """End a running quiz the way "stop" does (missed questions are kept); returns what to say, or None."""
        return self._finish(stopped=True) if self.active else None

    def _finish(self, stopped=False):
        a, self.active = self.active, None
        asked = a["i"]
        if a["fixed"]:
            self._drop_misses(a["fixed"])
        if a["missed"]:
            self._save_misses(a["title"], a["missed"])
        if asked == 0:
            return "Okay, quiz stopped."
        score = f"You got {a['right']} out of {asked}."
        if a["right"] == asked:
            tail = " Perfect!" if asked >= 3 else ""
        elif a["missed"]:
            tail = " Say 'quiz me on my mistakes' to try the ones you missed again."
        else:
            tail = ""
        return ("Okay, stopping there. " if stopped else "That's the end. ") + score + tail
