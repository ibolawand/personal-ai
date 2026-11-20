# Study Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three buttons in MyNotion's Aria panel (Quiz me, Explain simply, Test prep) that work on the open note, plus Hint · Skip · Stop while a quiz runs.

**Architecture:** A new `study` request on the existing panel socket (`ui/app_bridge.py`) reaches a new `Aria.study_app(action, on_text)`, which reads the open note in code. Quiz goes through a new `Quiz.start_on(title, text)`. Explain/prep is one no-tools turn through the existing `handle_turn(..., extra=..., use_tools=False)`. Every `done` gets a `quiz` flag so the panel knows when to show Hint/Skip/Stop.

**Tech Stack:** Python 3 + pytest (Aria). TypeScript: Electron main process + vitest (`MyNotion/note`), Angular 20 + Karma (`MyNotion/note-frontend`).

**Spec:** `docs/superpowers/specs/2026-11-10-study-buttons-design.md`

**Repos:** Tasks 1–3 commit in `personal-ai` (cwd `BetterAI/`). Tasks 4–5 commit in the separate MyNotion repo at `../../MyNotion` (relative to `BetterAI/`).

## Global Constraints

- Study actions: exactly `"quiz"`, `"explain"`, `"prep"`.
- Request: `{"id", "type": "study", "action"}`. Unknown action → `error` "I don't know that study action."
- Every `done` (chat and study) carries `"quiz": bool`.
- `STUDY_NOTE_CHARS = 12000` (in `main.py`, next to `OPEN_NOTE_CHARS`). A longer note is cut at a line break, and code appends `"(I only covered the first part of this note, it's long.)"` to the reply.
- No open note → `"Open a note first, then I can help you study it."` Empty note → `"This note is empty, there's nothing to study yet."`
- Explain/prep never get tools. The note text is never stored in message history or `_recent` (same rule as `answer_app`).
- Buttons are labelled `Quiz me`, `Explain simply`, `Test prep`. Quiz buttons are `Hint`, `Skip`, `Stop` and send `"hint"`, `"skip"`, `"stop"`.
- Panel styling uses MyNotion's existing dark/green tokens only (no new colours).
- Aria tests never use the model, mic, camera or network (`FakeLLM`, conftest sandbox).

## Review Focus

1. **A quiz started from the panel and then abandoned** (panel closed, user types an unrelated question): the next chat is taken as a quiz answer, which is existing quiz behaviour. The `quiz` flag in that reply's `done` must still be correct so the Hint/Skip/Stop buttons stay in sync. Test in Task 3: `test_done_reports_quiz_state_after_a_chat`.
2. **Pressing a study button while a quiz is already running**: `study_app("quiz")` must start a fresh quiz on the open note rather than treat "Quiz me on this note" as an answer. `explain`/`prep` during a quiz must not be eaten as an answer either. Test in Task 2: `test_study_buttons_are_not_taken_as_quiz_answers`.
3. **A note whose text is only whitespace or a heading** ("<h1>Title</h1>" with nothing else): explain works, quiz says it's too short (existing `start_on` message). Test in Task 2: `test_quiz_on_a_tiny_note_says_so`.
4. **A pending yes/no confirmation when a study button is pressed**: the button must not resolve or drop the confirmation by accident. `study_app` doesn't go through `confirm.resolve`. Test in Task 2: `test_study_leaves_a_pending_question_alone`.
5. **Retry on a failed study message** must resend the study action, not send the label "Quiz me" as a chat. Test in Task 5: `retry resends a failed study action`.

---

### Task 1: `Quiz.start_on`

**Files:**
- Modify: `Engines/Quiz.py` (`start`, ~lines 215–239)
- Test: `tests/test_quiz.py`

