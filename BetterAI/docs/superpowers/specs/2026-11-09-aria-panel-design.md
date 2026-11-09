# Aria panel in MyNotion — design

Date: 2026-11-09. Piece 1 of 3 of "Aria inside MyNotion".

## Why

Aria is only reachable through the orb or by voice, outside MyNotion. Working on notes means leaving the app to
talk to her. Her note editing also gives poor results, is slow, and can't be steered. The agreed plan has three
pieces, built in this order, each usable on its own:

1. **Aria panel in MyNotion** (this spec): type to Aria inside the app.
2. **Select text, ask Aria**: actions on a selection, shown as before/after with Accept / Try again / Reject.
3. **Organise with preview and steering**: section by section, nothing saved until accepted.

Pieces 2 and 3 get their own specs. Both build on the connection defined here.

Constraints: everything stays local (Ollama `qwen3:8b`). The orb and voice keep working unchanged. MyNotion keeps
its dark/green look.

## What the user gets

- A panel on the right side of MyNotion, toggled with **Ctrl+J** or a button in the sidebar. It holds a message
  list and a text box. ↑ / ↓ in the text box bring back earlier messages.
- A chip above the text box shows the open note ("This note: Biology"), or nothing when no note is open.
  "Summarise this note" and "add a section about mitosis" work without naming the note (this already works through
  `app_state.open_note`).
- Replies appear word by word and are never spoken. The orb shows "thinking" during the turn, then returns to the
  state it had. A panel message does not wake Aria or start listening.
- A pending yes/no question shows **Yes** and **No** buttons under the reply. They send "yes" / "no" as a normal
  message, so the answer is still checked in code by `Confirmer`.
- The panel talks to the same Aria as the orb: same history, memory, tools and undo. All desk tools are available,
  because the user is at the laptop.
- If Aria isn't running, the panel says "Aria isn't running" with a **Start** button.
- The conversation shown in the panel lives as long as the MyNotion window. It is not stored by MyNotion; Aria
  keeps her own history.

Until pieces 2 and 3 exist, note changes made from the panel save directly, with the existing "Aria is editing…"
lock and undo.

## Aria side (BetterAI)

### `ui/app_bridge.py` (new)

A Unix socket server at `$XDG_RUNTIME_DIR/aria-<uid>-app.sock`, mode `0600`, separate from the hotkey socket in
`ui/instance.py` (that one reads 64 bytes and closes; this one is a conversation).

Protocol: newline-delimited JSON, UTF-8. One connection can carry many requests, one at a time.

Requests from MyNotion:

| Message | Meaning |
|---|---|
| `{"id": "<str>", "type": "chat", "text": "<str>"}` | One turn. `text` is 1–4000 characters after trimming. |
| `{"id": "<str>", "type": "status"}` | Is Aria ready? |

Events from Aria, each carrying the request's `id`:

| Message | Meaning |
|---|---|
| `{"type": "text", "delta": "<str>"}` | Reply text as it streams. |
| `{"type": "done", "reply": "<str>", "tools": ["<name>", …], "confirm": "<question>" \| null}` | The turn is over. `reply` is the tidied final reply and replaces the streamed text. `confirm` is the pending yes/no question, if any. |
| `{"type": "status", "ready": true}` | Answer to `status`. |
| `{"type": "error", "message": "<plain sentence>"}` | Bad request, or the turn raised. |

Rules:
- A line that isn't valid JSON, has an unknown `type`, or has a missing or oversized `text` gets an `error` event;
  the connection stays open.
- A request line longer than 64 KB closes the connection.
- Each connection is served on its own daemon thread. `start(answer)` takes the function that runs a turn:
  `answer(text, on_text) -> (reply, tools, confirm)`. The module knows nothing else about Aria, so it is testable
  with a stand-in.
- A client that disconnects mid-turn doesn't stop the turn; further writes are dropped silently.

### `Aria.answer_app(text, on_text)` (new, in `main.py`)

