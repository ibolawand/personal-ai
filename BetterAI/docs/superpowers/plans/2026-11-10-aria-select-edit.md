# Select Text, Ask Aria Implementation Plan

**Goal:** Select text in a MyNotion note, pick an Aria action, see her version in a card, accept or reject it.

**Spec:** `docs/superpowers/specs/2026-11-10-aria-select-edit-design.md` (binding; names and limits are there).

**Execution:** native, test first, in the same two repositories and branches as piece 1
(`BetterAI` on `aria-desk-assistant`, `MyNotion` on `aria-integration`). Approved by the user without separate
spec and plan check-ins. No reviewer pass was requested; push both branches at the end.

## Tasks

1. **`NoteWriter.rework`** (`Engines/NoteWriter.py`, `tests/test_note_writer.py`): the five actions, their
   checks, one retry, `previous`, the size limit.
2. **Bridge + Aria** (`ui/app_bridge.py`, `main.py`, `tests/test_app_bridge.py`): the `edit` request and its
   validation; `start(answer, path, edit=None)`; `Aria.edit_app`.
3. **MyNotion connection** (`note/src/aria.ts`, `preload.ts`, typings, `aria.test.ts`): `AriaLink.edit`,
   `proposal` events.
4. **Range extension** (`text-editor/aria-range.ts` + spec).
5. **Menu and card** (`text-editor/aria-edit/` + spec; `text-editor.ts/.html`; `AriaChat.ask`).
6. **Live run** on a database copy, fix what it shows, update `FEATURES.md`, rebuild the app, push.

## Review focus

1. A selection inside one list item or one sentence: only that text changes, the list or paragraph stays intact.
2. A selection with a formula, picture or highlight: they come back unchanged or the proposal is refused.
3. The text is edited while the card is open: the proposal is never applied to the wrong text.
4. Two requests at once (double click, Try again while writing): only one runs, and a late answer to an old
   request is ignored.
5. The note is switched or closed while the card is open: the card goes away and nothing is applied.
