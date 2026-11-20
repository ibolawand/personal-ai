# Test countdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the week before a WebUntis test, MyNotion's Aria panel shows a card for it and one click starts a quiz on the matching notebook's notes, earlier mistakes first; the morning briefing offers the same.

**Architecture:** A new `Engines/TestPrep.py` decides everything in code (which tests are close, which notebook, which notes, which questions). `Untis`, `NotionEngine` and `Quiz` each get a small public method it builds on. The panel reaches it through two new requests on the existing app socket (`ui/app_bridge.py`), mirrored in MyNotion's `note/src/aria.ts` and `aria-panel`.

**Tech Stack:** Python 3 + pytest (Aria). TypeScript: Electron main process + vitest (`MyNotion/note`), Angular 20 + Karma (`MyNotion/note-frontend`).

**Spec:** `docs/superpowers/specs/2026-11-12-test-countdown-design.md`

## Global Constraints

- Paths are relative to `BetterAI/` unless they start with `../../MyNotion/`. The git root of Aria is the parent `personal-ai/`; MyNotion is its own repository.
- Python runs through `.venv/bin/python`. Tests need no model, mic, camera or network and must not open the real `aria_memory.db` or MyNotion's DB (`tests/conftest.py` enforces this).
- No new tool, tool description, routing rule or system-prompt change. The local model takes no part in any decision here.
- Nothing speaks up or pops up on its own: the feature only shows in the panel when it is opened and in the morning briefing.
- WebUntis error text is never logged or spoken (it can hold the login). Log the exception's type name only.
- Numbers from the spec: tests up to **7** days ahead, at most **3** cards, quiz of **8** questions, at most **4** old mistakes, new questions from at most **3** notes, a note needs at least **25** words.
- The map file is `test_prep.json` in `$XDG_CACHE_HOME/aria/` (default `~/.cache/aria/`).
- **Commits:** this project commits only when Lala says so. Do not commit after a task; leave the work in the tree and report. MyNotion is on branch `bookshelf-home` with uncommitted work: before Task 7 ask Lala which branch to work on, and touch only the files Tasks 7 and 8 name.
- Copy (user-visible strings) is given verbatim in the tasks. Use it exactly.

## Review Focus

Conditions the spec implies but doesn't spell out, most likely first. Each has a test in the task named.

1. Two tests of the same subject inside the week (even on the same day) → two cards with different ids, and Quiz me on one starts that one. (Task 1)
2. A WebUntis exam with an empty subject → left out, no card, no crash. (Task 1)
3. A topic made only of short words or signs ("SA 2", "§ 3") → treated as no topic: the whole notebook is used. (Task 4)
4. `test_prep.json` missing, not JSON, or not writable → the map counts as empty, `set_notebook` returns `False`, cards still come back. (Task 4)
5. New MyNotion talking to an Aria that is busy or older (no answer in time, or an `error` answer to `tests`) → the panel keeps the cards it had and shows nothing new; no blank or broken panel. (Tasks 7, 8)

---

### Task 1: `Untis.upcoming_tests`

**Files:**
- Modify: `Engines/Untis.py` (next to `school_exams`, ~line 284)
- Test: `tests/test_untis.py`

**Interfaces:**
- Produces: `Untis.upcoming_tests(days: int = 7) -> list[dict]`, nearest first, each
  `{"id": str, "subject": str, "kind": str, "date": datetime.date, "topic": str}`.
  `id` is `f"{examDate}-{subject}-{startTime:04d}"` (start time 0 when missing). `kind` is `examType`, else `name`, else `"Test"`. `topic` is the stripped `text`, else `""`. Raises whatever `_exams()` raises; returns `[]` when no login is saved.

- [ ] **Step 1: Write the failing tests** using the existing `make` fixture and `FakeUntis` (`MON` is 2026-11-09):

