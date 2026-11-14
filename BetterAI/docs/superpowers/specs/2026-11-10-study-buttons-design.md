# Study buttons in MyNotion's Aria panel: design

Date: 2026-11-10. Status: approved in conversation, waiting for spec review.

## Why

Lala studies on their own and has never needed Aria while studying. The hard parts are **understanding the
material** and **testing themselves**, and the material is mostly typed MyNotion notes. Aria already has a quiz
and an Explain action for selected text, but Lala didn't know about them. The problem is that the features can't be
found, not that they're missing.

Success: in a real study session Lala reaches for Aria from the note they're reading, with one click and no magic
phrases.

Not in scope: reading images in notes (its own project later), reminders before WebUntis tests (later), new tools.

## What the user sees

When a note with text is open, the Aria panel shows three buttons above the text box:

- **Quiz me**: 5 short questions from this note, one at a time, answered by typing. While a quiz is running, the
  buttons change to **Hint · Skip · Stop**. Missed questions are saved for "quiz me on my mistakes" as before.
- **Explain simply**: the note's main ideas in plain language, short, with an example where it helps.
- **Test prep**: the 5–8 most important things to know from the note, then 3 questions a teacher would likely ask.

The buttons are hidden when no note is open or the open note has no text. The empty-panel line points to them,
e.g. "Ask about this note, or use the buttons below to study it."

Explain and Test prep only answer: no tools, nothing in the note changes.

**Long notes:** Explain and Test prep send the whole note up to `STUDY_NOTE_CHARS = 12000` characters of text. Above
that they use the first part, cut at a line break, and code adds a line to the reply: "(I only covered the first part of this note, it's long.)" (Longest current
note: ~5,400 characters.) The quiz keeps its own `pick_chunk` (a random 5,000-character part).

## Protocol (`ui/app_bridge.py`)

A new request type on the existing socket:

    MyNotion → Aria   {"id": "12", "type": "study", "action": "quiz|explain|prep"}
    Aria → MyNotion   {"id": "12", "type": "text", "delta": "…"}           (streamed, as for chat)
                      {"id": "12", "type": "done", "reply": "…", "tools": [], "confirm": null, "quiz": true}

- An unknown `action` → `error` "I don't know that study action."
- `done` gets a new field `"quiz": bool`, which is true while a quiz is running after this turn. It is added to
  **every** `done` (chat too), so the panel always knows whether to show Hint/Skip/Stop: a quiz can also be started
  or ended by typing or by voice.
- Hint, Skip and Stop are sent as ordinary chat messages (`"hint"`, `"skip"`, `"stop"`). The quiz intercept in
  `_handle_turn` already handles them in code.

The protocol docstring at the top of `app_bridge.py` is updated.

## Aria (`main.py`, `Engines/Quiz.py`)

`Aria.study_app(action, on_text=None) -> (reply, tools, confirm)`:

- Refuses during dictation, with the same message as `answer_app`.
- Runs under `_turn_lock()` and restores the orb state the way `answer_app` does.
- Reads the open note in code (`self.notion.open_note()`, `html_to_text`). No note → "Open a note first, then I can
  help you study it." Empty note → "This note is empty, there's nothing to study yet."
- `quiz` → `self.quiz.start_on(title, text)`.
- `explain` / `prep` → one model call without tools (`use_tools=False`), with a fixed instruction written in code
  plus the note text. Both turns go into the message history and `_recent` like a panel chat, so follow-up questions
  work.
- Nothing is spoken.

`Quiz.start_on(title, text, count=5)`: the part of `start()` after the source has been found (`pick_chunk`, the
too-short check, `make_questions`, `_begin`). `start()` calls it after `find_source`, so there is no duplicate code.

`app_bridge.start()` gets one more callable, `quiz_active() -> bool` (Aria passes `lambda: bool(self.quiz and self.quiz.active)`), and the bridge calls it when it builds each `done`.

## MyNotion panel (`../../MyNotion/note-frontend/src/app/aria-panel/`)

- `aria-panel.html` / `.css`: the row of study buttons, shown when a note is open (the panel already knows
  `noteTitle`) and not while busy. During a quiz, Hint/Skip/Stop replace them. Same dark/green tokens as the rest
  of the panel.
- `aria-chat.ts`: `study(action)` sends the new request, and its reply streams into the message list like a chat
  reply; it is shown as the user message "Quiz me" / "Explain simply" / "Test prep". It stores `quiz` from each
  `done`.
- `note/src/aria.ts`: lets `study` requests through to the socket, as it does chat and edit.

## Errors

- Aria not running → the panel's existing offline state with Start.
- A model failure or `error` event → the existing failed message with Retry (which resends the same study action).
- No questions could be made → the quiz's existing message ("I couldn't come up with questions…").

## Tests

Aria (all with `FakeLLM`, no model):
- bridge: `study` is routed; unknown action → error; `done` includes `quiz`.
- `study_app`: no open note, empty note, dictation running.
- `quiz` starts on the open note even when its title wouldn't match the title search; Hint/Skip/Stop are answered in code.
- `explain`/`prep` are called without tools and with the note text; a note over 12,000 characters is cut, and the
  reply ends with the "first part" line.
- `Quiz.start()` behaves as before (existing tests).

MyNotion (`aria-panel.spec.ts`, `aria.test.ts`):
- the buttons are hidden without a note; clicking one sends the right `study` action.
- `done` with `quiz: true` shows Hint/Skip/Stop, and they send "hint"/"skip"/"stop"; `quiz: false` brings the study buttons back.
- `aria.ts` forwards `study` requests.

`FEATURES.md`: add the study buttons under the MyNotion panel section and mention them under "Quiz me".
