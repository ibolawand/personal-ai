# Test countdown: design

Date: 2026-11-12. Status: approved in conversation, waiting for spec review.

## Why

Lala studies alone from typed MyNotion notes and has rarely reached for Aria while doing so, because her study
features had to be asked for by phrase. The study buttons (2026-11-10) fixed that for the open note. This is the
next step agreed then: Aria already knows from WebUntis when a test is coming, and already has a quiz, so she
should put the two together at the moment it matters.

Success: in the week before a test, opening MyNotion's Aria panel shows that test, and one click starts a quiz on
the right notes that begins with what Lala got wrong before.

What Lala decided:

- A WebUntis subject belongs to one MyNotion notebook. Aria asks once per subject and remembers.
- It shows in two places: a card in MyNotion's Aria panel, and a sentence in the morning briefing.
- The quiz asks earlier mistakes from that notebook first, then new questions from the matching notes.

Assumption (not verified, it needs Lala's WebUntis login): tests always carry a subject code and only sometimes a
topic text. Without a topic the quiz draws from the whole notebook.

Not in scope: voice or text phrases for this ("quiz me for the DBI test"), a tag on matching notes, study
schedules, spaced repetition, tests further away than 7 days, pictures in notes, any new tool for the local model.
Aria still never speaks up or pops up on her own.

## What the user sees

**In the panel.** When the panel opens and a test is at most 7 days away, a card sits above the study buttons, one
per test, nearest first, at most 3:

    DBI test on Tuesday · in 5 days
    Databases · 3 notes                      [Quiz me]

- "today" and "tomorrow" replace "in 0 days" / "in 1 day". A test stays on its card for the whole day it is on.
- The topic text from WebUntis, when there is one, is the second line's start: "Normalformen · Databases · 3 notes".
- **Unmapped subject:** instead of the second line and the button, the card asks "Which notebook is DBI?" with a
  dropdown of the notebooks. Picking one saves it and the card turns into the normal one.
- **Nothing to quiz on** (the notebook has no note with enough text): the second line is "Databases · no notes
  with enough text yet" and there is no button.
- While a quiz runs, the cards are hidden, as the study buttons are replaced by Hint · Skip · Stop today.
- No test in range, WebUntis not set up or not reachable: no card and no message.

**Quiz me on a card** runs a quiz of up to 8 questions, answered by typing like today's:

    Quiz for your DBI test, 8 questions: 3 you missed before, then 5 new ones. Say skip if you don't know, or
    stop to end. First one: …

**In the morning briefing.** After the existing sentence about tests in the next 7 days, one more for the nearest
test whose subject is mapped and has notes: "I can quiz you on your Databases notes." Nothing is added otherwise.

## Parts

### `Untis.upcoming_tests(days=7)` (`Engines/Untis.py`)

Returns a list of dicts from the exam data that `_exams()` already fetches and caches, nearest first:

    {"id": "20261117-DBI-0800", "subject": "DBI", "kind": "Test", "date": date(2026, 11, 17), "topic": "Normalformen"}

- `id` is built in code from date, subject and start time, so it doesn't depend on WebUntis having an id field.
- Only tests from today up to `days` ahead.
- Unlike the speaking methods it does not go through `_safely`: it raises, and the caller decides. No login saved
  → empty list.

### `NotionEngine.notebooks()` and `.notebook_notes(folder_id)` (`Engines/NotionEngine.py`)

Aria had no way to list notebooks. `notebooks()` returns the top-level folders by name; `notebook_notes(id)`
returns the notes in that folder and in its sections. Both read only.

### `Engines/TestPrep.py` (new)

`TestPrep(untis, notion, quiz, today=dt.date.today)` owns every decision; the local model is not involved.

- **The map.** `~/.cache/aria/test_prep.json` holds `{"subjects": {"DBI": 12}}` (subject → top-level folder id).
  `notebook_for(subject)` returns the mapped notebook if it still exists; otherwise the top-level notebook whose
  name equals the subject, ignoring case; otherwise `None`. A map entry whose folder is gone counts as no entry.
  `set_notebook(subject, folder_id)` checks the folder is a top-level notebook of this user and writes the file.
- **A notebook's notes** are the notes in that folder and in its sections (folders whose `parentID` is the
  notebook), read as text with `html_to_text`. Notes with fewer than 25 words are left out (the quiz's own
  minimum).
- **Picking notes for a test.** With a topic: the notes whose title or text contain every word of the topic that
  is longer than 2 letters, ignoring case. With no topic, or no note matching: all of the notebook's notes.
- **`cards()`** → one dict per test from `upcoming_tests()`, at most 3:
  `{"id", "subject", "kind", "date" (ISO), "when" ("today" | "tomorrow" | weekday name), "days", "topic",
  "headline" (the card's first line, worded here: "DBI test on Tuesday · in 5 days"),
  "notebook": {"id", "name"} | None, "notes": <count of picked notes>}`. Any error from WebUntis → `[]`, logged
  with `Diagnostics.problem("test_prep", type name)` and never with the error text (it could hold the login).
- **`notebooks()`** → `[{"id", "name"}]`, top-level folders by name, for the dropdown.
- **`start_quiz(test_id)`** → the quiz's opening text.
  1. Find the card again from fresh data. Gone → "That test isn't coming up any more." Unmapped → "Tell me which
     notebook belongs to {subject} first." No notes → "Your {notebook} notes don't have enough in them to quiz
     you on yet."
  2. Old questions: saved misses whose `source` is the title of a note in this notebook, newest first, at most 4.
  3. New questions: 8 minus the old ones. Up to 3 of the picked notes, chosen at random, share them as evenly as
     possible (5 over 3 notes → 2, 2, 1).
  4. Hand both to `Quiz.start_mixed`.
