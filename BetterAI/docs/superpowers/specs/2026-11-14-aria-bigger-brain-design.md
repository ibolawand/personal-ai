# Aria's bigger brain: switch the chat model to qwen3:30b-a3b-instruct

Status: short design, approach chosen by the user (2026-11-14).

## Why
The user wants Aria "independently smart": smarter on her own, on the laptop, not by handing more to Claude. Tested on
real school questions (matrices, differential equations, SQL, C#, a study plan, a reasoning trap), her model
qwen3:8b got 6/8 and failed both questions needing actual thinking; qwen3:30b-a3b-instruct-2507 (a mixture-of-experts
model: 30 B parameters, ~3 B used per word) got 7/8 at the same speed (30–40 words/s vs 33; first word ~0.6 s), 97 %
on the 8 GB graphics card. As a straight swap it passes only 40 of her 55 real-model checks (5 context overflows,
10 tool mistakes, e.g. claiming "I've added it" without calling the tool), because her prompt and tool descriptions
were tuned on qwen3:8b.

## Goal
Aria's chat model is qwen3:30b-a3b-instruct-2507-q4_K_M and all 55 real-model checks pass again
(`ARIA_MODEL_TESTS=1 pytest -m model`), with replies still starting within ~1 s and at ≥ 25 words/s.

## Non-goals / anti-goals
- Not a mix of models (approach B), not more Claude. The Claude tasks (BigModel) stay as they are for now.
- Failure even if it "works": she claims actions without doing them, the first word takes several seconds, the
  model ends up split onto the processor, or she becomes chatty/odd where she was crisp.

## Approaches (chosen: A)
- **A (chosen): switch fully and retune** until the checks pass. Smarter everywhere, one brain.
- B: commands on qwen3:8b, thinking questions on the 30 B, chosen in code. Reliable at once, but 4–14 s pauses
  whenever she switches models (measured).
- C: the 30 B only replaces Claude for the heavy text tasks. Everyday talk stays as smart as now.

## Design
1. **One setting for the model**: `ARIA_MODEL` in `Engines/.env` (default the 30 B), read in `llm_engine.py`;
   `ARIA_MODEL=qwen3:8b` goes back in one line. Everything that uses `LLM_MODEL` (chat, quiz, note writer,
   dictation, mood check) follows it.
2. **Context**: raise `LLM_NUM_CTX` until her largest request fits (measured, likely 12–16 k), checking the model
   stays fully on the graphics card next to the avatar page and that Whisper's fallback still works.
3. **Retune** the system prompt and tool descriptions against the 10 failing checks, one cause at a time, re-running
   the whole check set each round (the existing guards — "claims an action without a tool → retry" — stay).
   Prefer fixing in code (routing, guards) over prompt wording, per the project's pattern.
4. **Speed and memory check** in the real app with the avatar running; the vision model swap (screen questions)
   still works (it reloads the chat model afterwards: now ~7–14 s instead of ~3 s; measure and say so).
5. FEATURES.md / CLAUDE.md updated (model name, memory use, how to switch back).

## Left to the builder
Exact prompt and description wording, the context number, and whether a check reveals a real routing bug (fixed in
code) vs. wording. The two losing test models (qwen3:14b, qwen3:30b-a3b thinking) are deleted only if the user says so.
