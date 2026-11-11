# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Aria: a local, always-on desktop assistant for Linux Mint (Python). It is a general-purpose assistant, not school-only. A local LLM (Ollama, `qwen3:8b`, native tool calling) drives about 110 tools: MyNotion notes and calendar, reminders, Spotify, laptop control, files, mail, WebUntis, Telegram, weather, web search (SearXNG), an Arduino LED strip and Home Assistant. It has a PySide6 overlay orb, optional wake word + Whisper STT + Kokoro TTS, and face recognition through the camera.

`FEATURES.md` describes every feature with example phrases and the file that implements it. **Update it whenever a feature is added or changed.** `IMPROVEMENTS.md` logs past autonomous improvements and known open items. Propose new functionality to the user and wait for an OK before building it.

## Commands

All Python runs through the project venv at `.venv/`.

```bash
.venv/bin/python -m pytest                         # all fast tests (~15 s): no model, mic, camera or network
.venv/bin/python -m pytest tests/test_notion.py    # one file
.venv/bin/python -m pytest tests/test_notion.py -k clash   # one test
ARIA_MODEL_TESTS=1 .venv/bin/python -m pytest -m model     # real-model checks (needs Ollama running)

.venv/bin/python main.py            # overlay + text input
.venv/bin/python main.py --voice    # + wake word and microphone
.venv/bin/python main.py --no-ui    # terminal only
.venv/bin/python -m ui.overlay      # overlay demo, no AI attached

./aria.sh [--toggle|--capture|--quit|--report N|--untis|--telegram]   # everyday launcher; logs to ~/.cache/aria/aria.log
./install_desktop.sh                # menu entry, autostart, Ctrl+Alt+Space / Ctrl+Alt+N hotkeys
searxng/start.sh                    # local web search in Docker (falls back to Wikipedia/DDG without it)
```

Run the `-m model` checks after changing the system prompt (`BASE_PROMPT` in `main.py`), tool descriptions or routing. Those changes have caused regressions before: the model said "I'll turn the volume down" without calling a tool.

## Configuration