```python
def exam(date, su, start=800, text="", kind="Test"):
    return {"examType": kind, "name": "", "examDate": date, "startTime": start, "endTime": start + 50,
            "subject": su, "text": text}

def test_upcoming_tests_are_plain_records_nearest_first(make):
    u = make(FakeUntis(exams=[exam(20261116, "E"), exam(20261112, "DBI", text=" Normalformen "),
                              exam(20261117, "AM")]))          # 17th is 8 days away
    assert u.upcoming_tests() == [
        {"id": "20261112-DBI-0800", "subject": "DBI", "kind": "Test", "date": dt.date(2026, 11, 12), "topic": "Normalformen"},
        {"id": "20261116-E-0800", "subject": "E", "kind": "Test", "date": dt.date(2026, 11, 16), "topic": ""}]
    assert [t["subject"] for t in u.upcoming_tests(days=10)] == ["DBI", "E", "AM"]

def test_two_tests_of_one_subject_get_their_own_ids(make):
    u = make(FakeUntis(exams=[exam(20261112, "DBI", 800), exam(20261112, "DBI", 1000)]))
    assert [t["id"] for t in u.upcoming_tests()] == ["20261112-DBI-0800", "20261112-DBI-1000"]

def test_a_test_without_a_subject_is_left_out_and_today_counts(make):
    u = make(FakeUntis(exams=[exam(20261109, ""), exam(20261109, "E", kind="")]))
    assert [(t["subject"], t["kind"]) for t in u.upcoming_tests()] == [("E", "Test")]

def test_upcoming_tests_without_a_login(make, monkeypatch):
    monkeypatch.setattr(U, "load_login", lambda: None)
    assert make(FakeUntis(exams=[exam(20261112, "DBI")])).upcoming_tests() == []
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_untis.py -k "upcoming or own_ids or without_a_subject"`. Expected: FAIL, `Untis` has no `upcoming_tests`.
- [ ] **Step 3: Implement `upcoming_tests`** from `self._exams()`. Do not wrap it in `_safely`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_untis.py`. Expected: all pass.

---

### Task 2: Notebooks in `NotionEngine`

**Files:**
- Modify: `Engines/NotionEngine.py` (after `_notes`, ~line 328)
- Test: `tests/test_notion.py`

**Interfaces:**
- Produces:
  - `NotionEngine.notebooks() -> list[dict]`: this user's top-level folders (`parentID` NULL or 0) as `{"id": int, "name": str}`, sorted by name ignoring case.
  - `NotionEngine.notebook_notes(folder_id: int) -> list[dict]`: the user's `notes` rows (as dicts, like `_notes()`) whose `folderID` is `folder_id` or a folder whose `parentID` is `folder_id`; newest `updated_at` first. Unknown folder → `[]`.

- [ ] **Step 1: Write the failing test.** Folders are inserted straight into the fixture DB:

```python
def test_notebooks_and_their_notes(notion):
    with notion._conn() as c:
        uid = notion.user_id
        c.execute("INSERT INTO FOLDERS (id, name, userID) VALUES (1, 'databases', ?)", (uid,))
        c.execute("INSERT INTO FOLDERS (id, name, userID) VALUES (2, 'Analysis', ?)", (uid,))
        c.execute("INSERT INTO FOLDERS (id, name, parentID, userID) VALUES (3, 'SQL', 1, ?)", (uid,))
        c.execute("INSERT INTO FOLDERS (id, name, userID) VALUES (4, 'Not mine', ?)", (uid + 1,))
    a, b, loose = (notion._create_note(t, "<p>x</p>") for t in ("Normal forms", "Joins", "Loose"))
    with notion._conn() as c:
        c.execute("UPDATE notes SET folderID = 1 WHERE id = ?", (a,))
        c.execute("UPDATE notes SET folderID = 3 WHERE id = ?", (b,))
    assert notion.notebooks() == [{"id": 2, "name": "Analysis"}, {"id": 1, "name": "databases"}]
    assert sorted(n["title"] for n in notion.notebook_notes(1)) == ["Joins", "Normal forms"]
    assert notion.notebook_notes(2) == [] and notion.notebook_notes(99) == []
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_notion.py -k notebooks_and_their_notes`. Expected: FAIL, no `notebooks`.
- [ ] **Step 3: Implement both methods** with `self._conn()` and `self.user_id`, like `_notes`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_notion.py`. Expected: all pass.

---

### Task 3: `Quiz.start_mixed`

**Files:**
- Modify: `Engines/Quiz.py` (`_save_misses` ~75, `_begin` ~264, `answer` ~300, new method after `start_on`)
- Test: `tests/test_quiz.py`

**Interfaces:**
- Produces: `Quiz.start_mixed(title: str, old: list[dict], sources: list[tuple[str, str, int]]) -> str`.
  - `old`: questions `{"q", "a", "source"}` asked first, in the order given.
  - `sources`: `(note title, note text, how many new questions)`; for each, `pick_chunk` then `make_questions(note title, chunk, how many)`; every new question gets `"source": note title`. A new question whose `q` equals an old one's is dropped. A source that yields nothing is skipped.
  - Returns `FINAL_PREFIX` + the opening line (copy below) + `f"First one: {q}"`, or, with no question at all, exactly `"I couldn't come up with questions for that, try again in a moment."` (no prefix, no quiz started).
- Opening line, `n` = total, `k` = old, `m` = new:
  - `k > 0` and `m > 0`: `f"Quiz for your {title}, {n} questions: {k} you missed before, then {m} new one{'s' if m != 1 else ''}. Say skip if you don't know, or stop to end. "`
  - otherwise: `f"Quiz for your {title}, {n} question{'s' if n != 1 else ''}. Say skip if you don't know, or stop to end. "`
