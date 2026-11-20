# Aria Panel in MyNotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A panel inside MyNotion where the user types to Aria and gets streamed replies, without leaving the app.

**Architecture:** Aria (Python) opens a private Unix socket that speaks newline-delimited JSON. MyNotion's Electron main process connects to it and relays events to an Angular side panel. A panel turn runs through the same `handle_turn` as the orb, under the shared turn lock, without voice.

**Tech Stack:** Python 3 (stdlib `socket`, `json`, `threading`), pytest; Electron main process (Node `net`), vitest; Angular standalone component, Karma/Jasmine specs.

**Spec:** `BetterAI/docs/superpowers/specs/2026-11-09-aria-panel-design.md`

## Global Constraints

- Two repositories. BetterAI: `/home/lala/Desktop/school/personal/personal-ai/BetterAI`, branch `aria-desk-assistant`. MyNotion: `/home/lala/Desktop/school/personal/MyNotion`, branch `aria-integration`. Commit in the repository the files belong to. Do not push.
- Everything stays local. No new Python or npm dependencies.
- Socket path: `$XDG_RUNTIME_DIR/aria-<uid>-app.sock` (fallback `/tmp`), mode `0600`.
- Protocol: newline-delimited JSON, UTF-8. `chat` text is 1–4000 characters after trimming. A request line over 64 KB closes the connection.
- Panel replies are never spoken and never change `Aria.awake`.
- MyNotion keeps its look: background `#171a29`, text `#e4e7eb`, accent green `#4ade80`. No new palette.
- Tests never touch real data, the model, the mic or the network (`tests/conftest.py` enforces this in BetterAI).
- BetterAI tests: `.venv/bin/python -m pytest`. MyNotion main-process tests: `cd note && npm test`. Frontend specs: `cd note-frontend && npx ng test --watch=false --browsers=ChromeHeadless`.

## Review Focus

1. **A reply with umlauts or emoji split across socket reads** (German notes are common): the text must arrive intact, not as `�`. Pinned in Task 3 (`splitLines` works on bytes, decodes whole lines only).
2. **A stale socket file after Aria crashed**: MyNotion must report "not running", not hang. Pinned in Task 3 (`status` against a path nobody listens on).
3. **Enter pressed twice, or a second message while a reply is pending**: only one request is sent. Pinned in Task 4.
4. **Aria rewrites her reply after streaming** (stock or repeated reply, cut offers): the panel must show the final reply, not the streamed draft. Pinned in Task 4 (`done.reply` replaces streamed text).
5. **A message sent while a voice turn is running**: it waits and is answered afterwards, never dropped or interleaved. Pinned in Task 2 (turn lock).

---

### Task 1: The socket bridge (BetterAI)

**Files:**
- Create: `ui/app_bridge.py`
- Test: `tests/test_app_bridge.py`

**Interfaces:**
- Produces:
  - `SOCKET_PATH: str`, `MAX_TEXT = 4000`, `MAX_LINE = 65536`
  - `start(answer, path: str = SOCKET_PATH) -> socket.socket` — starts the server on a daemon thread; removes a leftover socket file first; `chmod 0o600`.
  - `answer` is `Callable[[str, Callable[[str], None]], tuple[str, list[str], str | None]]`: `(text, on_text) -> (reply, tool_names, confirm_question)`.
  - Events as in the spec: `text` / `done` / `status` / `error`, each with the request's `id`.

- [ ] **Step 1: Write the failing tests** in `tests/test_app_bridge.py`

A helper `client(path)` connects, and `ask(sock, obj)` sends one JSON line and reads lines until `done`, `status` or `error`. Each test starts the bridge on `tmp_path / "a.sock"` with a stand-in `answer`.

