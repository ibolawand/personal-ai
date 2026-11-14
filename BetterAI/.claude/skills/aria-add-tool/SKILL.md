---
name: aria-add-tool
description: Use when adding or changing an Aria tool (anything declared with `_tool(...)` in Engines/Tool_Engine.py), or when a tool isn't offered/called for a phrase. Covers the checklist of places a tool must be registered, routed, tested and documented.
---

# Adding or changing an Aria tool

Aria decides things in code, not by trusting the 8B model. Propose a NEW feature to the user and wait for an OK first (CLAUDE.md); this skill is for building it after that.

## Checklist

1. **Backend first.** Put the logic in `Engines/<Name>.py`, no model, mic, camera or network needed for the logic. Anything checkable (maths, matching, parsing) is decided in code.
2. **Declare it once** in `ToolEngine._build()` in `Engines/Tool_Engine.py`: `_tool(name, description, handler, optional=..., **params)`. Register only when the backend exists (`if self.notion:` etc.). The description is what the model reads: start with the user's phrases ("'check exercise 4.15', 'stimmt mein Rechenweg?'"), say when NOT to use it, keep it short (8192-token context shared by ~110 tools).
3. **Route it.** Add it to the right set in `GROUPS` and extend that group's regex (English and German words) so `schemas_for(text)` offers it; or leave it ungrouped (always offered, costs context). Never put it in `CORE` unless it is needed on most turns.
4. **Gates.** Touches files, notes, mail, laptop or phone → add to `PROTECTED`. Changes notes/events/reminders → add to `UNDOABLE` and go through `Engines/Undo.py`. Risky or destructive → `confirmer.request(description, fn)`, never act directly. Allowed from Telegram? → `PHONE_TOOLS` in `Engines/Telegram.py` (default: no).
5. **Exact answers.** If the result must reach the user word for word (maths, a check, a count), return `FINAL_PREFIX + text` (`llm_engine.py`): the model doesn't reword it. Make sure `tidy_reply` leaves it unchanged (test it).
6. **Tests** (`tests/`, fast, sandboxed by `conftest.py`): the backend, the tool through `ToolEngine(notion=notion).execute(...)`, and that `schemas_for("<phrase>")` offers it for each phrase (English + German). Use the `aria`, `notion`, `memory` fixtures; never open the real `aria_memory.db` or MyNotion's DB.
7. **Model check.** Add 2–3 real phrases to `tests/test_model.py`, then run the `aria-model-check` skill. A changed description or routing has caused "I'll do it" replies without a tool call before.
8. **FEATURES.md.** Add or update the feature entry (what it does, example phrases, implementing file). Required by CLAUDE.md on every feature change.
9. Run `.venv/bin/python -m pytest` (all fast tests must pass).

## Pitfalls seen here
- A tool that isn't in a group whose regex matches the phrase is invisible to the model: the symptom is "I can't do that". `main.py` retries with all tools, which hides the routing bug in logs (`aria.sh --report`: `missing_tool`).
- Don't change the system prompt (`BASE_PROMPT`) to fix one phrase; fix the description or add a code path.
- Per-turn data goes after the user message, never into the system prompt (prompt cache).