- Behaviour change in the running quiz, driven only by keys on the question, so existing quizzes are untouched:
  - a missed question is saved with `source = question["source"]` when it has one, else the quiz title (today's behaviour);
  - a question with `"old": True` answered right is dropped from the saved misses (the same path `retry` quizzes use, `active["fixed"]`).

- [ ] **Step 1: Write the failing tests** with the existing `quiz` fixture (its fake model returns the 3 `QUESTIONS` for any "quiz questions" prompt and judges by `quick_check`; read the fixture before writing the answers):

```python
OLD = [{"q": "What is a primary key?", "a": "a unique identifier", "source": "Keys"}]

def state():
    return json.load(open(Q.STATE_FILE)).get("misses", [])

def test_mixed_asks_old_questions_first_and_says_the_split(quiz):
    said = quiz.start_mixed("DBI test", OLD, [("Databases", html_to_text(NOTE), 2)])
    assert said.startswith(Q.FINAL_PREFIX + "Quiz for your DBI test, ")
    assert "1 you missed before, then " in said and said.endswith("First one: What is a primary key?")
    assert [q.get("source") for q in quiz.active["questions"]][:2] == ["Keys", "Databases"]

def test_mixed_without_old_questions_has_the_plain_opening(quiz):
    said = quiz.start_mixed("DBI test", [], [("Databases", html_to_text(NOTE), 3)])
    assert "Quiz for your DBI test, 3 questions. Say skip" in said and "missed before" not in said

def test_mixed_saves_a_miss_under_its_note_and_drops_a_fixed_old_one(quiz):
    quiz._save_misses("Keys", OLD)
    quiz.start_mixed("DBI test", OLD, [("Databases", html_to_text(NOTE), 1)])
    quiz.answer("a unique identifier")          # the old one, right
    quiz.answer("skip")                         # the new one, missed
    assert [(m["q"], m["source"]) for m in state()] == [(QUESTIONS[0]["q"], "Databases")]

def test_mixed_drops_a_new_question_that_repeats_an_old_one(quiz):
    old = [dict(QUESTIONS[0], source="Databases")]
    quiz.start_mixed("DBI test", old, [("Databases", html_to_text(NOTE), 3)])
    assert [q["q"] for q in quiz.active["questions"]].count(QUESTIONS[0]["q"]) == 1

def test_mixed_with_nothing_to_ask(quiz):
    assert quiz.start_mixed("DBI test", [], []) == "I couldn't come up with questions for that, try again in a moment."
    assert quiz.active is None

def test_an_ordinary_quiz_still_saves_misses_under_its_title(quiz):
    quiz.start("databases")
    quiz.answer("skip"); quiz.answer("stop")
    assert state()[0]["source"] == "Databases"
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_quiz.py -k "mixed or ordinary"`. Expected: the `mixed` tests FAIL (no `start_mixed`); the last one passes already and must keep passing.
- [ ] **Step 3: Implement.** Mark old questions with `"old": True` when the quiz begins. Give `_begin` an optional opening-line argument rather than a second copy of it.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_quiz.py tests/test_study.py`. Expected: all pass.

---

### Task 4: `Engines/TestPrep.py`

**Files:**
- Create: `Engines/TestPrep.py`
- Test: `tests/test_testprep.py` (new)

**Interfaces:**
- Consumes: `Untis.upcoming_tests(days)` (Task 1); `NotionEngine.notebooks()`, `.notebook_notes(id)` (Task 2); `Quiz.start_mixed(title, old, sources)` and `Quiz._load()["misses"]` (Task 3); `html_to_text` from `Engines.NotionEngine`; `Engines.Diagnostics.problem`.
- Produces:
  - Module constants: `STATE_FILE` (built like `Quiz.STATE_FILE`, file name `test_prep.json`), `DAYS = 7`, `MAX_CARDS = 3`, `QUIZ_SIZE = 8`, `MAX_OLD = 4`, `MAX_NOTES = 3`, `MIN_WORDS = 25`.
  - `TestPrep(untis, notion, quiz, today=dt.date.today, rng=random)`
  - `notebook_for(subject: str) -> dict | None`: `{"id", "name"}`. Mapped folder if it is still in `notion.notebooks()`; else the notebook whose name equals the subject ignoring case; else `None`.
  - `set_notebook(subject: str, folder_id: int) -> bool`: `False` (nothing written) when `folder_id` is not in `notion.notebooks()` or the file can't be written.
  - `notebooks() -> list[dict]`: `notion.notebooks()`.
  - `cards() -> list[dict]`: at most `MAX_CARDS`, nearest first, each `{"id", "subject", "kind", "date": "YYYY-MM-DD", "when", "days": int, "topic", "headline", "notebook": {"id","name"} | None, "notes": int}`. `notes` is the number of picked notes (0 when unmapped). Any exception from `untis` → `[]` after `Diagnostics.problem("test_prep", type(e).__name__)`.
  - `start_quiz(test_id: str) -> tuple[str, str]`: `(what to say, subject)`; subject is `""` when the test is gone.
  - `briefing_line() -> str`: never raises.
- Wording, decided here so Python tests pin it:
  - `label` = `f"{subject} test"` when `kind` is `"Test"`, else `f"{subject} {kind}"`.
  - `when` = `"today"` (0 days), `"tomorrow"` (1), else the English weekday name (`"Tuesday"`).
  - `headline` = `f"{label} today"`, `f"{label} tomorrow"`, else `f"{label} on {when} · in {days} days"`.
  - `start_quiz` refusals: `"That test isn't coming up any more."`; `f"Tell me which notebook belongs to {subject} first."`; `f"Your {notebook name} notes don't have enough in them to quiz you on yet."`
  - `briefing_line`: for the nearest card with a notebook and `notes > 0`, `f"I can quiz you on your {notebook name} notes."`; otherwise `""`.
- Rules:
  - A notebook's usable notes: `notion.notebook_notes(id)`, text via `html_to_text(content or "")`, kept when it has at least `MIN_WORDS` words. A note's title is its `title` or `"Untitled note"`.
  - Picking: topic words are the topic's alphanumeric words longer than 2 characters, lower-cased. With at least one topic word, keep the notes whose title + text contain all of them (case-insensitive substring). No topic words, or no note kept → all usable notes.
  - Old questions: saved misses whose `source` is the title of **any** note in the notebook (not only the picked ones), newest `at` first, at most `MAX_OLD`.
  - New questions: `QUIZ_SIZE - len(old)`, over `min(MAX_NOTES, len(picked))` notes chosen with `rng.sample`, split as evenly as possible with the earlier notes getting the extra (5 over 3 → 2, 2, 1; 8 over 1 → 8). `Quiz.make_questions` caps one call at 10, which 8 never reaches.
  - Quiz title passed to `start_mixed` is `label`.

- [ ] **Step 1: Write the failing tests.** Use the `notion` fixture, a stub for WebUntis and a recording stub for the quiz:

```python
"""Test countdown: which tests are close, which notebook and notes belong to them, and the quiz it starts."""
import datetime as dt
import json
import random

import pytest

import Engines.TestPrep as T
import main  # noqa: F401  (imported at collection, before the subprocess guard is in place)

TODAY = dt.date(2026, 11, 12)                       # a Thursday
LONG = "<p>" + "Third normal form removes transitive dependencies between columns. " * 6 + "</p>"

class Untis:
    def __init__(self, tests=(), error=None): self.tests, self.error = list(tests), error
    def upcoming_tests(self, days=7):
        if self.error: raise self.error
        return self.tests

class Quiz:
    def __init__(self, misses=()): self.misses, self.started = list(misses), None
    def _load(self): return {"misses": self.misses}
    def start_mixed(self, title, old, sources):
        self.started = (title, old, sources)
        return "started"

def coming(subject="DBI", days=5, topic="", kind="Test", start="0800"):
    d = TODAY + dt.timedelta(days=days)
    return {"id": f"{d:%Y%m%d}-{subject}-{start}", "subject": subject, "kind": kind, "date": d, "topic": topic}

@pytest.fixture
def book(notion):
    """book(name, {title: html}, section={title: html}) → folder id"""
    def make(name, notes, section=None):
        with notion._conn() as c:
            fid = c.execute("INSERT INTO FOLDERS (name, userID) VALUES (?, ?)", (name, notion.user_id)).lastrowid
            sid = c.execute("INSERT INTO FOLDERS (name, parentID, userID) VALUES ('Part', ?, ?)",
                            (fid, notion.user_id)).lastrowid
        for where, group in ((fid, notes), (sid, section or {})):
            for title, html in group.items():
                nid = notion._create_note(title, html)
                with notion._conn() as c:
                    c.execute("UPDATE notes SET folderID = ? WHERE id = ?", (where, nid))
        return fid
    return make

@pytest.fixture
def prep(notion, monkeypatch, tmp_path):
    monkeypatch.setattr(T, "STATE_FILE", str(tmp_path / "test_prep.json"))
    def make(tests=(), misses=(), error=None):
        p = T.TestPrep(Untis(tests, error), notion, Quiz(misses), today=lambda: TODAY, rng=random.Random(1))
        return p
    return make
```

Tests (one behaviour each; names are the requirement):

```python
def test_card_for_a_mapped_subject(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": LONG}, section={"Keys": LONG})
    p = prep([coming()])
    assert p.set_notebook("DBI", fid) is True
    assert p.cards() == [{"id": "20261117-DBI-0800", "subject": "DBI", "kind": "Test", "date": "2026-11-17",
                          "when": "Tuesday", "days": 5, "topic": "", "headline": "DBI test on Tuesday · in 5 days",
                          "notebook": {"id": fid, "name": "Databases"}, "notes": 3}]

def test_headlines_for_today_tomorrow_and_other_kinds(prep):
    p = prep([coming(days=0), coming("AM", 1, kind="Schularbeit"), coming("E", 3)])
    assert [c["headline"] for c in p.cards()] == ["DBI test today", "AM Schularbeit tomorrow", "E test on Sunday · in 3 days"]
    assert [c["when"] for c in p.cards()] == ["today", "tomorrow", "Sunday"]

def test_at_most_three_cards(prep):
    assert len(prep([coming(s, i) for i, s in enumerate("ABCDE")]).cards()) == 3

def test_a_notebook_named_like_the_subject_needs_no_asking(prep, book):
    fid = book("dbi", {"Normal forms": LONG})
    assert prep([coming()]).cards()[0]["notebook"] == {"id": fid, "name": "dbi"}

def test_unmapped_subject_and_a_deleted_notebook(prep, book, notion):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()])
    assert p.cards()[0]["notebook"] is None and p.cards()[0]["notes"] == 0
    p.set_notebook("DBI", fid)
    with notion._conn() as c:
        c.execute("DELETE FROM FOLDERS WHERE id = ?", (fid,))
    assert p.cards()[0]["notebook"] is None
    assert p.set_notebook("DBI", 999) is False

