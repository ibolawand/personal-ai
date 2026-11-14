# Companion wake after school + app awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After school Aria quietly wakes herself into a "companion" mode (avatar on screen, no voice, no LLM), stays while the laptop is used, and now and then reacts to the app in front with a gesture, a glance and, rarely, one bubble line.

**Architecture:** A new `Engines/Companion.py` holds pure, tested rules (school over? may she wake? doze? which app kind? which reaction?) and a `Companion` loop that polls injected probes every 3 s and drives the UI through three calls: `ui.set_state("companion"|"sleeping")`, `ui.message("aria", line)`, `ui.avatar_act(name)` / `ui.glance(x, y, seconds)`. The overlay treats "companion" like an awake idle state (avatar shown, page state `idle`). Aria's conversation loop is untouched except `_go_to_sleep(by_user=...)`.

**Tech Stack:** Python 3.12, PySide6 overlay, existing X/dbus helpers (`Engines/Desk.py`, `Engines/Activity.py`), WebUntis (`Engines/Untis.py`), Open-Meteo (`Engines/Weather.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-aria-reacts-and-props-design.md` (piece 1 only; pieces 2–5 get their own plans).

## Global Constraints

- No camera; nothing read from the screen, window titles or audio leaves the laptop or is stored.
- Companion lines and the wake line are **never spoken**: only `ui.message("aria", ...)` (bubble). No LLM call anywhere in this plan.
- Never during a lesson (timetable), never in quiet hours (`Desk.in_quiet_hours`), never while fullscreen or a call (`Desk.fullscreen_app`, `Desk.mic_in_use_by_others`, call app in front), never while the screen is locked.
- Timetable unreadable → weekdays count as school until 16:00; weekends free.
- Self-wake at most once per day, plus again after ≥ 2 h without input. Companion dozes after 10 min without input.
- Bubble line at most every 30 min; body reaction at most every 5 min; nothing in the first 60 s after switching app; the same kind never gets two lines in a row; lines don't repeat until that kind's bank is used up.
- An explicit "go to sleep" (said/typed, or the menu) turns companion off until the user was away ≥ 2 h or the next day.
- `ARIA_COMPANION=0` in `Engines/.env` turns the whole feature off.
- Commit only when the user asks (project rule): no commit steps below. Update `FEATURES.md` (and `CLAUDE.md` architecture paragraph) in the last task.

## Review Focus

1. Aria asleep with `option == 2` (voice mode): companion must not open the microphone or start a conversation; only the wake word/typing wakes her for real.
2. The user types while she's in companion: the normal wake runs with no LLM greeting (input is waiting), and after that conversation she returns to companion, not the orb.
3. A lesson starting while she is in companion (afternoon lessons after a free period): she must go back to sleep.
4. Probes failing (dbus/xprop missing → `idle_seconds()` returns None, Untis raises): treat as "can't tell" → no self-wake, never a crash in the loop.
5. Aria's own overlay or MyNotion's Aria panel in front (wm class `aria`/`python3`): not an app to react to.

---

### Task 1: School hours and the wake/doze rules

**Files:**
- Modify: `Engines/Untis.py` (new public method next to `school_day`)
- Create: `Engines/Companion.py`
- Test: `tests/test_companion.py`

**Interfaces:**
- Produces: `Untis.school_span(day: dt.date) -> tuple[int, int] | None` — (first start, last end) as HHMM ints of the non-cancelled blocks (`_blocks`), `None` when no lessons; raises like `_lessons` (no login → raises `LoginError(NOT_SET_UP)`).
- Produces in `Engines/Companion.py`:
  - `UNKNOWN = object()` (timetable couldn't be read)
  - `school_over(now: dt.datetime, span) -> bool` — `span` is a `(start, end)` tuple, `None`, or `UNKNOWN`
  - `may_self_wake(now: dt.datetime, *, over: bool, idle_s: float | None, away_s: float, last_wake: dt.datetime | None, busy: bool) -> bool`
  - `should_doze(idle_s: float | None, *, over: bool, busy_quiet: bool) -> bool`
  - constants `ACTIVE_S = 10`, `AWAY_S = 2 * 3600`, `DOZE_S = 600`, `FALLBACK_END = 1600`

- [ ] **Step 1: Write the failing tests** in `tests/test_companion.py`

```python
import datetime as dt
from Engines.Companion import school_over, may_self_wake, should_doze, UNKNOWN

D = dt.datetime(2026, 11, 16, 15, 0)        # a Monday

def test_school_over_after_last_lesson_only():
    assert not school_over(D.replace(hour=13, minute=20), (755, 1325))
    assert school_over(D.replace(hour=13, minute=25), (755, 1325))
    assert not school_over(D.replace(hour=7), (755, 1325))          # morning before school isn't "after school"
    assert school_over(D, None)                                     # no lessons today (holiday)

def test_unknown_timetable_is_school_until_four_on_weekdays():
    assert not school_over(D.replace(hour=15, minute=59), UNKNOWN)
    assert school_over(D.replace(hour=16), UNKNOWN)
    assert school_over(dt.datetime(2026, 11, 15, 10, 0), UNKNOWN)  # Sunday

def test_self_wake_once_a_day_or_after_two_hours_away():
    kw = dict(over=True, idle_s=2, away_s=0, busy=False)
    assert may_self_wake(D, last_wake=None, **kw)
    assert not may_self_wake(D, last_wake=D.replace(hour=14), **kw)
    assert may_self_wake(D, last_wake=D.replace(hour=14), **{**kw, "away_s": 2 * 3600})
    assert may_self_wake(D, last_wake=D - dt.timedelta(days=1), **kw)

def test_no_self_wake_in_school_idle_busy_or_unknown_idle():
    kw = dict(away_s=0, last_wake=None)
    assert not may_self_wake(D, over=False, idle_s=2, busy=False, **kw)
    assert not may_self_wake(D, over=True, idle_s=60, busy=False, **kw)    # not using the laptop right now
    assert not may_self_wake(D, over=True, idle_s=2, busy=True, **kw)      # fullscreen / call / locked / quiet hours
    assert not may_self_wake(D, over=True, idle_s=None, busy=False, **kw)  # can't tell

def test_doze_after_ten_idle_minutes_a_lesson_or_quiet_hours():
    assert not should_doze(599, over=True, busy_quiet=False)
    assert should_doze(600, over=True, busy_quiet=False)
    assert should_doze(5, over=False, busy_quiet=False)
    assert should_doze(5, over=True, busy_quiet=True)
    assert should_doze(None, over=True, busy_quiet=False)
```

Add in `tests/test_untis.py` (existing file; follow its fake-session pattern for `_lessons`) a test that `school_span` returns `(755, 1325)` for lessons 0755–0845 and 1235–1325 plus a cancelled 1330–1415 lesson, and `None` for a day with no lessons.

- [ ] **Step 2: Run, expect failures**

Run: `.venv/bin/python -m pytest tests/test_companion.py tests/test_untis.py -q`
Expected: FAIL (`ModuleNotFoundError: Engines.Companion`, `AttributeError: school_span`)

- [ ] **Step 3: Implement** `Untis.school_span` (from `self._blocks(self._lessons(day))`), and the three functions. `should_doze` arg `busy_quiet` = quiet hours or screen locked (fullscreen alone doesn't send her to sleep).

- [ ] **Step 4: Run, expect pass** — same command, all PASS.

---

### Task 2: App kinds, reactions and lines

**Files:**
- Modify: `Engines/Companion.py`
- Test: `tests/test_companion.py`

**Interfaces:**
- Produces:
  - `app_kind(wm_class: str | None, title: str) -> str | None` — one of `"code" "video" "browser" "mynotion" "terminal" "call" "music" "chat" "docs" "game"`, or `None` for Aria herself / nothing in front / unknown apps. Video = a browser or player whose title matches `Activity.WATCH_RE` (import it). Call = zoom, teams, discord with "call"/"voice" in title, or a browser title with "meet"/"jitsi"/"zoom". `"mynotion"` before `"browser"`.
  - `LINES: dict[str, list[str]]` — 4–6 lines per kind except `call`/`game` (none). Her voice: playful, short (≤ 8 words), English, emoji rare. e.g. code: "coding again? don't forget to commit 👀", video: "ooh, what are we watching?", mynotion: "studying? I'm proud of you".
  - `BODY: dict[str, str]` — kind → existing page gesture (`think`, `curious`, `smile`, `lookAround`, `rock`, `lean`, `stretch`); `call`/`game` absent.
  - `class Reactions(rng=random)` with `pick(kind: str | None, now: float, in_app_s: float) -> tuple[str | None, str | None]` → (gesture, line). Rules from Global Constraints (5 min body, 30 min line, 60 s settle, no same kind twice in a row for lines, no-repeat bag per kind). A line always comes with its kind's gesture.
  - `wake_line(now: dt.datetime, test: dict | None, rain: bool | None) -> str` — `test` is a `TestPrep` card dict (`subject`, `when`, `days`); e.g. "school's done! Maths test Thursday, btw" / "hey, you're back!" (not first wake of the day) / "+ take an umbrella later ☔" when `rain`. ≤ 12 words.

- [ ] **Step 1: Write the failing tests**

```python
from Engines.Companion import app_kind, Reactions, LINES, wake_line

def test_app_kinds():
    assert app_kind("code", "main.py - BetterAI - Visual Studio Code") == "code"
    assert app_kind("firefox", "Lofi beats - YouTube — Mozilla Firefox") == "video"
    assert app_kind("firefox", "Stack Overflow — Mozilla Firefox") == "browser"
    assert app_kind("mynotion", "MyNotion") == "mynotion"
    assert app_kind("zoom", "Zoom Meeting") == "call"
    assert app_kind("aria", "") is None and app_kind("python3", "Aria") is None and app_kind(None, "") is None

def test_reaction_rules():
    r = Reactions()
    assert r.pick("code", 0, in_app_s=30) == (None, None)            # just switched: wait
    g, line = r.pick("code", 100, in_app_s=100)
    assert g == "think" and line in LINES["code"]
    assert r.pick("code", 200, in_app_s=200) == (None, None)          # body cooldown
    g, line = r.pick("video", 100 + 6 * 60, in_app_s=90)
    assert g and line is None                                         # body ok, line still cooling down
    _, line = r.pick("video", 100 + 31 * 60, in_app_s=90)
    assert line in LINES["video"]
    assert r.pick("call", 10**6, in_app_s=999) == (None, None)

def test_lines_do_not_repeat_until_bank_used_and_kind_alternates():
    r, seen, t = Reactions(), [], 0
    for i in range(len(LINES["code"]) * 2):
        t += 31 * 60
        kind = "code" if i % 2 == 0 else "video"
        _, line = r.pick(kind, t, in_app_s=999)
        if kind == "code":
            seen.append(line)
    n = len(LINES["code"])
    assert len(set(seen[:n])) == n

def test_wake_line():
    test = {"subject": "Maths", "when": "Thursday", "days": 3}
    assert "Maths" in wake_line(D, test, rain=False)
    assert "umbrella" in wake_line(D, None, rain=True)
    assert len(wake_line(D, None, rain=None).split()) <= 12
```

- [ ] **Step 2: Run, expect failures** — `.venv/bin/python -m pytest tests/test_companion.py -q` → ImportError.
- [ ] **Step 3: Implement** the four names above.
- [ ] **Step 4: Run, expect pass.**

---

### Task 3: The overlay shows her in companion mode and takes acts and glances

**Files:**
- Modify: `ui/overlay.py` (`STATE_COLORS`, `_shows_avatar`, `OverlayBridge`, the 15 Hz look feed at ~line 659)
- Modify: `ui/avatar_view.py` (`AvatarLink.act`)
- Modify: `main.py` (`NullUI`: `avatar_act`, `glance` no-ops)
- Test: `tests/test_avatar.py`

**Interfaces:**
- Produces:
  - `AvatarLink.act(name: str)` → `window.aria.act(<json name>)`, a moment (never replayed, like `hop`).
  - `OverlayBridge.avatar_act(name: str)` and `OverlayBridge.glance(x: int, y: int, seconds: float)` (screen px), thread-safe through new signals `actRequested = Signal(str)`, `glanceRequested = Signal(int, int, float)`.
  - UI state `"companion"`: avatar shown (`_shows_avatar` true), page state `idle` (`AvatarLink.set_state("idle")`), orb colours = `STATE_COLORS["listening"]` if painted; the right-click "go to sleep" item enabled.
  - While a glance is active, the look feed aims at the glance point instead of the cursor (same maths, with the point mapped from global).

- [ ] **Step 1: Write the failing tests** (follow the existing overlay fixtures in `tests/test_avatar.py`):
  - `test_companion_state_shows_her_idle`: overlay with a ready fake link; `bridge.set_state("companion")` → `_shows_avatar()` is True and the link's last state is `"idle"`.
  - `test_avatar_act_reaches_the_page`: `bridge.avatar_act("think")` → link ran `window.aria.act("think")`; not replayed after a page reload.
  - `test_glance_overrides_cursor_then_expires`: glance at a point far left for 2 s → next look feed x < 0 regardless of cursor; after 2 s (monkeypatched clock) it follows the cursor again.
- [ ] **Step 2: Run, expect failures** — `.venv/bin/python -m pytest tests/test_avatar.py -q -k "companion or avatar_act or glance"`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole avatar test file, expect pass.**

---

### Task 4: The companion loop, wired into Aria

**Files:**
- Modify: `Engines/Companion.py` (class `Companion`)
- Modify: `Engines/Weather.py` (`rain_soon`)
- Modify: `main.py` (build/start, `_go_to_sleep(by_user=...)`)
- Test: `tests/test_companion.py`, `tests/test_weather.py` (or the existing weather test file)

**Interfaces:**
- Consumes: Task 1 and 2 functions; Task 3 UI calls; `Desk.idle_seconds/fullscreen_app/mic_in_use_by_others/screen_locked/in_quiet_hours`; `Activity.active_window()`; `Untis.school_span`; `TestPrep.cards()`; `desktop_windows` to find the active window's rect for the glance (`window_rect(wid)`; get the wid from `_NET_ACTIVE_WINDOW` through `desktop_windows._x()`; add `active_window_rect() -> Win | None` there).
- Produces:
  - `Weather.rain_soon(hours: int = 3, threshold: int = 60) -> bool | None` — hourly `precipitation_probability` from Open-Meteo for the next `hours`; `None` on any error or no home city. Cached 30 min.
  - `class Companion(aria, ui, probes: Probes, clock=time.time, now=dt.datetime.now)` with `start()` (daemon thread, `tick()` every 3 s, exceptions printed and swallowed), `tick()`, `dismissed()`.
  - `Probes` — a small dataclass of callables with the real defaults above, so tests pass fakes: `idle_s, active_window, active_rect, fullscreen, on_call, locked, quiet, school_span, next_test, rain_soon`. `school_span` probe returns `UNKNOWN` when Untis raises or isn't configured; `next_test` returns the first `TestPrep.cards()` entry or None; timetable/test/rain probes cached ≥ 10 min.
- Behaviour per `tick()` (Aria asleep = `not aria.awake`):
  - Track `away_s`: the longest idle seen since the last input (resets once input is seen).
  - Asleep, UI not in companion, `may_self_wake` → `ui.set_state("companion")`; if it's a new wake (not a return after a conversation) → `ui.message("aria", wake_line(...))`, `ui.avatar_act("wave")`, record `last_wake`.
  - Asleep and **returning**: companion was on before Aria woke for a conversation, she's asleep again (not by user), school still over, not busy → back to `"companion"` with no line.
  - In companion and `should_doze` → `ui.set_state("sleeping")`, companion off.
  - In companion, not fullscreen/call: `Reactions.pick(app_kind(...), clock(), in_app_s)` → `avatar_act(gesture)`, `glance(center of active rect, 2.5)` with the gesture, `ui.message("aria", line)` when a line.
  - `dismissed()` (called by `Aria._go_to_sleep(by_user=True)`): companion off; no self-wake until `away_s ≥ AWAY_S` or the next day.
  - Never touches the UI while `aria.awake`.
  - `ARIA_COMPANION=0` → `start()` does nothing.
- `main.py`: `self.companion = self._try("Companion", lambda: Companion(self, self.ui, Probes.real(self)))`, started with the other background loops; `_go_to_sleep(self, line=None, by_user=False)` → when `by_user`, `self.companion.dismissed()`; pass `by_user=True` at the `wants_sleep` call and the `_sleep_request` call in `run()`.

- [ ] **Step 1: Write the failing tests** with a fake aria (`awake` attribute), a recording fake UI (`set_state`, `message`, `avatar_act`, `glance`) and fake probes on a fake clock:
  - `test_wakes_quietly_after_school_with_a_line_and_wave` — Monday 15:00, span (755, 1325), idle 2 → states `["companion"]`, one message, act `"wave"`; nothing spoken (fake aria has a `speak` that fails the test if called).
  - `test_no_wake_during_lesson_or_when_busy` — span (755, 1600) at 15:00 → no UI calls; fullscreen → none; on_call → none.
  - `test_dozes_after_ten_idle_minutes` and `test_dozes_when_afternoon_lesson_starts`.
  - `test_returns_after_conversation_without_line` — companion on → `aria.awake=True` (tick: no UI calls) → `aria.awake=False` → state `"companion"` again, no new message.
  - `test_dismissed_stays_off_until_two_hours_away` — `dismissed()` → no wake at idle 2; after a tick with idle 7200 then idle 1 → wakes.
  - `test_reacts_to_app_with_gesture_glance_and_line` — in companion, active window `("code", "x - Visual Studio Code")` for 120 s → `avatar_act("think")`, a `glance`, a message from `LINES["code"]`.
  - `test_probe_failures_never_crash` — every probe raises / returns None → `tick()` returns, no UI calls.
  - `test_voice_mode_never_opens_mic` — fake aria with `option=2`; after a self-wake, `aria.ui.set_mic_open` never called and `aria._wake_event` never set.
  - Weather: `rain_soon` with a faked `_forecast_hourly` returning probabilities `[10, 70, 20]` → True; `[10, 20, 30]` → False; raising → None.
- [ ] **Step 2: Run, expect failures** — `.venv/bin/python -m pytest tests/test_companion.py tests/test_weather.py -q`.
- [ ] **Step 3: Implement** `Companion`, `Probes`, `Weather.rain_soon`, `active_window_rect`, the `main.py` wiring.
- [ ] **Step 4: Run the full suite** — `.venv/bin/python -m pytest -q` → all pass.

---

### Task 5: Docs and a real check

**Files:**
- Modify: `FEATURES.md` (new "Companion" bullet in the avatar section: what she does, when never, `ARIA_COMPANION=0`)
- Modify: `CLAUDE.md` (architecture paragraph: one sentence on `Engines/Companion.py`)

- [ ] **Step 1:** Write the two doc changes.
- [ ] **Step 2: Real check.** Restart Aria (aria-restart skill). With school over (it's after the last lesson, or run on a free day), touch the mouse while she sleeps: within ~3 s the orb becomes her, she waves, one line appears in the bubble, nothing is spoken (`tail ~/.cache/aria/aria.log`: no `Aria:` speech line, a `[Companion] woke` line). Open VS Code for > 1 min: she thinks/glances, at most one line. Type "go to sleep": she sleeps and stays asleep while you keep using the laptop.
- [ ] **Step 3:** Report to the user; wait for their go before piece 2 (test card). No commit unless asked.
