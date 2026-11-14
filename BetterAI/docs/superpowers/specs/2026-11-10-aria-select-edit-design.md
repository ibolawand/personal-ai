# Select text, ask Aria — design

Date: 2026-11-10. Piece 2 of 3 of "Aria inside MyNotion" (piece 1: `2026-11-09-aria-panel-design.md`).

## Why

Aria's note editing changes whole notes in the background, is slow on long notes and can't be steered. Working on
just the selected text is fast, is where the small local model does well, and lets the user see a change before it
lands. Everything stays local.

## What the user gets

- Selecting text in a note adds an **Aria** button to the selection toolbar. It opens a menu: **Rewrite**,
  **Shorter**, **Fix spelling**, **Make a table**, **Explain**, and a box for an own instruction ("make this more
  formal", "turn into bullet points"; Enter sends it).
- A card appears under the selection: "Aria is writing…", then her version, drawn as it would look in the note
  (headings, lists, tables, formulas, boxes).
- The card has **Accept**, **Try again**, **Reject** and a box to steer ("keep the exercise numbers"). Steering
  redoes the same selection with that instruction added. Esc rejects.
- The note doesn't change until Accept. Accept replaces the selection in the editor like a paste, so Ctrl+Z
  undoes it and the note saves as usual.
- The selected text stays marked while the card is open. If that text is edited meanwhile, the proposal is
  dropped with "The text changed, so I dropped my version."
- **Explain** changes nothing: it opens the Aria panel and asks her to explain the selected text there.
- When Aria has nothing to offer, the card says why ("I found no mistakes in that part.", "That would have
  removed a picture or highlight.") and offers Try again and Close.
- If Aria isn't running, the card says "Aria isn't running" with a Start button (same as the panel).

## Limits

- At most 4,500 characters of Markdown per selection (`CHUNK_CHARS`, what the model handles in one call). A
  larger selection gets "That's too much at once. Select a smaller part."
- Not offered inside code blocks or formulas (the toolbar isn't shown there today either).
- Not offered while Aria has the note locked ("Aria is editing…").

## Protocol (added to `ui/app_bridge.py`)

Request:

    {"id", "type": "edit", "action": "rewrite" | "shorter" | "spelling" | "table" | "custom",
     "html": "<the selection as HTML>", "instruction": "", "title": "<note title>",
     "context": "<plain text around the selection>", "previous": "<her last version as HTML, for Try again>"}

- `html`: 1–40,000 characters. `instruction`: at most 500 characters, required for `custom`.
  `title` ≤ 200, `context` ≤ 2,000, `previous` ≤ 40,000; all optional.

Events:

    {"id", "type": "proposal", "html": "<her version as HTML>"}
    {"id", "type": "error", "message": "<plain sentence>"}

An edit request runs under Aria's turn lock (one model call at a time on the GPU) but is not a conversation
turn: it isn't saved to history or memory, and she doesn't speak. Aria never writes to the database for it.

## Aria side

`NoteWriter.rework(html, action, instruction="", title="", context="", previous="") -> (html | None, message)`

- Converts the selection to Markdown (`html_to_md`), asks the model, converts back (`md_to_html`). Pictures,
  highlights and coloured text travel as `{{n}}` markers, as in the rest of NoteWriter.
- Checks in code, per action:
  - all: the reply isn't empty and isn't the same as the original; no `{{n}}` marker is lost; the old lines
    aren't kept next to the new ones
  - **spelling**: only small corrections (`small_changes`); no change at all → "I found no mistakes in that part."
  - **shorter**: fewer words than before, and no formula lost
  - **rewrite**: no formula lost
  - **table**: the result contains a table and no word, formula or marker is missing (`missing`)
  - **custom**: markers only (the instruction may legitimately remove text)
- A failed check gets one retry that tells the model what was wrong; after that, `(None, reason)`.
- `previous` (Try again) is shown to the model as a version to differ from, with a higher temperature.

`Aria.edit_app(...)`: takes the turn lock, shows "thinking" on the orb and puts it back, calls `writer.rework`,
logs failures with `Diagnostics.problem("app_edit", …)`.

## MyNotion side

- `note/src/aria.ts`: `AriaLink.edit(request)`; a `proposal` event closes the request like `done`. Exposed as
  `electronAPI.aria.edit`.
- `text-editor/aria-range.ts`: a small editor extension that marks one range, follows it through edits, and
  reports whether its text is still the original.
- `text-editor/aria-edit/`: the menu and the card (component). It reads the selection as HTML, sends the
  request, shows the states, draws the proposal in a read-only editor with the note's own extensions, and on
  Accept selects the marked range and pastes her HTML.
- `text-editor.ts` / `.html`: the Aria button in the selection toolbar and the component's place in the page.
- `AriaChat.ask(text)`: sends a message into the panel conversation (for Explain).

## Tests

- BetterAI: `rework` per action with the scripted model (accepted, each check failing, the retry, too long,
  empty, markers kept, Try again); the bridge's `edit` request (valid, each invalid field, the function
  raising); `edit_app` (lock, no history, orb state).
- MyNotion: `AriaLink.edit`; the range extension (follows edits, notices changes); the card (states, accept,
  reject, steer, try again, not running, changed meanwhile).
- Live, in the built app on a copy of the database: each action on a paragraph, part of a sentence, list
  items and a part with a formula; accept and Ctrl+Z; reject; Explain.

## Out of scope

Organising whole notes with per-section previews (piece 3), streaming the proposal while it is written,
translating a selection (the custom box covers it), and any cloud model.