def test_a_renamed_notebook_keeps_its_subject(prep, book, notion):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()]); p.set_notebook("DBI", fid)
    with notion._conn() as c:
        c.execute("UPDATE FOLDERS SET name = 'DB systems' WHERE id = ?", (fid,))
    assert p.cards()[0]["notebook"]["name"] == "DB systems"

def test_the_topic_picks_the_matching_notes(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": "<p>" + "A join combines rows of two tables. " * 8 + "</p>"})
    p = prep([coming(topic="Transitive dependencies")]); p.set_notebook("DBI", fid)
    assert p.cards()[0]["notes"] == 1

@pytest.mark.parametrize("topic", ["", "SA 2", "§ 3", "Quantum chromodynamics"])
def test_no_usable_topic_or_no_match_means_the_whole_notebook(prep, book, topic):
    fid = book("Databases", {"Normal forms": LONG, "Joins": LONG})
    p = prep([coming(topic=topic)]); p.set_notebook("DBI", fid)
    assert p.cards()[0]["notes"] == 2

def test_short_notes_do_not_count(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Stub": "<p>todo</p>"})
    p = prep([coming()]); p.set_notebook("DBI", fid)
    assert p.cards()[0]["notes"] == 1

def test_webuntis_failing_gives_no_cards_and_logs_no_details(prep, monkeypatch):
    seen = []
    monkeypatch.setattr(T.Diagnostics, "problem", lambda kind, detail: seen.append((kind, detail)))
    p = prep(error=RuntimeError("login s3cret-pw refused"))
    assert p.cards() == [] and p.briefing_line() == ""
    assert seen == [("test_prep", "RuntimeError")] * len(seen) and seen

@pytest.mark.parametrize("content", [None, "{not json", '["a list"]'])
def test_a_missing_or_broken_map_file_counts_as_empty(prep, book, content, tmp_path):
    if content is not None:
        (tmp_path / "test_prep.json").write_text(content)
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()])
    assert p.cards()[0]["notebook"] is None
    assert p.set_notebook("DBI", fid) is True and p.cards()[0]["notebook"]["id"] == fid

def test_a_map_file_that_cannot_be_written(prep, book, monkeypatch, tmp_path):
    fid = book("Databases", {"Normal forms": LONG})
    (tmp_path / "a_file").write_text("x")
    monkeypatch.setattr(T, "STATE_FILE", str(tmp_path / "a_file" / "test_prep.json"))   # a folder can't be made there
    p = prep([coming()])
    assert p.set_notebook("DBI", fid) is False and len(p.cards()) == 1