- **`briefing_line()`** → the sentence above, or `""`; never raises.

### `Quiz.start_mixed(title, old, sources)` (`Engines/Quiz.py`)

One new entry point next to `start_on`. `old` is a list of `{"q", "a", "source"}`; `sources` is a list of
`(note title, text, how many)`.

- For each source it uses the existing `pick_chunk` and `make_questions` (so question writing still goes to
  Claude when the big model is on, with the note text only, as today). Each new question is tagged with its
  note's title as `source`.
- A source that yields no questions is skipped. No old and no new questions at all → "I couldn't come up with
  questions for that, try again in a moment."
- The quiz runs through the existing `answer` / hint / skip / stop code. Two things change there, both driven by
  a `source` on the question:
  - a missed question is saved under its own `source` instead of the quiz title, so next time it counts as a
    mistake from that notebook;
  - an old question answered right is dropped from the misses, as "quiz me on my mistakes" does today.
  Questions without a `source` (every existing quiz) behave exactly as before.
- The opening line names the split only when there are old questions; with none it is "Quiz for your DBI test,
  8 questions. …".

### Wiring in `main.py`

- `self.test_prep = self._try("Test prep", lambda: TestPrep(self.untis, self.notion, self.quiz))`, only when
  WebUntis, MyNotion and the quiz exist.
- `_briefing_extras` adds `test_prep.briefing_line()` after the WebUntis line.
- `study_app(action, on_text, test=None)`: the new action `"test"` ends a running quiz like the other buttons,
  calls `test_prep.start_quiz(test)` under the turn lock, saves the turn as "Quiz me for my {subject} test" and
  returns `(reply, ["start_quiz"], None)`. It does not need an open note.
- Two functions for the bridge: `_app_tests()` (cards and notebooks) and `_app_map(subject, notebook)`.

## Protocol (`ui/app_bridge.py`)

    MyNotion → Aria   {"id": "20", "type": "tests"}
                      {"id": "21", "type": "tests", "map": {"subject": "DBI", "notebook": 12}}
    Aria → MyNotion   {"id": "20", "type": "tests", "cards": [ … ], "notebooks": [{"id": 12, "name": "Databases"}]}

    MyNotion → Aria   {"id": "22", "type": "study", "action": "test", "test": "20261117-DBI-0800"}
    Aria → MyNotion   "text" … "done", exactly as for the other study actions ("quiz": true)

- `tests` with `map` saves first and answers with the refreshed cards. A `map` that isn't a subject string (at
  most 40 characters) and an integer → `error` "That wasn't a valid notebook choice."; a notebook that doesn't
  exist → `error` "I couldn't find that notebook."
- `tests` is read-only apart from the map file and doesn't take the turn lock. The panel has one connection and
  Aria answers its requests in order, so a `tests` request sent while she is answering a message waits for that
  answer. MyNotion gives up after 8 seconds and keeps the cards it had. Aria not started with test prep →
  `{"cards": [], "notebooks": []}`.
- `STUDY_ACTIONS` gains `"test"`; it needs `test` as a string of at most 60 characters, else `error` "I don't
  know which test you mean."
- An older MyNotion never sends these; an older Aria answers `tests` with the existing "I don't know that kind of
  request." error, which the panel treats as "no cards".

## MyNotion side (`../../MyNotion`)

- `note/src/aria.ts`: `tests()`, `mapTest(subject, notebook)` and the `test` id on the study request, with the
  matching IPC channels to the frontend.
- `note-frontend/src/app/aria-panel/`: asks for the cards when the panel opens and after a quiz ends; draws the
  cards, the dropdown and the button with the existing dark/green tokens; a failed or slow request leaves the
  panel as it is today.
- MyNotion is on the branch `bookshelf-home` with its own work in progress. The plan starts from whatever branch
  Lala says, and touches only these files.

## Privacy

The test list, the map and the choice of notes stay on the laptop. The only thing that leaves it is what leaves
it today for any quiz: the text of the chosen note, sent to Claude to write questions when the big model is on.
`aria-big-model-task` rules are unchanged; no new task kind is added.

## Tests

Fast, with a fake Untis and the `notion` fixture, no network or model:

- `tests/test_untis.py`: `upcoming_tests` range, order, ids, no login.
- `tests/test_testprep.py` (new): mapped / name-matched / unmapped subject; deleted notebook; notes in sections
  counted; topic picks matching notes; no topic or no match → whole notebook; short notes left out; `cards()`
  wording of `when` and `days`; WebUntis raising → `[]` and nothing of the error text logged; `start_quiz`
  answers for gone, unmapped and empty; at most 4 old questions, newest first, 8 in total; the split over notes.
- `tests/test_quiz.py`: `start_mixed` order (old first), misses saved under the note's title, an old question
  answered right is dropped, existing quizzes unchanged.
- `tests/test_app_bridge.py`: `tests`, `tests` with a good and a bad `map`, `study` with `action: "test"` and
  with a missing id.
- `tests/test_study.py`: `study_app("test", …)` ends a running quiz and works with no note open.
- Briefing: the extra sentence appears only for a mapped subject with notes.
- MyNotion: `aria.test.ts` for the two requests; `aria-panel.spec.ts` for the card, the dropdown, the button and
  the hidden state during a quiz.

No tool, tool description, routing rule or system prompt changes, so the real-model checks are not affected.
`FEATURES.md` gets a "Test countdown" entry under School and under the MyNotion panel.
