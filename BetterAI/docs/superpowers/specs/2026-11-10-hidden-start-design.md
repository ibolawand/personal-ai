# Starting Aria from MyNotion without the orb: design

Date: 2026-11-10. Status: approved in conversation, waiting for spec review.

## Why

When Aria isn't running, the **Start** button in MyNotion's Aria panel runs `aria.sh`, which starts the whole of
Aria **including the orb overlay**. Lala wants the orb to appear only when they summon Aria themselves (Ctrl+Alt+Space,
the menu, autostart). Started from MyNotion, she should be the same full Aria, just without the orb on screen.

## Behaviour

- **Start in the panel** starts the full Aria (camera, voice if configured, reminders, mail, Telegram, the panel
  socket) with the orb window **hidden**.
- **Ctrl+Alt+Space / the menu** while that Aria runs: the same process shows its orb and the text box, as a second
  launch does today. No restart; the conversation goes on.
- **A reminder, timer or yes/no card** shows the orb together with the card (today's `_on_card` already does this).
  After that the orb stays, as it does today.
- **A normal start** (menu, autostart, the hotkey while she isn't running) shows the orb right away, unchanged.
- **A hidden start while Aria is already running** does nothing visible and exits 0. (Today a second start sends
  `show`, which would pop up the orb.)
- Out of scope: hiding the orb again once it's shown.

## Changes

**`ui/instance.py`**: a new command `ping` in `COMMANDS` that the receiver ignores. It only proves that an Aria is
running. The docstring lists it. The overlay's `_on_remote` and the `--no-ui` listener must treat `ping` as a no-op:
no `show`, no wave, no text box.

**`ui/overlay.py`**: `run_with_overlay(make_aria, visible=True)`. With `visible=False`, `overlay.show()` isn't called
at start. Everything else (bridge, instance listener, worker) is unchanged. The existing paths that show the window
(`_on_remote` for show/toggle/capture, `_on_card`) already call `self.show()` when it's hidden.

**`main.py`** (`__main__`): a new flag `--hidden` ("start without showing the orb; used by MyNotion's Start").
- With `--hidden`: `instance.send("ping")` succeeds → print "Aria is already running." and exit 0.
- Without it: the existing `instance.send("show")` path.
- Then `run_with_overlay(..., visible=not args.hidden)`. With `--no-ui`, `--hidden` changes nothing.

To make this testable, the start decision moves into a small function
`main.already_running(hidden: bool, send=instance.send) -> bool`, which sends `ping` if hidden and `show` otherwise.

**`aria.sh`**: `--hidden` is passed on: `case "$1" in --hidden) ARGS="--hidden" ;;` before the start section, and the
log line `=== Aria started … args: --hidden ===` shows it.

**MyNotion `note/src/aria.ts`**: Start runs the launcher with `['--hidden']`. The arguments live in an exported
`LAUNCH_ARGS = ['--hidden']` constant, and the spawn moves into an exported
`launch(launcher, run = spawn)`, so a test can check the call without starting anything.

**`FEATURES.md`**: one line in the Aria panel section: "Start" opens her without the orb; Ctrl+Alt+Space shows it.

## Errors

- If a hidden start fails, nothing changes: the panel's existing 60 s wait and "Aria didn't start" message still apply.
- An old `aria.sh` without `--hidden` support would start her with the orb (it ignores the argument), which is today's
  behaviour, so nothing breaks.

## Tests

Aria (offscreen Qt, like `tests/test_overlay.py`):
- `ping` reaches the overlay's `_on_remote` and leaves a hidden overlay hidden, with the text box closed.
- `show` and `toggle` make a hidden overlay visible; a card makes it visible.
- `instance.COMMANDS` contains `ping`.
- `already_running(True, send)` sends `ping` only; `already_running(False, send)` sends `show`; both return what
  `send` returned.
- `run_with_overlay` itself isn't started in tests (it runs the Qt event loop). The `visible` switch is one `if`
  around `overlay.show()`, and the live check covers it.

MyNotion (`note/src/aria.test.ts`):
- `launch('/x/aria.sh', fakeSpawn)` calls `fakeSpawn('/x/aria.sh', ['--hidden'], {detached: true, stdio: 'ignore',
  cwd: '/x'})` and unrefs the child.

Live check (by Lala, since it starts the real Aria): quit Aria, press Start in MyNotion's panel → no orb, the panel
answers; Ctrl+Alt+Space → the orb appears.