def test_start_quiz_asks_mistakes_first_then_new_ones(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": LONG, "Keys": LONG, "Views": LONG})
    misses = [{"q": f"q{i}", "a": "a", "source": "Keys", "at": i} for i in range(6)]
    misses.append({"q": "other", "a": "a", "source": "Gear trains", "at": 99})
    p = prep([coming()], misses); p.set_notebook("DBI", fid)
    assert p.start_quiz("20261117-DBI-0800") == ("started", "DBI")
    title, old, sources = p.quiz.started
    assert title == "DBI test"
    assert [m["q"] for m in old] == ["q5", "q4", "q3", "q2"]
    assert [n for _, _, n in sources] == [2, 1, 1] and len({t for t, _, _ in sources}) == 3
    assert all(len(text.split()) >= 25 for _, text, _ in sources)

def test_start_quiz_with_one_note_and_no_mistakes(prep, book):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming()]); p.set_notebook("DBI", fid)
    p.start_quiz("20261117-DBI-0800")
    assert p.quiz.started[1] == [] and [(t, n) for t, _, n in p.quiz.started[2]] == [("Normal forms", 8)]

def test_start_quiz_picks_the_right_one_of_two_tests_of_a_subject(prep, book):
    fid = book("Databases", {"Normal forms": LONG, "Joins": "<p>" + "A join combines rows of two tables. " * 8 + "</p>"})
    p = prep([coming(start="0800", topic="join"), coming(start="1000", topic="transitive")]); p.set_notebook("DBI", fid)
    p.start_quiz("20261117-DBI-1000")
    assert [t for t, _, _ in p.quiz.started[2]] == ["Normal forms"]

def test_start_quiz_says_why_not(prep, book):
    fid = book("Databases", {"Stub": "<p>todo</p>"})
    p = prep([coming()])
    assert p.start_quiz("20261101-DBI-0800") == ("That test isn't coming up any more.", "")
    assert p.start_quiz("20261117-DBI-0800") == ("Tell me which notebook belongs to DBI first.", "DBI")
    p.set_notebook("DBI", fid)
    assert p.start_quiz("20261117-DBI-0800") == ("Your Databases notes don't have enough in them to quiz you on yet.", "DBI")
    assert p.quiz.started is None

def test_briefing_offers_the_nearest_test_that_can_be_quizzed(prep, book):
    fid = book("Databases", {"Normal forms": LONG})
    p = prep([coming("AM", 1), coming("DBI", 5)])
    assert p.briefing_line() == ""
    p.set_notebook("DBI", fid)
    assert p.briefing_line() == "I can quiz you on your Databases notes."