Modelled on `answer_phone`:
- takes `_turn_lock()`, so the desk, the phone and the panel never run turns at the same time
- calls `handle_turn(text, check_state=False, on_text=…)` with all tools (no `tools.phone()` restriction)
- does not speak, does not change `awake`, and sets the orb back to "listening" or "sleeping" afterwards
- returns the tidied reply, the tool names used, and `confirm.pending[0]` if a question is pending

The text passed to `on_text` goes through a `SentenceStreamer`-free path: raw deltas are forwarded, and the final
`done.reply` is authoritative. The panel replaces the streamed text with it, so filler or offers cut by
`tidy_reply` disappear at the end of the turn.

### Startup

`main.py` starts the bridge after `Aria` is built, in every mode (overlay, voice, `--no-ui`). It writes the
absolute path of `aria.sh` to `app_state.aria_launcher` in the MyNotion database, so MyNotion can start Aria
without a hardcoded path. If `DB_PATH` isn't set, this step is skipped.

## MyNotion side

### `note/src/aria.ts` (new, Electron main process)

- Connects to the socket with `net.connect`, lazily on first use, and reconnects on the next request after a drop.
- Splits incoming data into lines and forwards each parsed event to the window as `aria:event`.
- IPC handlers:
  - `aria:ask(text)` → sends a `chat` request, returns its `id`; rejects with `not-running` if the socket can't be
    reached
  - `aria:status()` → `running` | `not-running`
  - `aria:start()` → reads `app_state.aria_launcher`, spawns it detached, then polls the socket for up to 60 s
- If the connection closes while a request is open, it emits a local `{"type": "error", "message": "Aria stopped
  answering."}` for that `id`.
- The line splitter and request builder are pure functions, exported for tests.

### `note/src/preload.ts`

The existing `aria` group gains `ask`, `status`, `start` and `onEvent(callback)` (returns an unsubscribe function,
like `onDbChanged`).

### `note-frontend/src/app/aria-panel/` (new Angular component)

- Added to `home-app.html` after the main workspace, shown when `modelService.ariaPanelOpen$` is true. The
  workspace shrinks; the sidebar and notes list don't move.
- State: a list of messages (`user` | `aria`, text, `pending`, `failed`, `confirm`), the input, the input history.
- Sending is disabled while a reply is pending. A failed reply keeps its partial text and shows **Retry**, which
  resends the same message.
- The note chip reads the open note from `ModelService`.
- Ctrl+J toggles the panel from anywhere in the app and focuses the text box. Esc in the text box closes it.
- Styling uses the app's existing colour variables; no new palette.

## Errors

| Situation | What happens |
|---|---|
| Aria not running | Panel shows "Aria isn't running" + Start. After Start, the panel becomes usable when `status` answers. |
| Aria busy with another turn | The request waits on the turn lock; the panel shows "thinking". |
| Connection drops mid-reply | Partial text stays, marked "Aria stopped answering", with Retry. |
| Turn raises in Aria | `error` event with a plain sentence; logged with `Diagnostics.problem("app_turn", …)`. |
| Launcher path missing | Start shows "Start Aria once from the menu, then try again." |

## Tests

BetterAI, `tests/test_app_bridge.py`, using a temporary socket path and the `aria` fixture with `FakeLLM`:
- a chat request streams `text` events and ends with `done` carrying the reply and tool names
- a pending confirmation appears in `done.confirm`, and a following "yes" resolves it
- invalid JSON, an unknown type and an empty or oversized text each give `error` and keep the connection open
- two requests at once run one after the other
- a client that disconnects mid-turn doesn't break the server
- `answer_app` doesn't speak and doesn't change `awake`

MyNotion, vitest, `note/src/aria.test.ts`:
- the line splitter handles events split across chunks and several events in one chunk
- a closed connection with an open request yields the "stopped answering" error

By hand, with both apps on a copy of the database: open the panel, ask about the open note, add to a list, answer
a yes/no with the buttons, quit Aria mid-reply, start her from the panel.

## Docs

`FEATURES.md` gets a section for the panel under "MyNotion app". `CLAUDE.md` gets one line on the bridge.

## Out of scope

Before/after previews, selection actions, per-section organising (pieces 2 and 3), voice input inside MyNotion,
storing the panel conversation between app starts, and any cloud model.