```python
def test_chat_streams_text_then_done(bridge):          # answer calls on_text("Hi "), on_text("there"), returns ("Hi there", ["add_note"], None)
    events = ask(sock, {"id": "1", "type": "chat", "text": "hello"})
    assert [e["type"] for e in events] == ["text", "text", "done"]
    assert events[-1] == {"id": "1", "type": "done", "reply": "Hi there", "tools": ["add_note"], "confirm": None}

def test_done_carries_pending_question(bridge):         # answer returns (..., [], "delete the team meeting")
    assert events[-1]["confirm"] == "delete the team meeting"

def test_status(bridge):
    assert ask(sock, {"id": "s", "type": "status"}) == [{"id": "s", "type": "status", "ready": True}]

@pytest.mark.parametrize("line", ["not json", '{"id":"1","type":"dance"}', '{"id":"1","type":"chat","text":"   "}',
                                  '{"id":"1","type":"chat","text":"' + "x" * 4001 + '"}', '{"id":"1","type":"chat"}', "[1,2]"])
def test_bad_request_gets_error_and_connection_survives(bridge, line):
    # send the raw line → one "error" event; then a status request on the same socket still answers

def test_oversized_line_closes_connection(bridge):      # 70_000 bytes without newline → recv returns b""

def test_answer_raising_gives_error(bridge):            # answer raises RuntimeError → {"type": "error", "message": "Something went wrong on my side."}

def test_client_leaving_mid_turn_does_not_break_server(bridge):
    # answer blocks on an Event; client closes; release the Event; a new client still gets status

def test_umlauts_roundtrip(bridge):                      # text "Größe 😀" reaches answer unchanged; reply "Schön" comes back unchanged

def test_socket_is_private(bridge):
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
```

- [ ] **Step 2: Run them, expect failure**

Run: `.venv/bin/python -m pytest tests/test_app_bridge.py`
Expected: FAIL, `No module named 'ui.app_bridge'`

- [ ] **Step 3: Implement `ui/app_bridge.py`**

One thread accepts; each connection gets a daemon thread that buffers bytes, splits on `b"\n"`, and decodes whole lines as UTF-8. Writes go through one `send(obj)` per connection that swallows `OSError`. JSON is written with `ensure_ascii=False`. The module must not import `main`.

- [ ] **Step 4: Run the tests, expect pass**

Run: `.venv/bin/python -m pytest tests/test_app_bridge.py`
Expected: all pass

- [ ] **Step 5: Commit** (BetterAI)

```bash
git add ui/app_bridge.py tests/test_app_bridge.py
git commit -m "Add the socket bridge MyNotion will use to talk to Aria"
```

---

### Task 2: `Aria.answer_app` and startup (BetterAI)