Settings come from `Engines/.env` (gitignored), which `main.py` loads explicitly. The root `.env` is not the one main.py reads. Keys include `DB_PATH` (MyNotion's SQLite DB; currently `~/.config/MyNotion/noted.db`, older docstrings still say `../MyNotion/note/noted.db`), Spotify keys, `ARIA_OWNER`, `FILE_ROOTS`, `CAMERA_INDEX`, `VISION_MODEL`, `LLM_NUM_CTX`, `ARIA_ARGS` (e.g. `--voice`) and `ARIA_*` behaviour toggles. `aria_memory.db` in the repo root holds Aria's own long-term memory and message history (`database.py`).

## Architecture

**`main.py` → `Aria` class** is the hub. `__init__` builds every engine through `self._try(label, factory)`, so a missing device or service only disables that feature instead of crashing. It then passes the engines into `ToolEngine`. `run()` is the main loop: wake word/STT, or the text box, plus background loops for reminders, mail, presence, battery and so on.

**One turn = `Aria._handle_turn`.** Before the LLM sees anything, several **code paths** intercept the message, in this order: a pending yes/no confirmation (`Engines/Confirm.py`, matched by regex, never by the LLM), an active quiz, dictation, posture reference, "open in MyNotion". Only then is the LLM called. After the call, code-level guards run:
- If the message was a command and the reply claims an action but no tool was called → retry, insisting on the tool.
- If the reply sounds like "I can't" and routing hid tools → retry with all tools.
- An empty reply, a stock-assistant reply ("I'm here to help") or a parroted reply is rewritten (`ROBOTIC_RE`, `_norm_reply`), and `tidy_reply` strips filler and tacked-on offers.

The project's guiding pattern is to **decide things in code instead of trusting the small model**: confirmations, maths (`Engines/Calc.py`), clothing advice from the weather, quick-capture filing, and so on. Keep that approach when fixing model misbehaviour.

**`llm_engine.LLMEngine.chat_with_tools`** runs up to 3 tool rounds against Ollama and streams text through `on_text`, so `SentenceStreamer` can speak the first sentence early. It records `last_trace`. The tool calls and results of the last 6 turns are replayed as history (`Aria._recent`), which keeps the model using tools.

**`Engines/Tool_Engine.py`** declares every tool once with `_tool(name, description, handler, optional=..., **params)` inside `_build()`. A tool is only registered when its backend exists. **Tool routing:** `schemas_for(text, recent_tools)` sends `CORE` tools, any ungrouped tool, and only the `GROUPS` whose regex matches the message or that were used in the last two turns. This keeps the prompt small (8192-token context). A new tool must be added to the right group (and its regex extended if needed), or left ungrouped so it is always offered. Telegram messages are restricted to `PHONE_TOOLS` (`Engines/Telegram.py`). Risky actions call `confirmer.request(description, fn)` instead of acting. Changes to notes, events and reminders go through `Engines/Undo.py` snapshots.

**Prompt layout:** `ContextBuilder.build_system_prompt` gives a stable system prompt. Anything that changes per turn (time, presence, "[Right now: …]", clipboard) is appended to the *user* message, so Ollama can reuse its prompt cache. Keep that split.

**MyNotion integration** (`Engines/NotionEngine.py`, `NoteWriter.py`, `MemoryNote.py`) writes directly into the separate MyNotion app's SQLite DB (the path in `DB_PATH`). MyNotion's source is at `../../MyNotion`. The `BetterAI/MyNotion/` folder is an empty, root-owned stray directory, not the app or its DB. The git root is the parent `personal-ai/`; this project is the `BetterAI/` subfolder of it. The tables are `notes`, `FOLDERS`, `EVENTS` and `USERS`; `tests/conftest.py` has the schema. The note "What Aria knows about me" is synced both ways with `aria_memory.db`.

**UI threading:** Qt owns the main thread (`ui/overlay.py`). Aria runs in a worker thread and talks to the UI through `OverlayBridge` signals. `NullUI` in `main.py` defines the UI interface (`set_state`, `message`, `show_card`, …). `ui/instance.py` enforces a single running instance through a Unix socket; `aria.sh --toggle/--capture/--quit` send commands over that socket.

**MyNotion's Aria panel** talks to Aria through `ui/app_bridge.py` (a private Unix socket, one JSON object per line; the protocol is in its docstring) and `Aria.answer_app`: a normal turn under the turn lock with all tools, never spoken, with the open note's text appended to the prompt in code. The other end is `note/src/aria.ts` and `note-frontend/src/app/aria-panel/` in `../../MyNotion`. "Select text, ask Aria" uses the same socket with an `edit` request: `Aria.edit_app` → `NoteWriter.rework` returns a proposal as HTML and saves nothing; MyNotion applies it in the editor on Accept. A chat request with `"tools": false` is answer-only (used for Explain). Specs and plans for this work are in `docs/superpowers/`.

**Diagnostics:** `Engines.Diagnostics.timing(...)` / `problem(kind, detail)` log to `~/.cache/aria`. `aria.sh --report` summarises the log.

## Tests

`tests/conftest.py` sandboxes everything automatically:
- `database.DB_FILE` points to a temp file.
- Opening the real `aria_memory.db` or MyNotion's DB **fails the test**.
- `XDG_CACHE_HOME` is redirected.
- `subprocess.Popen` and app launches are recorded instead of run.
- gsettings is faked.

Useful fixtures:
- `aria`: a real `Aria` built with `__new__`, with devices stubbed and `FakeLLM` scripted through `replies=[(text, used)]` / `chats=[...]`.
- `notion`: a `NotionEngine` on a fresh MyNotion-schema DB.
- `memory`: an `AriaMemory` on the temp DB.

New tests should follow this pattern and never need the model, mic, camera or network.
