---
name: aria-model-check
description: Use after changing Aria's system prompt (BASE_PROMPT in main.py), tool descriptions, tool routing (GROUPS/regex) or tool parameters, and before claiming such a change works. Runs the real-model checks and reads their results.
---

# Real-model checks for Aria

The fast tests never call the model. Prompt/tool-description/routing changes have broken Aria before (the model said "I'll turn the volume down" without calling a tool), so they need the real `qwen3:8b`.

## Steps

1. Ollama must be running with `qwen3:8b` loaded: `ollama ps`. If Aria is running she holds the GPU model; that's fine (same model), but close MyNotion's heavy work first if it's slow.
2. Run everything:
   ```bash
   ARIA_MODEL_TESTS=1 .venv/bin/python -m pytest -m model -q
   ```
   Or only the new phrases: `... -m model -k "<word>"`. About a minute.
3. Fast suite too: `.venv/bin/python -m pytest -q` (≈15 s).
4. Read failures properly. The model is non-deterministic: rerun a failing test 2–3 times. A phrase that fails every time is a real regression; one that flips is flaky.
5. Known flaky/pre-existing (fail without your change too): "read the email from Mr Huber", "reply to Sara that I'm in". Check with `git stash`-free comparison: temporarily restore `Engines/Tool_Engine.py` from HEAD (`git show HEAD:BetterAI/Engines/Tool_Engine.py`), run, put your version back. Do NOT use `git stash -u`: the root-owned stray dir `MyNotion/note/noted` breaks it.
6. Report exactly what passed and failed. Don't say "works" from fast tests alone when routing or prompts changed.

## Adding a case
`tests/test_model.py` has phrase lists per tool with `Stub` backends that record calls. Add the user's real phrasings, English and German, including sloppy ones ("stimmt mein Rechenweg?").
