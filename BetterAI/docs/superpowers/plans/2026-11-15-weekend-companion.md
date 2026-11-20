# Weekend companion implementation plan

**Goal:** on free days, the companion starts chats in a bubble (topics picked in code, wording by the local model),
nudges now and then, and moves more.

**Spec:** `docs/superpowers/specs/2026-11-15-weekend-companion-design.md`

## Files

- Create `Engines/Openers.py`. It holds the pure rules:
  - `free_day(now, span)`
  - `Openers` (timing, back-off, daily cap, topic picking)
  - `prompt_for(topic)`
  - `clean_line(text, fallback)`
- Modify `Engines/Companion.py`:
  - new probe `today_items`
  - `Reactions.pick(..., body_every, lines)`
  - openers run in `_react` on free days
  - "answered" is detected through the `awake` → `after_conversation(talked)` path
- Modify `main.py`:
  - `Aria.write_opener(prompt) -> str | None`: a model call without tools, skipped when awake or the turn lock is
    busy
  - `Aria.remember_said(text)`: history, like the announcements
- Tests: `tests/test_openers.py`, plus additions to `tests/test_companion.py`
- Docs: `FEATURES.md`

## Tasks

1. **Openers rules and tests.**
   - first opener 10 min after the wake
   - a gap of 25–45 min after that, doubled per ignored opener beyond the first, capped at 2 h
   - at most 8 a day
   - a nudge never twice in a row
   - never the same topic twice in a row
   - templates as the fallback
2. **Companion wiring and tests:**
   - openers only on free days
   - none in a call or game, fullscreen, quiet hours or while Aria is awake
   - app lines are replaced by openers on free days
   - gestures every 2.5 min on free days
   - the opener is remembered in history
   - an answer resets the back-off
3. **Aria methods, FEATURES.md, full test run.**

## Review focus

- The model is slow or busy: the opener must not block Aria waking (it is phrased off the companion lock, in its own
  thread).
- The model returns a robotic, long or multi-line reply: use the template.
- Aria wakes while the opener is being phrased: don't show it.