**Files:**
- Modify: `main.py` (new method next to `answer_phone` near line 848; startup block at the bottom; `shutdown`)
- Modify: `ui/overlay.py` (only if the bridge can't be started from `main.py` for the overlay path — see Step 3)
- Modify: `Engines/NotionEngine.py` (new public method)
- Test: `tests/test_app_bridge.py` (append), `tests/test_notion.py` (append)

**Interfaces:**
- Consumes: `ui.app_bridge.start(answer, path)` from Task 1.
- Produces:
  - `Aria.answer_app(self, text: str, on_text=None) -> tuple[str, list[str], str | None]`
  - `NotionEngine.set_launcher(self, path: str) -> None` — writes `app_state.aria_launcher`.
  - `app_state` key `aria_launcher`: absolute path of `aria.sh` (Task 3 reads it).

- [ ] **Step 1: Write the failing tests**

```python
def test_answer_app_runs_a_turn_without_voice(aria):
    aria.llm = FakeLLM(replies=[("Sure thing.", [("add_note", "Added.")])])
    spoken = []; aria.speak = lambda t: spoken.append(t)
    pieces = []
    reply, tools, confirm = aria.answer_app("note that I called the bank", pieces.append)
    assert reply == "Sure thing." and tools == ["add_note"] and confirm is None
    assert "".join(pieces) == "Sure thing." and spoken == [] and aria.awake is False

def test_answer_app_reports_pending_question_and_yes_resolves_it(aria):
    aria.confirm.request("delete the team meeting", lambda: "Deleted.")
    aria.llm = FakeLLM(replies=[("Should I delete it?", [])])
    assert aria.answer_app("delete the team meeting")[2] == "delete the team meeting"
    reply, tools, confirm = aria.answer_app("yes")
    assert reply == "Deleted." and tools == ["confirmation"] and confirm is None

def test_answer_app_waits_for_a_running_turn(aria):
    # hold aria._turn_lock() in another thread; answer_app must not return until it is released

def test_answer_app_offers_all_tools(aria):
    # aria.tools gets a `phone` attribute that fails the test if entered; answer_app must not use it

def test_set_launcher_is_stored(notion):                # tests/test_notion.py
    notion.set_launcher("/x/aria.sh")
    assert notion._state("aria_launcher") == "/x/aria.sh"
```

- [ ] **Step 2: Run them, expect failure**

Run: `.venv/bin/python -m pytest tests/test_app_bridge.py tests/test_notion.py -k "answer_app or launcher"`
Expected: FAIL, `'Aria' object has no attribute 'answer_app'`

- [ ] **Step 3: Implement**

- `answer_app`: like `answer_phone` but without `self.tools.phone()`, passing `on_text` through to `handle_turn(text, check_state=False, on_text=on_text)`. Returns `(tidy_reply(reply) or reply, [name for name, _ in used], self.confirm.pending[0] if self.confirm.pending else None)`. Afterwards sets the UI state to `"listening"` if `awake` else `"sleeping"`.
- `NotionEngine.set_launcher`: a thin wrapper over `_set_state`.
- Startup: at the end of `Aria.__init__`, call a new `self._start_app_bridge()`, which starts `app_bridge.start(self._app_answer)` and, when `self.notion` exists, calls `self.notion.set_launcher(str(Path(__file__).parent / "aria.sh"))`. `_app_answer` wraps `answer_app`, and on an exception logs `Diagnostics.problem("app_turn", …)` and re-raises so the bridge sends its error event. Both steps run inside `try/except` that prints and continues: a bridge failure must never stop Aria from starting. Doing this in `__init__` covers the overlay, voice and `--no-ui` paths, so `ui/overlay.py` stays untouched. The `aria` test fixture builds Aria with `__new__`, so tests are unaffected.
- `shutdown`: close the bridge socket and unlink the socket file.

- [ ] **Step 4: Run the whole suite, expect pass**

Run: `.venv/bin/python -m pytest`
Expected: all pass, none of the existing tests broken

- [ ] **Step 5: Commit** (BetterAI)

```bash
git add main.py Engines/NotionEngine.py tests/test_app_bridge.py tests/test_notion.py
git commit -m "Answer messages from MyNotion: same turn as the orb, no voice"
```

---

### Task 3: The connection in MyNotion's main process

**Files:**
- Create: `note/src/aria.ts`
- Create: `note/src/aria.test.ts`
- Modify: `note/src/preload.ts` (the existing `aria` group, lines 34–38)
- Modify: `note/src/index.ts` (call `setUpAria()` after `setUpAriaState()`)
- Modify: the frontend's `electronAPI` type declaration (find it with `grep -rn "electronAPI" note-frontend/src --include=*.d.ts`)

**Interfaces:**
- Consumes: the protocol and socket path from Task 1; `app_state.aria_launcher` from Task 2.
- Produces, on `window.electronAPI.aria`:
  - `ask(text: string): Promise<{ ok: true; id: string } | { ok: false; error: 'not-running' }>`
  - `status(): Promise<'running' | 'not-running'>`
  - `start(): Promise<{ ok: boolean; error?: 'no-launcher' | 'timeout' }>`
  - `onEvent(callback: (e: AriaEvent) => void): () => void`
  - `type AriaEvent = { id: string } & ({ type: 'text'; delta: string } | { type: 'done'; reply: string; tools: string[]; confirm: string | null } | { type: 'error'; message: string })`
- Exported for tests: `socketPath(env = process.env, uid = process.getuid!()): string`, `splitLines(buffer: Buffer, chunk: Buffer): { lines: string[]; rest: Buffer }`, `class AriaLink { constructor(path: string, emit: (e: AriaEvent) => void); ask(text): Promise<…>; status(): Promise<…>; close(): void }`.

- [ ] **Step 1: Write the failing tests** in `note/src/aria.test.ts`

Tests run a real `net.createServer` on a socket in `os.tmpdir()`.

```ts
it('builds the same socket path as Aria', () =>
  expect(socketPath({ XDG_RUNTIME_DIR: '/run/user/1000' }, 1000)).toBe('/run/user/1000/aria-1000-app.sock'));
it('falls back to /tmp', () => expect(socketPath({}, 7)).toBe('/tmp/aria-7-app.sock'));

it('joins an event split across chunks', …);            // '{"id":"1","ty' + 'pe":"text","delta":"a"}\n'
it('splits several events in one chunk', …);
it('keeps a multi-byte character split across chunks intact', …);   // Buffer of "Größe\n" cut inside "ö" → 'Größe'

it('says not-running when nobody listens', …);          // path that doesn't exist → status() === 'not-running', ask() → { ok: false, error: 'not-running' }
it('says not-running for a stale socket file', …);      // create and close a server without unlinking, then status()
it('relays text and done events for a request', …);     // fake server answers; emit receives them with the id ask() returned
it('emits "Aria stopped answering." when the connection closes mid-request', …);
it('reconnects on the next request after a drop', …);
```

- [ ] **Step 2: Run them, expect failure**

Run: `cd note && npm test -- aria.test`
Expected: FAIL, cannot find module `./aria`

- [ ] **Step 3: Implement `note/src/aria.ts`**

`AriaLink` connects lazily, keeps the ids of open requests, and on `close`/`error` emits `{ id, type: 'error', message: 'Aria stopped answering.' }` for each. Request ids come from `crypto.randomUUID()`. `status()` sends a `status` request with a 2 s timeout. `setUpAria()` creates one `AriaLink(socketPath(), e => every window gets 'aria:event')` and registers `aria:ask`, `aria:status`, `aria:start`. `aria:start` reads `aria_launcher` from `app_state`, requires it to be an absolute existing file whose name is `aria.sh`, spawns it with `spawn(path, [], { detached: true, stdio: 'ignore' }).unref()`, then polls `status()` every second for up to 60 s.

- [ ] **Step 4: Wire it up**

Add `ask`, `status`, `start`, `onEvent` to the `aria` group in `preload.ts` (`onEvent` follows the `onDbChanged` pattern), call `setUpAria()` in `index.ts`, and extend the frontend type declaration.

- [ ] **Step 5: Run tests and lint, expect pass**

Run: `cd note && npm test && npm run lint`
Expected: all pass, no lint errors

- [ ] **Step 6: Commit** (MyNotion)

```bash
git add note/src/aria.ts note/src/aria.test.ts note/src/preload.ts note/src/index.ts note-frontend/src
git commit -m "Connect to Aria: ask, status, start, and her streamed replies"
```

---

### Task 4: The panel

**Files:**
- Create: `note-frontend/src/app/aria-panel/aria-panel.ts`, `.html`, `.css`, `aria-panel.spec.ts`
- Modify: `note-frontend/src/app/model.service.ts` (panel open state)
- Modify: `note-frontend/src/app/home-app/home-app.html`, `home-app.ts`, `home-app.css`
- Modify: `note-frontend/src/app/side-bar/side-bar.html` (a button after Inbox, near line 46)
- Modify: `note-frontend/src/app/quick-search/quick-search.ts` (Ctrl+J in the existing `onKey`, lines 82–97)

**Interfaces:**
- Consumes: `window.electronAPI.aria` and `AriaEvent` from Task 3; `ModelService.currentNote$`.
- Produces:
  - `ModelService.ariaPanelOpen$: Observable<boolean>`, `ModelService.toggleAriaPanel(): void`
  - `<app-aria-panel>` with public members used by the spec: `messages: PanelMessage[]`, `draft: string`, `running: boolean | null`, `send(): Promise<void>`, `answer(text: 'yes' | 'no'): Promise<void>`, `retry(m: PanelMessage): Promise<void>`, `startAria(): Promise<void>`, `onKey(e: KeyboardEvent): void`
  - `type PanelMessage = { role: 'user' | 'aria'; text: string; id?: string; pending?: boolean; failed?: boolean; confirm?: string | null; question?: string }` (`question` is the user text a failed reply answers, for Retry)

- [ ] **Step 1: Write the failing spec** in `aria-panel.spec.ts`

The spec installs a fake `window.electronAPI.aria` that records `ask` calls and lets the test push events.

```ts
it('shows the user message and a pending reply after send', …);         // draft 'hello' → messages: user 'hello', aria '' pending; draft cleared
it('appends streamed text to the pending reply', …);                     // text 'Hi ', text 'there' → 'Hi there'
it('replaces the streamed draft with the final reply', …);               // done.reply 'Hi.' → text 'Hi.', pending false
it('ignores events for other ids', …);
it('does not send while a reply is pending', …);                         // send() twice → ask called once
it('does not send an empty or whitespace message', …);
it('shows Yes and No when a question is pending and sends the answer', …); // done.confirm set → answer('yes') calls ask('yes'); buttons gone afterwards
it('marks a reply failed on an error event and keeps the partial text', …);
it('retry resends the same question', …);
it('shows "Aria isn\'t running" when ask says not-running', …);          // running === false; the typed message stays in the draft
it('start makes the panel usable again', …);                             // start → { ok: true } → running === true
it('ArrowUp brings back the last message, ArrowDown goes forward', …);
it('shows the open note as a chip', …);                                  // currentNote$ emits { title: 'Biology' } → 'This note: Biology'
it('Escape closes the panel', …);
```

- [ ] **Step 2: Run it, expect failure**

Run: `cd note-frontend && npx ng test --watch=false --browsers=ChromeHeadless --include='**/aria-panel.spec.ts'`
Expected: FAIL, component not found

- [ ] **Step 3: Implement the component**

Standalone component. It subscribes to `aria.onEvent` in `ngOnInit` inside `NgZone.run` and unsubscribes in `ngOnDestroy`. It calls `aria.status()` when created. The list scrolls to the bottom on every change. Exact copy:
- placeholder: `Ask Aria…`
- not running: `Aria isn't running` with button `Start`; while starting: `Starting Aria…`
- start failed with `no-launcher`: `Start Aria once from the menu, then try again.`
- start failed with `timeout`: `Aria didn't start. Check ~/.cache/aria/aria.log.`
- failed reply footer: the event's message, with button `Retry`
- empty panel: `Ask about this note, your lists or your calendar.`

Layout: fixed width 360 px on the right, full height, left border `1px solid rgba(255,255,255,0.08)`, background `#171a29`. User messages right-aligned with a green (`#4ade80`) tint; Aria's left-aligned, plain. Text keeps line breaks (`white-space: pre-wrap`) and is rendered as text, never as HTML.

- [ ] **Step 4: Put it in the app**

- `ModelService`: a `BehaviorSubject(false)` with `ariaPanelOpen$` and `toggleAriaPanel()`.
- `home-app.html`: `@if (modelService.ariaPanelOpen$ | async) { <app-aria-panel></app-aria-panel> }` as the last child inside the dashboard block; `home-app.css`: `app-aria-panel { display: flex; flex: 0 0 360px; min-width: 0; height: 100%; }`.
- Sidebar: a `menu-item` button labelled `Aria` after Inbox, `[class.active]` bound to `ariaPanelOpen$`, click calls `toggleAriaPanel()`.
- `quick-search.ts` `onKey`: `mod && !e.shiftKey && key === 'j'` → `preventDefault()`, `toggleAriaPanel()`. The panel focuses its text box when it appears.

- [ ] **Step 5: Run the specs and a production build, expect pass**

Run: `cd note-frontend && npx ng test --watch=false --browsers=ChromeHeadless && npx ng build --base-href ./`
Expected: all specs pass, build succeeds

- [ ] **Step 6: Commit** (MyNotion)

```bash
git add note-frontend/src
git commit -m "Aria panel: talk to Aria inside MyNotion (Ctrl+J)"
```

---

### Task 5: Try it for real, then document

**Files:**
- Modify: `BetterAI/FEATURES.md` (new bullet group under "MyNotion app (`../MyNotion`)", near line 477)
- Modify: `BetterAI/CLAUDE.md` (one line under Architecture)
- Modify: `MyNotion/README.md` (one line on the panel, if it lists features)

- [ ] **Step 1: Run both apps on a copy of the database**

Copy `~/.config/MyNotion/noted.db` to the scratchpad. Start Aria with `DB_PATH` pointing at the copy and `ARIA_ARGS=` (no voice), and MyNotion in dev mode against the same copy (see how `note/src/database` picks its path; use its override if it has one, otherwise report this to the user and test against the real app with their OK).

- [ ] **Step 2: Check each of these and note the result**

1. Ctrl+J opens the panel; the text box has focus; Esc closes it.
2. With a note open, the chip shows its title; "what is this note about?" answers from it, streamed.
3. "add milk to my shopping list" changes the list; the note refreshes in MyNotion.
4. "clear my shopping list" shows Yes/No; No cancels; again with Yes clears; "undo that" restores it.
5. A message with `ä ö ü ß` comes back intact.
6. Quit Aria mid-reply (`./aria.sh --quit`): the reply is marked failed with Retry.
7. With Aria stopped: the panel says she isn't running; Start brings her up and the panel works.
8. The orb never speaks a panel reply and doesn't start listening.
9. `./aria.sh --report` shows no `app_turn` problems from the run.

Fix anything that fails in the task that owns the code, with a test, before continuing.

- [ ] **Step 3: Update the docs**

`FEATURES.md`: what the panel does, Ctrl+J, the chip, Yes/No buttons, Start, that replies aren't spoken, and the files (`ui/app_bridge.py`, `note/src/aria.ts`, `aria-panel/`). `CLAUDE.md`: one line saying MyNotion talks to Aria through `ui/app_bridge.py` and `Aria.answer_app`.

- [ ] **Step 4: Rebuild the installed app**

Run: `cd /home/lala/Desktop/school/personal/MyNotion && ./build_app.sh`
Expected: `✓ Done`

- [ ] **Step 5: Commit** (both repositories)

```bash
# BetterAI
git add FEATURES.md CLAUDE.md && git commit -m "Document the Aria panel in MyNotion"
# MyNotion
git add README.md && git commit -m "Mention the Aria panel"
```
