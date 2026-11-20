---
name: aria-bugfix
description: Use when Lala reports that Aria did something wrong or didn't do something ("she doesn't cancel the timer", "she said she'd do X but didn't", a crash, a wrong answer). How to find what happened in her log, find the root cause, fix it in code and pin it with a test.
---

# Fixing a bug in Aria

## 1. Find what actually happened
- Her log is `~/.cache/aria/aria.log` (all runs appended). It contains binary bytes: always `grep -a`.
  `grep -a -n -i "cancel\|timer" ~/.cache/aria/aria.log | tail -40`, then `sed -n 'A,Bp'` around the hits.
- Lines to look for: `You: ...` (typed), `[STT] Heard: '...' (confidence x)` (spoken; low confidence or
  `Shielded` means it was dropped), `[Tools] name({...})` (what the model called and with what), `Aria: ...` (reply),
  `[Aria] ... rewriting it`, tracebacks. A turn with no `[Tools]` line means no tool was called.
- Also: `~/.cache/aria/diagnostics.jsonl` (`problem(kind, detail)`), `~/.cache/aria/big_model.log`,
  `./aria.sh --report`.

## 2. Find the root cause (one hypothesis at a time)
Typical causes, in order of how often they were the real one:
- **The model picked the wrong tool or argument** (guessed the text to match, chose a reminder for a timer).
  Fix: decide it in code (see 3), don't reword the prompt and hope.
- **The right tool wasn't offered**: routing in `Engines/Tool_Engine.py` (`CORE`, `GROUPS` regexes,
  `schemas_for`). Check which groups the message matches.
- **The tool can't do it**: read the handler (e.g. `Engines/Reminders.py cancel_reminder` didn't see focus sessions).
- **She claimed an action without a tool call** ("Got it, I won't set the timer"): the claim guard in
  `Aria._handle_turn` only catches some phrasings.
- **Speech**: Whisper misheard or the turn was shielded (see the `[STT]` lines).
- **A code path before the model swallowed it** (confirmation, quiz, dictation, posture, open-in-MyNotion, cancel):
  order is in `Aria._handle_turn`.

## 3. Fix it in code
- The project's pattern: short, unambiguous commands are decided in code before the model (example:
  `Engines/Cancel.py` + `Aria._cancel_command`, called in `_handle_turn` after `_open_in_notion`). Pure decision
  function in its own module (testable without Aria), a thin method in `main.py` that carries it out, returns a plain
  sentence, saves the turn (`_save_turn`) and appends it to `self._recent`. Anything not clearly matched returns None
  so the model handles it as before.
- Changes to notes, events, reminders go through `self.undo.around(label, fn)` so "undo that" works
  (label reads as "Undone: <label>").
- Changing `BASE_PROMPT`, tool descriptions or routing: also follow `aria-model-check`.

## 4. Test it
- Reproduce the exact log case as a test first (it must fail before your fix).
- Pure decision: plain pytest on the function. In a turn: the `aria` fixture (`tests/conftest.py`: a real `Aria` via
  `__new__`, `FakeLLM` with `replies=[(text, used)]`, `prompts` records what reached the model); give it real parts
  where needed, e.g. `aria.reminders = Reminders(memory, on_due=lambda r: None)` with the `memory` fixture.
- `import main` at the top of a new test file (module level), as the other tests do: importing it first inside a
  fixture breaks (the sandbox has replaced `subprocess.Popen` by then).
- Also test what must NOT be caught (e.g. "cancel my meeting tomorrow" still goes to the model).

## 5. Finish
Update `FEATURES.md` where the behaviour is described; run the full suites; report per AGENTS.md. Restarting Aria
(`aria-restart`) is Claude's call unless the prompt says to.