**Interfaces:**
- Produces: `Quiz.start_on(self, title: str, text: str, count=5) -> str`. It returns the same strings `start()` returns once a source is found (`FINAL_PREFIX + "Quiz on …"`, or the too-short / couldn't-make-questions messages). `count` is clamped to 1–10 like in `start`.

- [ ] **Step 1: Write the failing tests** in `tests/test_quiz.py`, using the existing `quiz` fixture:

```python
def test_start_on_uses_the_given_text_without_searching(quiz):
    out = quiz.start_on("Kapitel 3 (untitled-ish)", NOTE_TEXT, 3)   # a title the search would never match
    assert out.startswith(Q.FINAL_PREFIX + "Quiz on Kapitel 3 (untitled-ish), 3 questions.")
    assert quiz.active["title"] == "Kapitel 3 (untitled-ish)"
    assert "transitive dependencies" in quiz.calls[0]

def test_start_on_a_tiny_text_says_so(quiz):
    assert quiz.start_on("Stub", "just a heading") == "'Stub' doesn't have enough in it to quiz you on yet."
    assert quiz.active is None
```

`NOTE_TEXT` = `html_to_text(NOTE)` (import `html_to_text` from `Engines.NotionEngine`, define it at module level).

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_quiz.py -k start_on`. Expected: FAIL, `AttributeError: 'Quiz' object has no attribute 'start_on'`.

- [ ] **Step 3: Implement.** Move everything in `start()` from `chunk = self.pick_chunk(text)` to the end into `start_on`, together with the count clamping. `start()` keeps its own clamping (it's needed for the mistakes branch) and ends with `return self.start_on(title, text, count)`.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_quiz.py`. Expected: all pass, the old ones included.

- [ ] **Step 5: Commit** `Engines/Quiz.py tests/test_quiz.py`: "Quiz: start on a given text (for the panel's Quiz me button)".

---

### Task 2: `Aria.study_app`

**Files:**
- Modify: `main.py` (constant next to `OPEN_NOTE_CHARS` at line ~123; new method after `answer_app` at ~line 880)
- Create: `tests/test_study.py`

**Interfaces:**
- Consumes: `Quiz.start_on(title, text, count=5)` (Task 1); `self.notion.open_note()` → dict with `"title"`, `"content"` or None; `html_to_text`; `self.handle_turn(user_input, check_state, on_text, extra, use_tools)`; `self._turn_lock()`; `self._save_turn(user, reply)`; `self._recent`.
- Produces: `Aria.study_app(self, action: str, on_text=None) -> tuple[str, list[str], str | None]`, the same shape as `answer_app`. `action` is assumed to be valid (the bridge checks it). `Aria._app_study(self, action, on_text)` is the bridge entry point: it wraps `study_app` with `Diagnostics.problem("app_study", …)` and re-raises, like `_app_answer`.

Behaviour (the exact copy is in Global Constraints):
- Dictation running → the same refusal as `answer_app`, with `[]`, `None`.
- Under `_turn_lock()`, with the same orb save/restore as `answer_app`. Factor that into a small helper used by both if that's clean, and don't change `answer_app`'s behaviour.
- No note / empty note (`html_to_text(...).strip() == ""`) → the fixed messages, with `[]`, `None`.
- `quiz`: `self.quiz.active = None`, then `reply = self.quiz.start_on(title, text)`. Strip `FINAL_PREFIX`, `self._save_turn("Quiz me on this note", reply)`, append that pair to `_recent`, return `(reply, ["start_quiz"], None)`. If `self.quiz` is missing → "I can't run quizzes right now."
- `explain` / `prep`: `self.handle_turn(LABEL, check_state=False, on_text=on_text, extra=prompt, use_tools=False)` with
  - LABEL: `"Explain this note simply"` / `"Test prep for this note"` (this is what history keeps)
  - prompt = `\n[The note "{title}":\n{text}\n]\n` + instruction, where the instruction is
    - explain: `"Explain the main ideas of this note in plain, simple language, like to a classmate. Keep it short, use an everyday example where it helps. Don't add facts that aren't in the note."`
    - prep: `"From this note, list the 5 to 8 most important things to know for a test, one short line each. Then write 3 questions a teacher would likely ask about it. Only use what is in the note."`
  - `text` is cut to `STUDY_NOTE_CHARS` at the last `\n` before the limit; when cut, append the first-part line to the final reply (after `tidy_reply`).
- Explain/prep can't be eaten by a running quiz: set `self.quiz.active = None` before `handle_turn` (pressing a study button ends the quiz, like saying stop without the score).

- [ ] **Step 1: Write the failing tests** in `tests/test_study.py`. Copy the `open_note` fixture from `tests/test_app_bridge.py:263-273` and the `Recording` FakeLLM from `tests/test_app_bridge.py` (~line 560). Tests and their key assertions:

```python
def test_no_open_note(aria):
    assert aria.study_app("explain") == ("Open a note first, then I can help you study it.", [], None)

def test_empty_note(aria, open_note):
    open_note("Leer", "<p> </p>")
    assert aria.study_app("prep")[0] == "This note is empty, there's nothing to study yet."

def test_refused_while_dictating(aria):  # same setup as test_a_panel_message_is_not_written_into_a_dictation
    ...; assert "dictating" in aria.study_app("quiz")[0]

def test_explain_gets_the_note_and_no_tools(aria, open_note):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.llm = Recording(replies=[("They're the cell's power plants.", [])])
    reply, tools, _ = aria.study_app("explain")
    assert reply == "They're the cell's power plants." and tools == []
    assert aria.llm.offered == [[]]
    assert aria.llm.prompts[0].startswith("Explain this note simply")
    assert "Mitochondria make ATP" in aria.llm.prompts[0] and "plain, simple language" in aria.llm.prompts[0]
    assert not any("Mitochondria" in m["content"] for turn in aria._recent for m in turn)

def test_prep_uses_its_own_instruction(aria, open_note):
    ...; assert "3 questions a teacher" in aria.llm.prompts[0]

def test_a_long_note_is_cut_and_the_reply_says_so(aria, open_note):
    open_note("Lang", "".join(f"<p>Zeile {i} mit etwas Text darin</p>" for i in range(1000)))
    aria.llm = FakeLLM(replies=[("Main ideas.", [])])
    reply, _, _ = aria.study_app("explain")
    assert reply.endswith("(I only covered the first part of this note, it's long.)")
    assert "Zeile 999 " not in aria.llm.prompts[0]

def test_quiz_starts_on_the_open_note(aria, open_note):
    open_note("Kapitel 3", NOTE)   # NOTE/QUESTIONS and the fake ollama.chat: reuse tests/test_quiz.py's
    reply, tools, _ = aria.study_app("quiz")
    assert reply.startswith("Quiz on Kapitel 3") and tools == ["start_quiz"]
    assert aria.quiz.active["title"] == "Kapitel 3"
    assert aria._recent[-1][0] == {"role": "user", "content": "Quiz me on this note"}

def test_quiz_buttons_are_answered_in_code(aria, open_note):
    ...start quiz...; reply, _, _ = aria.answer_app("hint")
    assert reply.startswith("It starts with")
    assert aria.answer_app("stop")[0]  # quiz ended
    assert aria.quiz.active is None

def test_study_buttons_are_not_taken_as_quiz_answers(aria, open_note):
    ...start quiz...; aria.llm = FakeLLM(replies=[("Simple version.", [])])
    assert aria.study_app("explain")[0] == "Simple version."
    assert aria.quiz.active is None

def test_quiz_on_a_tiny_note_says_so(aria, open_note):
    open_note("Stub", "<h1>Title</h1>")
    assert "doesn't have enough in it" in aria.study_app("quiz")[0]

def test_study_leaves_a_pending_question_alone(aria, open_note):
    open_note("Zelle", "<p>Mitochondria make ATP for the cell.</p>")
    aria.confirm.request("delete the event Test", lambda: "Deleted.")
    aria.llm = FakeLLM(replies=[("Explained.", [])])
    aria.study_app("explain")
    assert aria.confirm.pending
```

Set up `aria.quiz = Quiz(aria.notion)` with the monkeypatched `ollama.chat` and `STATE_FILE`, as in the `quiz` fixture. Put that setup in a local fixture `study_quiz`. Check how `Confirmer.request` is called in `tests/test_conversation.py` and match its real signature.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_study.py`. Expected: FAIL, `AttributeError: … 'study_app'`.

- [ ] **Step 3: Implement** `STUDY_NOTE_CHARS`, `study_app` and `_app_study` as specified above.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_study.py tests/test_app_bridge.py tests/test_quiz.py`. Expected: all pass.

- [ ] **Step 5: Commit** `main.py tests/test_study.py`: "Study actions on the open note: quiz, explain simply, test prep".

---

### Task 3: Bridge: `study` request and the `quiz` flag

**Files:**
- Modify: `ui/app_bridge.py` (docstring, `_handle`, `_serve`, `start`)
- Modify: `main.py` `_start_app_bridge` (~line 953)
- Modify: `FEATURES.md` (the MyNotion panel section ~line 479 and "Quiz me" ~line 283)
- Test: `tests/test_app_bridge.py`

**Interfaces:**
- Consumes: `Aria._app_study(action, on_text)` (Task 2).
- Produces: `app_bridge.start(answer, path=SOCKET_PATH, edit=None, study=None, quiz_active=None)`. `study(action, on_text) -> (reply, tools, confirm)`; `quiz_active() -> bool`. `STUDY_ACTIONS = ("quiz", "explain", "prep")`. `done` = `{"id", "type": "done", "reply", "tools", "confirm", "quiz": bool}` for chat and study. `quiz` is False when `quiz_active` is None or raises.
- `main.py` passes `study=self._app_study, quiz_active=lambda: bool(getattr(self, "quiz", None) and self.quiz.active)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_app_bridge.py`. Add a `serve_study` fixture like `serve_edit` that takes `(answer, study, quiz_active)`.

```python
def test_study_request_streams_and_finishes(serve_study):
    # study fake: on_text("Point one. "); returns ("Point one. Point two.", [], None); quiz_active → False
    events = ...send {"id": "s1", "type": "study", "action": "prep"}...
    assert events[0] == {"id": "s1", "type": "text", "delta": "Point one. "}
    assert events[-1] == {"id": "s1", "type": "done", "reply": "Point one. Point two.", "tools": [],
                          "confirm": None, "quiz": False}

def test_study_passes_the_action(serve_study):            # study called with "quiz"
def test_unknown_study_action_is_refused(serve_study):    # "action": "summarise" → error "I don't know that study action."; study never called
def test_study_on_an_aria_that_cannot_study(serve):       # study=None → error, not a crash
def test_study_that_raises_gives_a_plain_error(serve_study):  # → error SORRY
def test_done_reports_quiz_state_after_a_chat(serve_study):   # quiz_active → True; a chat's done has "quiz": True
def test_quiz_flag_is_false_when_the_check_fails(serve_study):  # quiz_active raises → "quiz": False
```

Update the existing assertions on chat `done` dicts in this file to include `"quiz": False`.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_app_bridge.py`. Expected: the new tests fail, and the updated old ones fail on the missing `quiz` key.

- [ ] **Step 3: Implement.** In `_handle`: `kind == "study"` → `_handle_study(rid, req, study, send, quiz_active)`, which validates the action, makes the same `on_text` lambda as chat, and on an exception logs and sends `SORRY`. Thread `study` and `quiz_active` through `_serve` and `start` the way `edit` is threaded. A shared `_done(rid, reply, tools, confirm, quiz_active)` builds the `done` for both. Add the `study` lines and the `"quiz"` field to the protocol docstring. Wire it up in `main.py`.

- [ ] **Step 4: Update `FEATURES.md`.** Add the study buttons to the MyNotion panel section (what each does, Hint/Skip/Stop, "covers the whole note up to 12,000 characters", files `Aria.study_app`, `ui/app_bridge.py`, MyNotion `aria-panel`). Add one line under "Quiz me": "In MyNotion's Aria panel, **Quiz me** quizzes you on the open note with one click."

- [ ] **Step 5: Run** the full suite: `.venv/bin/python -m pytest`. Expected: all pass.

- [ ] **Step 6: Commit** `ui/app_bridge.py main.py tests/test_app_bridge.py FEATURES.md`: "Panel socket: study requests, and every reply says whether a quiz is running".

---

### Task 4: MyNotion main process: forward `study` and `quiz`

**Files (in `../../MyNotion`):**
- Modify: `note/src/aria.ts` (header comment lines 4–6, `AriaEvent` ~line 19, `onLine` done branch ~line 113, new `study()` next to `edit()` ~line 147, new `ipcMain.handle('aria:study', …)` in `setUpAria` ~line 196)
- Modify: `note/src/preload.ts` (~line 42)
- Modify: `note-frontend/src/services/NoteService.ts` (`AriaEvent` ~line 13, `aria?:` typings ~line 90)
- Test: `note/src/aria.test.ts`

**Interfaces:**
- Produces: `export type StudyAction = 'quiz' | 'explain' | 'prep'` (in `aria.ts` and mirrored in `NoteService.ts`). `AriaLink.study(action: StudyAction): Promise<AskResult>` sends `{type: 'study', action}`. IPC `'aria:study'` (an invalid action → `{ok: false, error: 'not-running'}`, like `aria:edit`). Preload: `study: (action: string) => ipcRenderer.invoke('aria:study', action)`. Renderer typing: `study?: (action: StudyAction) => Promise<AskResult-shape>`. The `done` event gains `quiz: boolean`, which is `e.quiz === true` (anything else → false).

- [ ] **Step 1: Write the failing tests** in `note/src/aria.test.ts`, following `'sends the selection and relays her proposal'` (~line 235):
  - `'sends a study action and relays text and done with the quiz flag'`: the fake server receives `{id, type: 'study', action: 'quiz'}` and replies with a text event and `done` with `quiz: true`. The emitted `done` has `quiz: true`.
  - `'a done without quiz says false'`: the existing relay test's expected `done` gains `quiz: false`.
  - `'study says not-running when she is not there'`.

- [ ] **Step 2: Run** `cd ../../MyNotion/note && npx vitest run src/aria.test.ts`. Expected: the new tests fail.

- [ ] **Step 3: Implement** as listed under Interfaces, and update the header protocol comment.

- [ ] **Step 4: Run** `npx vitest run` (in `note/`). Expected: all pass. Also run `npx tsc --noEmit -p .` if the package has a tsconfig. Expected: no errors.

- [ ] **Step 5: Commit** in the MyNotion repo: `note/src/aria.ts note/src/preload.ts note/src/aria.test.ts note-frontend/src/services/NoteService.ts`, "Aria link: study requests and the quiz flag".

---

### Task 5: MyNotion panel: the buttons

**Files (in `../../MyNotion/note-frontend/src/app/aria-panel/`):**
- Modify: `aria-chat.ts`, `aria-panel.ts`, `aria-panel.html`, `aria-panel.css`
- Test: `aria-panel.spec.ts`

**Interfaces:**
- Consumes: `window.electronAPI.aria.study(action)`, and `done.quiz` (Task 4).
- Produces, in `AriaChat`:
  - `quizActive = false`, set from every `done` (`e.quiz === true`).
  - `PanelMessage.study?: StudyAction`.
  - `study(action: StudyAction): Promise<boolean>`: shows the user message `STUDY_LABELS[action]` (`{quiz: 'Quiz me', explain: 'Explain simply', prep: 'Test prep'}`) and a pending reply, then calls `api.study(action)`. It shares the bookkeeping in `deliver` (refactor `deliver` to take a sender function and an optional `study`, and don't duplicate the asking/early/not-running handling).
  - `retry` resends via `study()` when `m.study` is set.
  - `quizButton(word: 'hint' | 'skip' | 'stop')` → `deliver(word)`.
- `AriaPanel` exposes `quizActive`, `study(a)` and `quizButton(w)` and passes them through.

Template, placed above the `<textarea>` inside `<footer>`, after the chip:
- `@if (noteTitle && running !== false)`: a `div.study` row. When `quizActive`, it shows the buttons Hint/Skip/Stop; otherwise Quiz me / Explain simply / Test prep. All are `[disabled]="busy"`.
- The empty-state text becomes `Ask about this note, or use the buttons below to study it.` when `noteTitle` is set. Otherwise it stays `Ask about this note, your lists or your calendar.`
- CSS: small pill buttons in one wrapping row with a gap, using the existing button tokens from `aria-panel.css`. Look at `.confirm button` / `.yes` there.

- [ ] **Step 1: Write the failing tests** in `aria-panel.spec.ts`. Add `study: async (a: string) => { studied.push(a); return askResult(); }` to the fake `electronAPI.aria`. Use the open-note setup from `'shows the open note as a chip'` (~line 218).
  - `'hides the study buttons when no note is open'`
  - `'Quiz me sends the quiz study action and shows "Quiz me"'`: `studied` equals `['quiz']`, and the text contains `Quiz me`.
  - `'Explain simply and Test prep send explain and prep'`
  - `'a done with quiz true shows Hint, Skip and Stop, and they send hint, skip and stop'`: `asked` equals `['hint']` after a click, and so on.
  - `'a done with quiz false brings the study buttons back'`
  - `'study buttons are disabled while a reply is pending'`
  - `'retry resends a failed study action'`: an error event, then `retry`; `studied` is `['prep', 'prep']` and `asked` stays empty.
  - `'the empty panel points to the buttons when a note is open'`

- [ ] **Step 2: Run** `cd ../../MyNotion/note-frontend && npx ng test --watch=false --browsers=ChromeHeadless`. Expected: the new specs fail.

- [ ] **Step 3: Implement** as listed under Interfaces.

- [ ] **Step 4: Run** the same command. Expected: all specs pass, the existing ones included.

- [ ] **Step 5: Live check.** Run `./aria.sh` from `BetterAI/` and open MyNotion. Open a note with text and press each button. Check that the quiz buttons appear during a quiz and go away after Stop, and that the orb isn't left on "thinking". Report what you saw.

- [ ] **Step 6: Commit** in the MyNotion repo: the four panel files and the spec, "Aria panel: Quiz me, Explain simply and Test prep for the open note".
