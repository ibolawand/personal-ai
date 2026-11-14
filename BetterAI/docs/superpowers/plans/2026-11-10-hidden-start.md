# Hidden Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MyNotion's Start button starts the full Aria with the orb hidden. The hotkey, the menu or a card shows it later in the same process.

**Architecture:** A new `--hidden` flag makes `run_with_overlay` skip `overlay.show()`. A new no-op `ping` instance command lets a hidden start find out whether Aria is already running without popping up the orb. `aria.sh` passes the flag on, and MyNotion's launcher call adds it.

**Tech Stack:** Python 3, PySide6 (offscreen in tests), pytest; bash; TypeScript + vitest (`MyNotion/note`).

**Spec:** `docs/superpowers/specs/2026-11-10-hidden-start-design.md`

**Repos:** Tasks 1–2 commit in `personal-ai` (cwd `BetterAI/`). Task 3 commits in `../../MyNotion`.

## Global Constraints

- Flag name: `--hidden`. Instance command name: `ping`. MyNotion: `LAUNCH_ARGS = ['--hidden']`.
- `ping` never shows the window, plays no wave and doesn't open the text box.
- A normal start (no `--hidden`) behaves exactly as today, including `send("show")` when Aria is already running.
- A hidden start against a running Aria prints `Aria is already running.` and exits 0.

## Review Focus

1. **The autostart or menu start (no flag) must still show the orb**: `already_running(False, send)` sends `show`. Test in Task 2: `test_normal_start_still_shows_a_running_aria`.
2. **`ping` on a hidden overlay must leave the text box closed and the window hidden.** A stray `_toggle_input(True)` would grab focus away from MyNotion. Test in Task 1: `test_ping_leaves_a_hidden_overlay_alone`.
3. **`ping` on a visible overlay with the text box open must not close the box** (`toggle` would). Test in Task 1: `test_ping_leaves_an_open_text_box_open`.
4. **`aria.sh --hidden` must reach the start path** and not exit through one of the command cases. Covered by the Task 2 shell check (`bash -n` + grep), and live by Lala.
5. **The `--no-ui` listener with `ping`** must not shut down or crash. It already ignores everything but `quit`; Task 2's test `test_no_ui_listener_ignores_ping` pins that.

---

### Task 1: `ping` command and a hidden-capable overlay

**Files:**
- Modify: `ui/instance.py` (docstring, `COMMANDS`)
- Modify: `ui/overlay.py` (`_on_remote` ~line 480, `run_with_overlay` ~line 1135)
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces: `instance.COMMANDS` includes `"ping"`. `run_with_overlay(make_aria, visible: bool = True)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_overlay.py`, using the existing `overlay` fixture. Call `overlay.hide()` first where the test needs a hidden start.

```python
def test_ping_is_an_instance_command():
    from ui import instance
    assert "ping" in instance.COMMANDS

def test_ping_leaves_a_hidden_overlay_alone(overlay):
    overlay.hide()
    overlay._on_remote("ping")
    assert not overlay.isVisible() and not overlay.input.isVisible()

def test_ping_leaves_an_open_text_box_open(overlay):
    overlay.show(); overlay._on_remote("show")
    overlay._on_remote("ping")
    assert overlay.input.isVisible()

@pytest.mark.parametrize("cmd", ["show", "toggle"])
def test_the_hotkey_shows_a_hidden_orb(overlay, cmd):
    overlay.hide()
    overlay._on_remote(cmd)
    assert overlay.isVisible()

def test_a_card_shows_a_hidden_orb(overlay):
    overlay.hide()
    overlay._on_card({"type": "reminder", "text": "Call mum"})   # use the shape of an existing card test
    assert overlay.isVisible()
```

