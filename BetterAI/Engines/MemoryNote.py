"""
What Aria remembers about Lala — visible and editable.

Aria saves facts after conversations (database.py, `memories`). This keeps them in a MyNotion note,
"What Aria knows about me", one fact per line, in both directions:
  - new facts Aria learns are added to the note
  - delete or change a line in MyNotion and Aria forgets / uses your version; add a line and she knows it
Voice/text: "what do you know about me?", "forget that I …", "remember that I …".

Sync runs every minute and after each conversation. If both sides changed since the last sync,
your edits in the note win and Aria's new facts are added on top.
"""

import hashlib
import html
import json
import os
import re
import threading

from Engines.NotionEngine import _match_score, _norm, _stem, html_to_text

NOTE_TITLE = "What Aria knows about me"
HEADER = "Aria reads this note. Delete or change a line to correct her, or add your own. One fact per line."
STATE_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "aria", "memory_note.json")
MAX_FACTS = 200


_FILLER = {"that", "i'm", "im", "i", "am", "my", "me", "user", "user's", "users", "is", "the", "a", "an", "about",
           "was", "have", "has", "i've", "ive", "to", "of"}


def _words(text: str) -> set:
    return {w for w in _stem(_norm(text)).split() if w not in _FILLER and len(w) > 1}


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").encode()).hexdigest()


def render(facts) -> str:
    return f"<p><em>{html.escape(HEADER)}</em></p>" + "".join(f"<p>{html.escape(f)}</p>" for f in facts)


def parse(content: str) -> list:
    out = []
    for line in html_to_text(content).splitlines():
        line = line.strip().lstrip("•☐☑-* ").strip()
        if line and line != HEADER and line not in out:
            out.append(line)
    return out


class MemoryNote:
    def __init__(self, memory, notion=None, confirm=None, on_card=None):
        self.memory = memory
        self.notion = notion
        self.confirm = confirm
        self.on_card = on_card
        self.llm = None                    # set by Aria, for clean_up()
        self._lock = threading.Lock()
        self.state = self._load()

    def _load(self):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=1)
        except OSError:
            pass

    def _note(self):
        n = self.notion._find_note(NOTE_TITLE)
        return n if n and _match_score(NOTE_TITLE, n["title"]) >= 80 else None

    # ── sync ──

    def sync(self):
        if not self.notion:
            return
        with self._lock:
            try:
                self._sync()
            except Exception as e:
                print(f"[Memory] note sync failed: {e}")

    def _sync(self):
        note = self._note()
        db = self.memory.get_memories(MAX_FACTS)
        last = self.state.get("facts")
        if last is None:
            last = db                                   # first run: nothing to compare with yet
        user_changed = bool(note) and _hash(note["content"]) != self.state.get("hash")
        db_changed = set(db) != set(last)

        if user_changed:
            facts = parse(note["content"])
            if db_changed:      # Aria learned/forgot something meanwhile: apply that on top of your version
                facts += [f for f in db if f not in last and f not in facts]
                facts = [f for f in facts if not (f in last and f not in db)]
            self._set_db(facts, db)
            if db_changed:
                self._write(note, facts)
            else:
                self.state["hash"] = _hash(note["content"])
            self.state["facts"] = facts
            print(f"[Memory] took your edits from the note ({len(facts)} facts)")
        elif db_changed or not note:
            self._write(note, db)
            self.state["facts"] = db
        self._save()

    def _set_db(self, facts, db):
        for f in db:
            if f not in facts:
                self.memory.forget(f)
        for f in facts:
            if f not in db:
                self.memory.save_memory(f)

    def _write(self, note, facts):
        content = render(facts)
        if note:
            self.notion._set_content(note["id"], content)
        else:
            self.notion._create_note(NOTE_TITLE, content)
        self.state["hash"] = _hash(content)

    # ── tools ──

    def what_you_know(self):
        self.sync()
        facts = self.memory.get_memories(40)
        if not facts:
            return "I haven't saved anything about you yet."
        if self.on_card and self.notion:
            note = self._note()
            self.on_card({"type": "list", "note_id": note["id"] if note else 0, "title": NOTE_TITLE,
                          "items": [{"text": f, "checked": None} for f in facts]})
        where = " They're in the note 'What Aria knows about me' in MyNotion, where Lala can edit them." if self.notion else ""
        return (f"Saved facts about Lala ({len(facts)}): " + "; ".join(facts) + "." + where +
                " Summarise them briefly in your own words.")

    def remember(self, fact: str):
        fact = (fact or "").strip().rstrip(".")
        if not fact:
            return "What should I remember?"
        self.memory.save_memory(fact)
        self.sync()
        return f"Got it, I'll remember that: {fact}."

    def clean_up(self, llm=None):
        """Tool: 'clean up your memory'. Suggests what to forget; Lala confirms with yes/no."""
        llm = llm or self.llm
        facts = self.memory.get_memories(MAX_FACTS)
        if not facts or not llm:
            return "There's nothing to clean up."
        junk = [facts[i] for i in llm.find_junk_facts(facts)]
        if not junk:
            return "I went through everything I remember about you, and it all looks like real facts."
        if self.on_card and self.notion:
            note = self._note()
            self.on_card({"type": "list", "note_id": note["id"] if note else 0, "title": "I'd forget these",
                          "items": [{"text": f, "checked": None} for f in junk]})

        def do():
            for f in junk:
                self.memory.forget(f)
            self.sync()
            return f"Done, I forgot those {len(junk)}. What's left is in your note 'What Aria knows about me'."
        listing = "; ".join(f"'{f}'" for f in junk[:6]) + (f" and {len(junk) - 6} more" if len(junk) > 6 else "")
        if self.confirm:
            return self.confirm.request(f"forget {len(junk)} saved things that don't look like real facts: {listing}", do)
        return do()

    def forget(self, what: str):
        what = (what or "").strip()
        facts = self.memory.get_memories(MAX_FACTS)
        if not facts:
            return "I don't have anything saved about you."
        if re.fullmatch(r"(everything|all( of it)?|all facts|it all)", what.lower()):
            def do():
                for f in facts:
                    self.memory.forget(f)
                self.sync()
                return f"Done, I forgot all {len(facts)} things I knew about you."
            if self.confirm:
                return self.confirm.request(f"forget all {len(facts)} things I know about you", do)
            return do()
        # "forget that I'm bored" -> "User is bored": every meaningful word of the request is in the fact
        want = _words(what)
        hits = [f for f in facts if want and want <= _words(f)]
        if not hits:
            scored = sorted(((max(_match_score(what, f), _match_score(f, what)), f) for f in facts), reverse=True)
            hits = [f for s, f in scored if s >= 60] or [f for s, f in scored[:1] if s >= 30]
        if not hits:
            return f"I don't have anything saved about '{what}'. Saved: " + "; ".join(facts[:10]) + "."
        for f in hits[:3]:
            self.memory.forget(f)
        self.sync()
        return "Forgotten: " + "; ".join(hits[:3]) + "."
