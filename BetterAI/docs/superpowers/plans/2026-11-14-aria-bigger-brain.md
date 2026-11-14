# Bigger brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aria's chat model becomes qwen3:30b-a3b-instruct-2507-q4_K_M, chosen by one setting, and all of her real-model checks pass again.

**Architecture:** `llm_engine.LLM_MODEL_DEFAULT` comes from `ARIA_MODEL` (default the 30 B); every user of the chat model already takes it from there (`main.LLM_MODEL`). The context window is raised to fit her largest request. Then the failing real-model checks are fixed one cause at a time — in code (routing, guards) where the cause is routing, in prompt/tool wording otherwise — re-running the whole check set each round.

**Tech Stack:** Ollama 0.40.7, qwen3 MoE, Python, pytest (`-m model` real-model checks).

**Spec:** `docs/superpowers/specs/2026-11-14-aria-bigger-brain-design.md`

## Global Constraints

- Model: `qwen3:30b-a3b-instruct-2507-q4_K_M`; `ARIA_MODEL=qwen3:8b` in `Engines/.env` switches back.
- Success: all real-model checks pass (`ARIA_MODEL_TESTS=1 .venv/bin/python -m pytest -m model`, currently 55), twice in a row; replies start within ~1 s and stream at ≥ 25 words/s; the model stays (almost) fully on the graphics card next to the avatar page.
- Prefer code over prompt wording (project pattern: decide in code, don't trust the model). Keep the existing guards.
- Don't change the BigModel (Claude) tasks. Don't delete the test models unless the user says so. Commit only when asked.

## Review Focus

1. `ARIA_MODEL` names a model that isn't pulled: Aria starts, the health check says which model is missing and how to get it (no crash, no silent hang).
2. Going back with `ARIA_MODEL=qwen3:8b`: still passes the fast suite and the real-model checks (nothing tuned so hard for the 30 B that the 8 B breaks).
3. A command answered with chatter instead of the tool ("organise this note" → self-introduction): covered by the existing tool checks; the reply must not claim an action without a tool (existing guard).
4. German messages: answered in German, tools still chosen right (existing German cases in the checks).
5. Memory pressure (a game running): no code change, but the real-app check notes speed with the avatar running.

---

### Task 1: One setting for the model

**Files:** Modify `llm_engine.py` (`LLM_MODEL_DEFAULT`, `LLMEngine.__init__` default), `Engines/UserStateEngine.py` (default arg), `Engines/Health.py` (models check uses the configured model), `tests/test_model.py` docstring; Test `tests/test_llm.py` (or the existing file that tests `llm_engine`; create `tests/test_llm_engine.py` if none).

**Interfaces — Produces:** `llm_engine.LLM_MODEL_DEFAULT = os.environ.get("ARIA_MODEL", "qwen3:30b-a3b-instruct-2507-q4_K_M")`; `LLMEngine(model=None)` → `LLM_MODEL_DEFAULT`.

- [ ] **Step 1: Failing tests**
  - `test_model_comes_from_aria_model(monkeypatch)`: `setenv("ARIA_MODEL", "qwen3:8b")`, `importlib.reload(llm_engine)` → `LLM_MODEL_DEFAULT == "qwen3:8b"`; without it → the 30 B name; reload back at the end.
  - `test_engine_defaults_to_the_configured_model`: `LLMEngine().model == llm_engine.LLM_MODEL_DEFAULT`.
  - Health: a test (in the existing health test file) that a missing configured chat model is reported by name with "ollama pull <name>".
- [ ] **Step 2:** run → fail. **Step 3:** implement. **Step 4:** fast suite passes.

### Task 2: Fit the context

- [ ] **Step 1:** Measure: run the real-model checks against the 30 B with `LLM_NUM_CTX=16384` while logging each request's `prompt_eval_count` (temporary print in `_round`, removed afterwards, or read Ollama's log); note the largest.
- [ ] **Step 2:** Set the default `NUM_CTX` to the smallest of 12288 / 16384 that fits the largest with ≥ 1 k to spare; check `ollama ps` shows ≥ 95 % GPU with it while the avatar page runs.
- [ ] **Step 3:** Re-run the real-model checks: the 5 "exceeds the available context" failures are gone. Record the remaining failures in the ledger.

### Task 3: Retune until every check passes

- [ ] For each remaining failure, one at a time: find the cause (superpowers:systematic-debugging: look at the request the model got — routed tools, history, prompt — and what it answered), fix the cause (routing regex / tool grouping / guard in code first; tool description or system prompt wording otherwise), re-run that check, then the whole real-model set and the fast suite.
- [ ] Each fix gets a ledger line: check, cause, fix. A fix that only helps the 30 B by hurting the 8 B is not a fix (spot-check the touched cases with `SWAP_MODEL=qwen3:8b`).
- [ ] Done when the whole set passes twice in a row.

### Task 4: Real app

- [ ] Restart Aria (aria-restart skill). Measure in her log (`[Speed]`/timing lines or `./aria.sh --report`): first word and total time for a few typed questions; `ollama ps` placement with the avatar shown; one screen question ("what's on my screen?") and the time until the chat model is back.

### Task 5: Docs, review

- [ ] FEATURES.md (her model, memory use, `ARIA_MODEL` to switch back, the measured speeds), CLAUDE.md first paragraph (model name), `aria-model-check` skill text if it names qwen3:8b. Fresh reviewer, fix pass, report.
