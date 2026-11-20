# AGENTS.md (for Codex)

You do the hands-on work in this project: building features, fixing bugs, debugging, writing tests and docs. Claude
writes your prompts and the skills in `.agents/skills/`, and checks your result afterwards. Work on your own until the
task is done; don't stop to ask unless the prompt is truly ambiguous.

**Read `CLAUDE.md` first.** It is the project guide: what Aria is, commands, configuration, architecture, the code
paths before the model, tool routing, prompt layout, the UI threading, tests and fixtures. Then use the skill that
fits the task:

| Task | Skill |
|---|---|
| Fixing a bug or a "she doesn't do X" report | `aria-bugfix` |
| Anything in `ui/avatar/` (gestures, poses, timing, the look) | `aria-avatar-animation`, then `senior-3d-audio-engineer` |
| Looking at her: screenshots, contact sheets, measuring hand positions | `aria-film` |
| Adding or changing a tool (`_tool(...)` in `Engines/Tool_Engine.py`) | `aria-add-tool` |
| Changing `BASE_PROMPT`, tool descriptions or routing | `aria-model-check` (needs Ollama; say so if you can't run it) |
| Sending a task to Claude (`Engines/BigModel.py`) | `aria-big-model-task` (privacy rules) |
| Voice, microphone, wake word, TTS, latency, audio | `senior-3d-audio-engineer` |
| Restarting Aria after a change | `aria-restart` |

## Rules

- Never commit, push, branch or otherwise touch git. Never edit `Engines/.env` or any `.db` file, and never open the
  real `aria_memory.db` or MyNotion's DB (tests fail if you do; `tests/conftest.py` sandboxes everything).
- Decide in code, not by trusting the small local model (see CLAUDE.md). Pure functions for decisions, a thin layer
  for I/O and rendering.
- Smallest change that fully solves it. Follow the file's existing style and comment voice: plain sentences saying
  what she does and why. Don't reformat or refactor code you aren't changing.
- Every change gets tests that fail without it (Python: pytest with the fixtures in `tests/conftest.py`; avatar:
  `node --test ui/avatar/*.test.mjs`). Tests never need the model, mic, camera or network.
- Update `FEATURES.md` when what she does changes. Add to `IMPROVEMENTS.md` only when the prompt asks.
- New user-facing features are proposed by Claude to Lala first; build what the prompt asks, not extra features.

## Finishing

1. Run `.venv/bin/python -m pytest -q` and `node --test ui/avatar/*.test.mjs` (both must pass; if the sandbox blocks
   one, say exactly what failed and why).
2. End with a short report, at most ~15 lines: what you changed (files, functions, numbers), the tests you added,
   what you could not verify (and the command to check it, e.g. a `tools/avatar_look.py` call). No code dumps.
