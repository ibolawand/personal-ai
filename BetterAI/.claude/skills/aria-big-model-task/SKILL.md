---
name: aria-big-model-task
description: Use when sending another kind of task to the big model (Claude via `claude -p`, Engines/BigModel.py), or when anything might leave the laptop. Holds the privacy rules: what may be sent, what never may, how fallback and marking work.
---

# Sending work to the big model

`Engines/BigModel.py` runs Claude through the locally signed-in Claude Code (`claude -p`, the user's subscription, no API key). The user chose this: local model talks and runs tools; a FIXED list of heavy text tasks goes out. Decide the list in code, never by the model.

## May be sent (one task's text only)
Note writing/organising/rewriting/translating/summarising, MyNotion's Explain and study buttons, quiz question writing, and "ask the big model / frag die große KI …" (the open note only if the question mentions it).

## NEVER sent
Mail (also summaries/drafts), Telegram, calendar/events, reminders, Aria's memory ("What Aria knows about me"), conversation history, camera/face data, screen contents, clipboard, file contents outside the asked task. "Save that as a note" from `last_reply` stays local (`local=True`) because that reply may hold mail.

## Adding a task
1. Build ONE prompt string containing only that task's text. Call `big.ask(prompt, "<label>")` (label shows in `~/.cache/aria/big_model.log`) or wrap a local `ask` with `big.or_local(local)`.
2. `None` return = off/offline/limit/failed → use the local model exactly as before. Never raise to the user; never retry in a loop (BigModel pauses 2 minutes after a failure).
3. Replies that Claude helped with end in `(via Claude)` (`Aria.handle_turn` → `big.marked`), but the mark is added after the turn is saved, so it never enters history. `tidy_reply` must leave it alone.
4. Keep Claude tool-less: the flags `--tools ""`, `--strict-mcp-config`, `--setting-sources ""`, `--no-session-persistence`, empty cwd, and no `ANTHROPIC_*` env. Don't relax them.
5. Tests in `tests/test_bigmodel.py` with a fake `run` (no real process). Test the fallback path and that excluded data is NOT in the sent input.
6. Update FEATURES.md ("Heavy text work goes to Claude") and the CLAUDE.md paragraph if the list changes. Tell the user what newly leaves the laptop.

Off switch: `ARIA_BIG_MODEL=0` in `Engines/.env`. Model: `ARIA_BIG_MODEL_NAME` (default `sonnet`).