Check `test_list_card_checkbox` for a valid card dict and use the minimal one `Card` accepts.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_overlay.py`. Expected: the `ping` tests fail (`"ping" not in COMMANDS`, and `_on_remote("ping")` shows the window). The hotkey and card tests may already pass, because they pin existing behaviour.

- [ ] **Step 3: Implement.**
  - Add `ping` to `COMMANDS`, with a docstring line: `ping    nothing; only checks that Aria is running (MyNotion's hidden start)`.
  - In `_on_remote`, `return` right away for `"ping"`, before `show()`.
  - Add `visible=True` to `run_with_overlay`, and only call `overlay.show()` when it's true.

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_overlay.py`. Expected: all pass.

- [ ] **Step 5: Commit** `ui/instance.py ui/overlay.py tests/test_overlay.py`: "Overlay can start hidden; a ping command that only checks Aria is running".

---

### Task 2: `--hidden` in `main.py` and `aria.sh`

**Files:**
- Modify: `main.py` (`__main__` block ~line 1692; new module-level function above it)
- Modify: `aria.sh`
- Modify: `FEATURES.md` (Aria panel section)
- Create: `tests/test_hidden_start.py`

**Interfaces:**
- Consumes: `instance.COMMANDS` with `ping`, and `run_with_overlay(make_aria, visible=...)` (Task 1).
- Produces: `main.already_running(hidden: bool, send=None) -> bool`. `send` defaults to `ui.instance.send`. It sends `"ping"` if `hidden`, else `"show"`, and returns the result.

- [ ] **Step 1: Write the failing tests** in `tests/test_hidden_start.py`:

```python
import main

def test_hidden_start_only_pings():
    sent = []
    assert main.already_running(True, lambda c: sent.append(c) or True) is True
    assert sent == ["ping"]

def test_normal_start_still_shows_a_running_aria():
    sent = []
    assert main.already_running(False, lambda c: sent.append(c) or True) is True
    assert sent == ["show"]

def test_nothing_running():
    assert main.already_running(True, lambda c: False) is False

def test_no_ui_listener_ignores_ping():
    # the --no-ui handler in __main__: lambda cmd: aria.shutdown() if cmd == "quit" else None
    # extract it as main._no_ui_command(aria, cmd) and check that ping doesn't call shutdown
    calls = []
    main._no_ui_command(type("A", (), {"shutdown": lambda self: calls.append("quit")})(), "ping")
    assert calls == []
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_hidden_start.py`. Expected: FAIL, `AttributeError: module 'main' has no attribute 'already_running'`.

- [ ] **Step 3: Implement.**
  - `already_running` and `_no_ui_command(aria, cmd)` at module level.
  - `parser.add_argument("--hidden", action="store_true", help="start without showing the orb (MyNotion's Start button)")`.
  - The `__main__` block uses `already_running(args.hidden)`. Its message is `"Aria is already running."` when hidden, and the existing one otherwise. `--no-ui` uses `_no_ui_command`, and the overlay path calls `run_with_overlay(..., visible=not args.hidden)`.
  - `aria.sh`: add a case `--hidden) ARGS="--hidden" ;;` to the existing `case`. It must fall through to the start section, so no `exit`. Replace the `ARGS=""` line with `ARGS="${ARGS:-}"` so the case's value survives.

- [ ] **Step 4: Update `FEATURES.md`** in the Aria panel bullet about **Start**: "Start launches her without the orb (`aria.sh --hidden`); Ctrl+Alt+Space or the menu shows it, and a reminder or question card brings it up too."

- [ ] **Step 5: Verify.**
  - `.venv/bin/python -m pytest` → all pass.
  - `bash -n aria.sh` → no output.
  - `grep -n 'hidden' aria.sh` shows the case line and no `exit` on it.

- [ ] **Step 6: Commit** `main.py aria.sh FEATURES.md tests/test_hidden_start.py`: "aria.sh --hidden: start without the orb; a running Aria stays out of sight".

---

### Task 3: MyNotion's Start runs the launcher with `--hidden`

**Files (in `../../MyNotion`):**
- Modify: `note/src/aria.ts` (the `spawn(launcher, [] …)` call in `aria:start` ~line 234)
- Test: `note/src/aria.test.ts`

**Interfaces:**
- Produces: `export const LAUNCH_ARGS = ['--hidden']` and `export function launch(launcher: string, run: typeof spawn = spawn): void`. `launch` spawns `launcher` with `LAUNCH_ARGS` and `{ detached: true, stdio: 'ignore', cwd: path.dirname(launcher) }`, then `.unref()` on the child. `aria:start` calls `launch(launcher)`.

- [ ] **Step 1: Write the failing test** in `aria.test.ts`, inside the launcher `describe`:

```ts
it('starts her without the orb', () => {
    const calls: any[] = []; let unref = false;
    launch('/x/aria.sh', ((cmd: string, args: string[], opts: object) => { calls.push([cmd, args, opts]); return { unref: () => { unref = true; } }; }) as any);
    expect(calls).toEqual([['/x/aria.sh', ['--hidden'], { detached: true, stdio: 'ignore', cwd: '/x' }]]);
    expect(unref).toBe(true);
});
```

- [ ] **Step 2: Run** `cd ../../MyNotion/note && npx vitest run src/aria.test.ts`. Expected: FAIL, `launch` is not exported.

- [ ] **Step 3: Implement** as listed under Interfaces. Add one line to the header comment: "Start runs the launcher with --hidden: she starts without the orb."

- [ ] **Step 4: Run** `npx vitest run`. Expected: all pass.

- [ ] **Step 5: Commit** in the MyNotion repo `note/src/aria.ts note/src/aria.test.ts`: "Start Aria without her orb from the panel".