```

In the fixture, expose the quiz stub as `p.quiz` (the constructor stores it under that name).

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_testprep.py`. Expected: FAIL at import, no `Engines.TestPrep`.
- [ ] **Step 3: Implement `Engines/TestPrep.py`** to the Interfaces block. Import `Diagnostics` as `from Engines import Diagnostics` so the test can patch `T.Diagnostics.problem`. Guard the map file with a `threading.Lock` (the panel's socket thread and the main loop both use it) and create its folder on write, as `Quiz._save_misses` does.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_testprep.py`. Expected: all pass.

---

### Task 5: The two requests in `ui/app_bridge.py`

**Files:**
- Modify: `ui/app_bridge.py` (docstring, `STUDY_ACTIONS`, `_handle`, `_handle_study`, `_serve`, `start`)
- Test: `tests/test_app_bridge.py`

**Interfaces:**
- Produces:
  - `start(answer, path=SOCKET_PATH, edit=None, study=None, quiz_active=None, tests=None)`.
  - `tests(mapping) -> dict`: called with `None`, or `(subject: str, notebook: int)` to save first. Returns `{"cards": [...], "notebooks": [...]}`. Raises `LookupError` when the notebook doesn't exist.
  - `study` is now called as `study(action, on_text)` for `quiz|explain|prep` (unchanged) and as `study("test", on_text, test=<id>)` for the new action.
- Wire format (also goes into the module docstring):

      MyNotion → Aria   {"id": "20", "type": "tests"}
                        {"id": "21", "type": "tests", "map": {"subject": "DBI", "notebook": 12}}
      Aria → MyNotion   {"id": "20", "type": "tests", "cards": [...], "notebooks": [{"id": 12, "name": "Databases"}]}
      MyNotion → Aria   {"id": "22", "type": "study", "action": "test", "test": "20261117-DBI-0800"}

- Rules and copy:
  - `tests` is `None` at `start` → answer `{"cards": [], "notebooks": []}`.
  - `map` present but not a dict with `subject` a non-empty string of at most 40 characters and `notebook` an `int` (a `bool` is not accepted) → `error` `"That wasn't a valid notebook choice."`
  - `LookupError` → `error` `"I couldn't find that notebook."`; any other exception → `error` `SORRY`, logged by type name only.
  - `action == "test"` without `test` being a non-empty string of at most 60 characters → `error` `"I don't know which test you mean."`
  - Requests on one connection are still answered in order: a `tests` request sent while a turn is being answered waits for it. That is accepted; MyNotion handles the wait (Task 7).

- [ ] **Step 1: Write the failing tests.** Add a `serve_tests` fixture like the existing `serve` one that takes `(answer, study=None, tests=None)`; use the file's `client`, `ask` and `read_events` helpers:

```python
CARDS = {"cards": [{"id": "20261117-DBI-0800", "subject": "DBI"}], "notebooks": [{"id": 12, "name": "Databases"}]}

def test_tests_request_returns_cards_and_notebooks(serve_tests):
    seen = []
    sock = serve_tests(hi_there, tests=lambda m: seen.append(m) or CARDS)
    assert ask(sock, {"id": "1", "type": "tests"}) == [{"id": "1", "type": "tests", **CARDS}]
    assert ask(sock, {"id": "2", "type": "tests", "map": {"subject": "DBI", "notebook": 12}})[0]["cards"] == CARDS["cards"]
    assert seen == [None, ("DBI", 12)]

def test_tests_request_without_test_prep_is_empty(serve_tests):
    assert ask(serve_tests(hi_there), {"id": "1", "type": "tests"}) == [{"id": "1", "type": "tests", "cards": [], "notebooks": []}]

@pytest.mark.parametrize("bad", [{}, "DBI", {"subject": "", "notebook": 1}, {"subject": "DBI", "notebook": "1"},
                                 {"subject": "DBI", "notebook": True}, {"subject": "x" * 41, "notebook": 1}])
def test_a_bad_map_is_refused_and_nothing_is_saved(serve_tests, bad):
    seen = []
    sock = serve_tests(hi_there, tests=lambda m: seen.append(m) or CARDS)
    assert ask(sock, {"id": "1", "type": "tests", "map": bad}) == [
        {"id": "1", "type": "error", "message": "That wasn't a valid notebook choice."}]
    assert seen == []

def test_an_unknown_notebook_and_a_crash(serve_tests):
    def gone(m): raise LookupError()
    def boom(m): raise RuntimeError("login s3cret-pw")
    assert ask(serve_tests(hi_there, tests=gone), {"id": "1", "type": "tests", "map": {"subject": "DBI", "notebook": 9}}) == [
        {"id": "1", "type": "error", "message": "I couldn't find that notebook."}]
    assert ask(serve_tests(hi_there, tests=boom), {"id": "1", "type": "tests"}) == [
        {"id": "1", "type": "error", "message": app_bridge.SORRY}]

def test_study_test_passes_the_id_and_answers_like_chat(serve_tests):
    seen = []
    def study(action, on_text, test=None):
        seen.append((action, test)); return "Quiz for your DBI test…", ["start_quiz"], None
    sock = serve_tests(hi_there, study=study)
    events = ask(sock, {"id": "1", "type": "study", "action": "test", "test": "20261117-DBI-0800"})
    assert events[-1]["type"] == "done" and events[-1]["reply"] == "Quiz for your DBI test…"
    assert seen == [("test", "20261117-DBI-0800")]

@pytest.mark.parametrize("test_id", [None, "", 7, "x" * 61])
def test_study_test_needs_an_id(serve_tests, test_id):
    sock = serve_tests(hi_there, study=lambda *a, **k: ("x", [], None))
    assert ask(sock, {"id": "1", "type": "study", "action": "test", "test": test_id}) == [
        {"id": "1", "type": "error", "message": "I don't know which test you mean."}]

def test_the_old_study_actions_are_still_called_without_a_test(serve_tests):
    seen = []
    sock = serve_tests(hi_there, study=lambda action, on_text: seen.append(action) or ("ok", [], None))
    ask(sock, {"id": "1", "type": "study", "action": "explain"})
    assert seen == ["explain"]
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_app_bridge.py -k "tests_request or bad_map or unknown_notebook or study_test or old_study"`. Expected: FAIL (`start` takes no `tests`).
- [ ] **Step 3: Implement**, with a `_handle_tests(rid, req, tests, send)` next to `_handle_study`, and update the module docstring with the wire format above.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_app_bridge.py`. Expected: all pass.

---

### Task 6: Wiring in `main.py`

**Files:**
- Modify: `main.py` (`Aria.__init__` after `self.untis`, ~514; `study_app` ~921; `_app_study` ~1017; `_start_app_bridge` ~1050; `_briefing_extras` ~1487)
- Test: `tests/test_study.py`, `tests/test_untis.py`

**Interfaces:**
- Consumes: `TestPrep` (Task 4); `app_bridge.start(..., tests=)` and the `study(action, on_text, test=None)` call shape (Task 5).
- Produces:
  - `self.test_prep`: built with `self._try("Test prep", ...)` only when `self.untis`, `self.notion` and `self.quiz` all exist; otherwise `None`.
  - `Aria.study_app(action, on_text=None, test=None)`; `Aria._app_study(action, on_text, test=None)`.
  - `Aria._app_tests(mapping=None) -> dict`: without test prep `{"cards": [], "notebooks": []}`; with a mapping, `set_notebook` first and `raise LookupError` when it returns `False`.
- `study_app("test", ...)`:
  - comes after the dictation check and **before** the open-note checks (no note needs to be open);
  - no `test_prep` → `("I can't help with tests right now.", [], None)`;
  - under the turn lock: stop a running quiz, `reply, subject = self.test_prep.start_quiz(test)`, strip `FINAL_PREFIX`, and when a quiz is now active save the turn and append to `_recent` with the user text `f"Quiz me for my {subject} test"` (as the `"quiz"` branch does with "Quiz me on this note");
  - returns `(reply, ["start_quiz"], None)` when a quiz started, `(reply, [], None)` otherwise.
- `_briefing_extras`: append `self.test_prep.briefing_line()` after the WebUntis line, inside the same kind of `try`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_study.py`, a stub keeps these about the wiring only:

```python
class Prep:
    def __init__(self, quiz, reply=("Quiz for your DBI test, 2 questions. First one: Q?", "DBI"), start=True):
        self.quiz, self.reply, self.start, self.asked = quiz, reply, start, []
    def start_quiz(self, test_id):
        self.asked.append(test_id)
        if self.start:
            self.quiz._begin("DBI test", [dict(q) for q in QUESTIONS])
            return main.FINAL_PREFIX + self.reply[0], self.reply[1]
        return self.reply

def test_test_quiz_needs_no_open_note_and_is_kept_in_the_conversation(aria, study_quiz):
    aria.test_prep = Prep(study_quiz)
    reply, tools, confirm = aria.study_app("test", test="20261117-DBI-0800")
    assert reply == "Quiz for your DBI test, 2 questions. First one: Q?" and tools == ["start_quiz"] and confirm is None
    assert aria.test_prep.asked == ["20261117-DBI-0800"] and study_quiz.active
    assert aria._recent[-1][0] == {"role": "user", "content": "Quiz me for my DBI test"}

def test_test_quiz_that_cannot_start_claims_no_tool(aria, study_quiz):
    aria.test_prep = Prep(study_quiz, reply=("That test isn't coming up any more.", ""), start=False)
    before = len(aria._recent)
    assert aria.study_app("test", test="gone") == ("That test isn't coming up any more.", [], None)
    assert len(aria._recent) == before

def test_test_quiz_ends_a_running_quiz_first(aria, open_note, study_quiz):
    open_note("Databases", NOTE)
    aria.study_app("quiz")
    aria.test_prep = Prep(study_quiz)
    aria.study_app("test", test="20261117-DBI-0800")
    assert study_quiz.active["title"] == "DBI test"

def test_test_quiz_without_test_prep(aria):
    aria.test_prep = None
    assert aria.study_app("test", test="x") == ("I can't help with tests right now.", [], None)

def test_app_tests_and_mapping(aria):
    aria.test_prep = None
    assert aria._app_tests() == {"cards": [], "notebooks": []}
    class P:
        def cards(self): return [{"id": "c"}]
        def notebooks(self): return [{"id": 1, "name": "Databases"}]
        def set_notebook(self, subject, fid): return fid == 1
    aria.test_prep = P()
    assert aria._app_tests(("DBI", 1)) == {"cards": [{"id": "c"}], "notebooks": [{"id": 1, "name": "Databases"}]}
    with pytest.raises(LookupError):
        aria._app_tests(("DBI", 2))
```

The `aria` fixture builds `Aria` with `__new__`, so every new attribute must be read with `getattr(self, "test_prep", None)`.

In `tests/test_untis.py`, next to `test_the_morning_briefing_includes_school`, following its setup:

```python
def test_the_morning_briefing_offers_a_quiz(aria):
    class P:
        def briefing_line(self): return "I can quiz you on your Databases notes."
    aria.test_prep = P()
    assert "I can quiz you on your Databases notes." in aria._briefing_extras()
    def broken(): raise RuntimeError("x")
    aria.test_prep.briefing_line = broken
    aria._briefing_extras()                       # never raises
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_study.py tests/test_untis.py -k "test_quiz or app_tests or offers_a_quiz"`. Expected: FAIL.
- [ ] **Step 3: Implement**, and pass `tests=self._app_tests` to `app_bridge.start`.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest`. Expected: the whole fast suite passes.

---

### Task 7: MyNotion main process: `tests`, `mapTest`, study with a test

Ask Lala which MyNotion branch to work on before starting (see Global Constraints).

**Files:**
- Modify: `../../MyNotion/note/src/aria.ts` (header comment, types ~22–35, `AriaLink` ~69–190, `setUpAria` ~226)
- Modify: `../../MyNotion/note/src/preload.ts` (~35–50)
- Modify: `../../MyNotion/note-frontend/src/services/NoteService.ts` (types ~13–19, `electronAPI.aria` ~89–97)
- Test: `../../MyNotion/note/src/aria.test.ts`

**Interfaces:**
- Consumes: the wire format of Task 5.
- Produces (identical type declarations in `aria.ts` and `NoteService.ts`):

```ts
export type StudyAction = 'quiz' | 'explain' | 'prep' | 'test';
export type TestCard = { id: string; subject: string; headline: string; topic: string; days: number;
                         notebook: { id: number; name: string } | null; notes: number };
export type Notebook = { id: number; name: string };
export type TestCards = { ok: boolean; cards: TestCard[]; notebooks: Notebook[] };
export const TESTS_TIMEOUT_MS = 8000;
```

  - `AriaLink.tests(map?: { subject: string; notebook: number }): Promise<TestCards>`
  - `AriaLink.study(action: StudyAction, test?: string): Promise<AskResult>`; `test` is sent only for `'test'`.
  - IPC: `'aria:tests'` `(map?)` → `TestCards`; `'aria:study'` `(action, test?)`. `'test'` without a string `test` resolves `{ ok: false, error: 'not-running' }` like an unknown action does today.
  - Preload: `aria.tests(map?)`, `aria.study(action, test?)`.
- Rules:
  - `ok` is `true` only when a `tests` answer arrived. Not connected, write failed, an `error` answer, the connection dropping, or no answer within `TESTS_TIMEOUT_MS` → `{ ok: false, cards: [], notebooks: [] }`. (A turn being answered delays `tests`; the timeout is how that shows.)
  - Pending `tests` requests are tracked apart from `open` (chat) and `waiting` (status), so an in-flight `tests` request doesn't make `status()` report `'running'` early and its `error` isn't emitted as a chat event.
  - Incoming cards are filtered: keep entries whose `id`, `subject` and `headline` are strings; `topic` defaults to `''`, `days` and `notes` to `0`, `notebook` to `null` unless it has a numeric `id` and a string `name`. Notebooks likewise.

- [ ] **Step 1: Write the failing tests** in `aria.test.ts`, with the fake-server helpers the existing study tests use (see `'sends the selection and relays her proposal'`):
  - `tests() sends {"type":"tests"} and resolves the cards`: server answers `{id, type:'tests', cards:[{id:'20261117-DBI-0800', subject:'DBI', headline:'DBI test on Tuesday · in 5 days', notebook:{id:12,name:'Databases'}, notes:3}, {id: 7}], notebooks:[{id:12,name:'Databases'},{name:'x'}]}` → result is `ok: true`, one card with `topic: ''` and `days: 0`, one notebook.
  - `tests(map) sends the map`: the written line has `map: {subject:'DBI', notebook:12}`.
  - `an error answer to tests resolves ok:false and emits no event`.
  - `tests gives up after TESTS_TIMEOUT_MS` (fake timers) → `ok: false`.
  - `tests resolves ok:false when Aria isn't running` and `when the connection drops`.
  - `a waiting tests request doesn't make status() skip its own request`.
  - `study('test', id) sends the test id`; `study('quiz') sends no test`.
- [ ] **Step 2: Run** `cd ../../MyNotion/note && npx vitest run src/aria.test.ts`. Expected: the new tests fail.
- [ ] **Step 3: Implement** in `aria.ts`, `preload.ts` and the types in `NoteService.ts`; update the header comment of `aria.ts` with the new lines of the protocol.
- [ ] **Step 4: Run** `npx vitest run` and `npx tsc --noEmit -p .` in `note/`. Expected: all pass, no type errors.

---

### Task 8: MyNotion panel: the cards

**Files:**
- Modify: `../../MyNotion/note-frontend/src/app/aria-panel/aria-chat.ts`
- Modify: `../../MyNotion/note-frontend/src/app/aria-panel/aria-panel.ts`, `aria-panel.html`, `aria-panel.css`
- Test: `../../MyNotion/note-frontend/src/app/aria-panel/aria-panel.spec.ts`

**Interfaces:**
- Consumes: `window.electronAPI.aria.tests(map?)`, `.study(action, test?)`, `TestCard`, `Notebook` (Task 7).
- Produces, on `AriaChat` (state lives there so it survives closing the panel):
  - `tests: TestCard[] = []`, `notebooks: Notebook[] = []`
  - `loadTests(): Promise<void>`: on `ok: true` replaces both lists; on `ok: false`, a missing API or a thrown error leaves them as they are.
  - `mapTest(subject: string, notebook: number): Promise<void>`: same, with the map.
  - `studyTest(card: TestCard): Promise<boolean>`: like `study`, shows the user message `` `Quiz me for my ${card.subject} test` ``; the message remembers `test: card.id` so **Retry** sends the same test again (`PanelMessage` gets `test?: string`; `STUDY_LABELS` gets `test: 'Quiz me'` to stay total).
  - `loadTests()` is called by the panel in `ngOnInit` after `checkRunning()`, and by `AriaChat` whenever a `done` event turns `quizActive` from `true` to `false`.
- What the panel draws, in the footer above the study buttons, when `running !== false`, no quiz is active and there are cards. It does **not** depend on a note being open. One block per card, `class="test-card"`:
  - line 1: `card.headline`
  - mapped with notes: line 2 is `[topic, notebook.name, notesLabel].filter(Boolean).join(' · ')` where `notesLabel` is `'1 note'` or `` `${n} notes` ``, and a button **Quiz me** (`title="8 questions, your earlier mistakes first"`, disabled while `busy`).
  - mapped, `notes === 0`: line 2 is `` `${notebook.name} · no notes with enough text yet` ``, no button.
  - unmapped: a `<label>` `` `Which notebook is ${card.subject}?` `` with a `<select>` whose first option is `Choose…` (no value) followed by `chat.notebooks`; choosing one calls `mapTest(card.subject, id)`. No notebooks at all → line 2 is `Make a notebook for it first.` and no select.
- Style: use the panel's existing CSS variables and the look of `.study` buttons (dark/green). No new colours.

- [ ] **Step 1: Write the failing tests** in a `describe('test cards', …)` block. Add `tests: async (map?: unknown) => { mapped.push(map); return nextTests; }` and extend the fake `study` to record its second argument. Cases:
  - `shows a card with headline, notebook line and Quiz me, with no note open`: one mapped card with `topic: 'Normalformen'`, 3 notes → text contains `DBI test on Tuesday · in 5 days` and `Normalformen · Databases · 3 notes`.
  - `says "1 note" for one note`.
  - `Quiz me on a card sends study('test', id) and shows "Quiz me for my DBI test"`.
  - `an unmapped card asks which notebook and saves the choice`: select the notebook → `mapped` ends with `{subject: 'DBI', notebook: 12}`, and the card redraws from the answer.
  - `an unmapped card with no notebooks says to make one`.
  - `a card with no usable notes has no button`.
  - `cards are hidden while a quiz runs and reloaded when it ends` (a `done` with `quiz: true`, then one with `quiz: false` → `tests` called again).
  - `a failed load keeps the cards that were there` (`ok: false` after a good load).
  - `no cards and no error when tests() is missing or throws` (older preload).
  - `retry resends the same test`.
- [ ] **Step 2: Run** the panel spec the way the study-buttons plan did (`cd ../../MyNotion/note-frontend && npx ng test --watch=false --include src/app/aria-panel/aria-panel.spec.ts`). Expected: the new tests fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx ng test --watch=false` in `note-frontend/`. Expected: all pass. The bookshelf specs are Lala's work in progress: if one of those fails without these changes too, report it and leave it.

---

### Task 9: Documentation and the real thing

**Files:**
- Modify: `FEATURES.md` ("School" section ~481 and the MyNotion panel's study buttons ~564)
- Modify: `CLAUDE.md` (the MyNotion's-Aria-panel paragraph: one sentence naming `Engines/TestPrep.py` and the `tests` request)

- [ ] **Step 1: Write the `FEATURES.md` entries**: what shows on a card, the three card states, the quiz (8 questions, up to 4 earlier mistakes first, new ones from up to 3 matching notes), the briefing sentence, that she asks once which notebook a subject is and where that is kept (`~/.cache/aria/test_prep.json`), that nothing is sent anywhere except note text for question writing as with any quiz, and the test files.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest`. Expected: all pass.
- [ ] **Step 3: Check it for real** (needs Lala: a saved WebUntis login and a test within 7 days, or none and the panel must simply show no card). Restart Aria with the `aria-restart` skill, rebuild MyNotion, open the Aria panel and confirm: the card, the notebook question when the subject is new, Quiz me starting a quiz with Hint/Skip/Stop, and the cards coming back after Stop. Report exactly what was and wasn't seen; if no test is within 7 days, say that the card itself could not be checked live.
