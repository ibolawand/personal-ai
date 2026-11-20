# Aria as a 3D anime avatar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While Aria is awake her orb gives way to Lala's own VRoid avatar, rendered in 3D with idle life, a pose per state and meaningful objects orbiting her; asleep, the orb stays exactly as it is.

**Architecture:** three.js and three-vrm run in one `QWebEngineView` inside the existing overlay window. All decisions that can be made without a GPU live in two testable places: `ui/avatar/logic.mjs` (pose, blink, mouth, ring maths) and `ui/avatar_view.py` (availability, the command queue to the page, which props show). `ui/overlay.py` only switches between orb and avatar and feeds the view what it already knows.

**Tech Stack:** Python 3 + PySide6 6.12 (QtWebEngine) + pytest; JavaScript ES modules, `three` and `@pixiv/three-vrm` vendored on disk, `node --test` (Node 24) for the pure logic.

**Spec:** `docs/superpowers/specs/2026-11-13-aria-avatar-design.md`

## Global Constraints

- Paths are relative to `BetterAI/`. Python runs through `.venv/bin/python`. The git root is the parent `personal-ai/`.
- **Commits only when Lala says so.** Leave work uncommitted and report.
- **Nothing is downloaded without Lala's explicit OK.** Task 5 stops and asks before fetching the two libraries. Nothing is downloaded from model sites, ever.
- The avatar never draws, animates or uses the processor while Aria is asleep, booting, in error, or while the overlay is hidden (`--hidden`).
- A missing piece (avatar file, libraries, QtWebEngine, WebGL, XFixes) never stops Aria or the overlay: she runs with the orb, and the self-check says which piece is missing.
- While the orb shows, its behaviour, painting and `setMask` are byte-for-byte what they are today.
- Tests need no display hardware, GPU, network or model, and never import `PySide6.QtWebEngineWidgets` (run with `QT_QPA_PLATFORM=offscreen`, like `tests/test_overlay.py`). The page itself is checked by eye in demo mode.
- The page loads everything from disk; it never touches the network.
- Numbers from the spec: avatar box **300 × 400** px; cross-fade **250 ms**; pose changes eased over **300 ms**; blink every **2 to 6 s**; rendered at **30 fps**; levels sent at most **20×/s**, mouse position at most **15×/s**.
- Settings: `ARIA_AVATAR` in `Engines/.env` = path of the `.vrm` (default `ui/avatar/aria.vrm`); `ARIA_AVATAR=0` = off. `*.vrm` is gitignored.
- No tool, prompt or routing change: the real-model checks aren't affected.
- X11 only (the overlay's click-through already is).

## Review Focus

Conditions the spec implies that no task's happy path exercises, most likely first. Each has a test in the task named.

1. State changes faster than the fade (wake then sleep within 250 ms; an alert flash while asleep) → never orb and avatar together, never neither, and a flash alone never brings the avatar up. (Task 4)
2. Started hidden, shown later by the hotkey while awake → the avatar resumes only then; hidden never renders. (Task 4)
3. The file exists but isn't a usable VRM (corrupt, a renamed PNG, a model without the bones or expressions used) → the page reports `failed` or skips that movement; the orb stays; nothing crashes. (Tasks 3, 5)
4. A timer already past due, or a reminder with an empty or very long text → no negative or broken caption; the prop is dropped or its caption cut. (Task 3)
5. A saved orb position near the top of the screen, restored with the taller avatar window → the window is moved back on screen. (Task 4)

---

### Task 1: The avatar's pure logic (`ui/avatar/logic.mjs`)

**Files:**
- Create: `ui/avatar/logic.mjs`
- Test: `ui/avatar/logic.test.mjs`

**Interfaces:**
- Produces (all pure, no three.js, no DOM):
  - `STATES = ['idle', 'listening', 'thinking', 'speaking']`
  - `avatarState(uiState: string, micOpen: boolean) -> string`: `'listening'` only for UI state `listening` **and** `micOpen`; `listening` without the microphone → `'idle'`; `thinking` → `'thinking'`; `speaking` → `'speaking'`; anything else → `'idle'`.
  - `poseFor(state) -> { spine: [x,y,z], neck: [x,y,z], head: [x,y,z], expressions: {name: weight} }`, angles in radians. `idle` is all zeros with no expressions. An unknown state returns the idle pose.
  - `ease(from: number, to: number, dt: number, seconds = 0.3) -> number`: exponential approach; reaches within 5% of `to` after `seconds`.
  - `nextBlink(now: number, rand: number) -> number` = `now + 2 + rand * 4`.
  - `blinkWeight(t: number, start: number) -> number`: 0 before `start`, up to 1 at `start + 0.075`, back to 0 at `start + 0.15`, 0 after.
  - `mouthWeight(prev: number, level: number, dt: number) -> number`: target `min(1, level * 5)`; rises fast (time constant 0.04 s), falls slower (0.12 s); returns exactly `0` when `level` is 0 and the result is below 0.02.
  - `ringPosition(index: number, count: number, t: number, radius = 0.55, tilt = 0.35) -> [x, y, z]`: props spread evenly on a ring tilted by `tilt` radians around the x axis, turning once every 12 s.
- Angle and expression values are the builder's, within these fixed signs (so tests can pin direction): `listening` has `spine[0] > 0` (leans in) and `head[2] != 0` (tilt); `thinking` has `head[0] < 0` (looks up) and `head[1] != 0` (to the side); `speaking` has an expression `relaxed > 0`. No angle exceeds 0.5 rad.

- [ ] **Step 1: Write the failing tests** in `ui/avatar/logic.test.mjs` with `node:test` and `node:assert/strict`:

```js
test('the microphone decides between listening and idle', () => {
  assert.equal(avatarState('listening', true), 'listening');
  assert.equal(avatarState('listening', false), 'idle');
  assert.equal(avatarState('thinking', false), 'thinking');
  assert.equal(avatarState('speaking', true), 'speaking');
  for (const s of ['sleeping', 'booting', 'error', 'alert', 'whatever']) assert.equal(avatarState(s, true), 'idle');
});
test('every state has a complete pose within limits, idle is neutral', () => {
  for (const s of STATES) {
    const p = poseFor(s);
    for (const bone of ['spine', 'neck', 'head']) {
      assert.equal(p[bone].length, 3);
      for (const a of p[bone]) assert.ok(Math.abs(a) <= 0.5);
    }
    for (const w of Object.values(p.expressions)) assert.ok(w >= 0 && w <= 1);
  }
  assert.deepEqual(poseFor('idle'), { spine: [0, 0, 0], neck: [0, 0, 0], head: [0, 0, 0], expressions: {} });
  assert.deepEqual(poseFor('nonsense'), poseFor('idle'));
});
test('poses point the right way', () => {
  assert.ok(poseFor('listening').spine[0] > 0 && poseFor('listening').head[2] !== 0);
  assert.ok(poseFor('thinking').head[0] < 0 && poseFor('thinking').head[1] !== 0);
  assert.ok(poseFor('speaking').expressions.relaxed > 0);
});
test('ease arrives in about its time and never overshoots', () => {
  let v = 0; for (let i = 0; i < 18; i++) v = ease(v, 1, 1 / 60);      // 0.3 s
  assert.ok(v > 0.95 && v <= 1);
  assert.equal(ease(1, 1, 0.016), 1);
});
test('blinks come every 2 to 6 seconds and last 150 ms', () => {
  assert.equal(nextBlink(10, 0), 12); assert.equal(nextBlink(10, 1), 16);
  assert.equal(blinkWeight(4.9, 5), 0); assert.equal(blinkWeight(5.075, 5), 1);
  assert.ok(blinkWeight(5.03, 5) > 0 && blinkWeight(5.03, 5) < 1); assert.equal(blinkWeight(5.2, 5), 0);
});
test('the mouth follows the voice and closes fully in silence', () => {
  let m = 0; for (let i = 0; i < 6; i++) m = mouthWeight(m, 0.2, 1 / 30);
  assert.ok(m > 0.9 && m <= 1);
  for (let i = 0; i < 30; i++) m = mouthWeight(m, 0, 1 / 30);
  assert.equal(m, 0);
  assert.ok(mouthWeight(0, 5, 1 / 30) <= 1);
});
test('props share the ring evenly and pass behind her', () => {
  const [a, b] = [ringPosition(0, 2, 0), ringPosition(1, 2, 0)];
  assert.ok(Math.abs(a[0] + b[0]) < 1e-9 && Math.abs(a[2] + b[2]) < 1e-9);    // opposite each other
  const zs = Array.from({ length: 24 }, (_, i) => ringPosition(0, 1, i * 0.5)[2]);
  assert.ok(Math.min(...zs) < 0 && Math.max(...zs) > 0);                      // in front and behind
  ringPosition(0, 1, 12).forEach((n, i) => assert.ok(Math.abs(n - ringPosition(0, 1, 0)[i]) < 1e-9));   // one turn in 12 s
});
```

- [ ] **Step 2: Run** `node --test ui/avatar/logic.test.mjs`. Expected: FAIL, `logic.mjs` not found.
- [ ] **Step 3: Implement `ui/avatar/logic.mjs`** to the Interfaces block.
- [ ] **Step 4: Run** `node --test ui/avatar/logic.test.mjs`. Expected: 7 passing.

---

### Task 2: Aria tells the UI when the microphone is open

**Files:**
- Modify: `main.py` (`NullUI` ~418; `Aria._ears_command`, `_go_to_sleep`; `Aria.run` at its start)
- Modify: `ui/overlay.py` (`OverlayBridge`, ~118–215)
- Test: `tests/test_listen.py`, `tests/test_overlay.py`

**Interfaces:**
- Produces:
  - `NullUI.set_mic_open(self, is_open: bool)` (no-op) and `OverlayBridge.set_mic_open(is_open)`: stores `bridge.mic_open: bool` (initially `False`) and emits a new signal `micOpenChanged = Signal(bool)` only when the value changes.
  - `Aria` calls `self.ui.set_mic_open(self._uses_mic())` after every change of `_ears` (`_ears_command` on both phrases, `_go_to_sleep`) and once at the start of `run()`.
- The `aria` test fixture's `NullUI` gets the method through the class, so existing tests are unaffected.

- [ ] **Step 1: Write the failing tests.** In `tests/test_listen.py`, with a recording UI on the existing `typing_aria` fixture:

```python
@pytest.fixture
def heard(typing_aria):
    calls = []
    typing_aria.ui.set_mic_open = calls.append
    return calls

def test_the_ui_is_told_when_the_microphone_opens_and_closes(typing_aria, heard):
    typing_aria._handle_turn("listen")
    typing_aria._handle_turn("stop listening")
    assert heard == [True, False]

def test_going_to_sleep_tells_the_ui_the_microphone_is_closed(typing_aria, heard):
    typing_aria._ears = True
    typing_aria._sleep_request, typing_aria._remember_session = threading.Event(), lambda: None
    typing_aria._go_to_sleep()
    assert heard == [False]

def test_null_ui_accepts_it():
    main.NullUI().set_mic_open(True)
```

In `tests/test_overlay.py`:

```python
def test_the_bridge_reports_the_microphone_only_when_it_changes(app):
    from ui.overlay import OverlayBridge
    b, seen = OverlayBridge(), []
    b.micOpenChanged.connect(seen.append)
    assert b.mic_open is False
    b.set_mic_open(True); b.set_mic_open(True); b.set_mic_open(False)
    app.processEvents()
    assert seen == [True, False] and b.mic_open is False
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_listen.py tests/test_overlay.py -q`. Expected: the four new tests FAIL.
- [ ] **Step 3: Implement.** The call at the start of `run()` covers `--voice` mode.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest -q; echo "exit $?"`. Expected: exit 0.

---

### Task 3: `ui/avatar_view.py`: availability, the link to the page, the props

**Files:**
- Create: `ui/avatar_view.py`
- Test: `tests/test_avatar.py` (new)

**Interfaces:**
- Produces:
  - `AVATAR_DIR` (the `ui/avatar` folder), `VENDOR_FILES = ("three.module.js", "three-vrm.module.js", "GLTFLoader.js")` under `AVATAR_DIR/vendor/` (Task 5 puts them there; if the libraries' own file names differ, Task 5 updates this tuple and its test).
  - `avatar_path(env=os.environ) -> str | None`: `None` when `ARIA_AVATAR` is `"0"`; the variable's value (with `~` expanded) when set; else `AVATAR_DIR/aria.vrm`.
  - `available(path, vendor_dir=None, has_webengine=None) -> tuple[bool, str]`, checked in this order, with these exact reasons:
    1. `path is None` → `(False, "switched off (ARIA_AVATAR=0)")`
    2. not a file → `(False, f"no avatar file at {path}")`
    3. any vendor file missing → `(False, "the 3D libraries aren't installed (ui/avatar/vendor)")`
    4. QtWebEngine not importable (`importlib.util.find_spec`, never an import) → `(False, "QtWebEngine isn't installed")`
    5. else `(True, "ready to load")`
  - `props_for(state: str, mic_open: bool, timers: list[dict], now: float) -> list[dict]`, each `{"kind", "caption"}`, in this order:
    - `{"kind": "mic", "caption": "listening"}` when `state == "listening" and mic_open`
    - `{"kind": "dots", "caption": "thinking"}` when `state == "thinking"`
    - `{"kind": "clock", "caption": "<m>:<ss> left"}` for the soonest entry of `timers` whose `kind` is `timer`, `focus` or `focusbreak` and whose `due` is in the future; none → no clock
    - `{"kind": "note", "caption": <text>}` for the soonest `kind == "reminder"` due later today (local time); its text cut to 40 characters with `…`; an empty text → `"reminder"`
  - `class AvatarLink(run_js: Callable[[str], None])`: everything the overlay says to the page, testable without a page.
    - `set_state(state)`, `set_level(mic, out)`, `look_at(x, y)`, `set_props(props)`, `fade(visible: bool)`, `hop()`, `pause()`, `resume()`
    - Each sends one string to `run_js`: `window.aria.setState("thinking")`, `window.aria.setLevel(0.1,0)`, `window.aria.lookAt(0.5,-0.2)`, `window.aria.setProps([...])`, `window.aria.fade(true)`, `window.aria.hop()`, `window.aria.pause()`, `window.aria.resume()`. Arguments are built with `json.dumps` (never string concatenation); numbers rounded to 3 decimals.
    - `ready: bool` (False at first), `failed: str | None`. Before `mark_ready()`, calls are kept, only the last one per method (`hop` is dropped), and `mark_ready()` replays them in the order `setState, setProps, setLevel, lookAt, fade, pause|resume`. After `mark_failed(why)`, every call is dropped.
    - `set_state`, `set_props`, `fade`, `pause`/`resume` are not re-sent when the value is unchanged.
  - `make_view(parent, path) -> AvatarView`: imports `PySide6.QtWebEngineWidgets` inside the function, builds a `QWebEngineView` subclass with a transparent page background and `WA_TransparentForMouseEvents`, loads `AVATAR_DIR/avatar.html` with the model's path as the `model` query parameter (a `file://` URL), and exposes `.link: AvatarLink`. It calls `link.mark_ready()` / `link.mark_failed(why)` from the page's report (Task 5 defines the report) and `mark_failed("the 3D view stopped")` on `renderProcessTerminated`. Local file access is enabled for this page only.

- [ ] **Step 1: Write the failing tests** in `tests/test_avatar.py` (no Qt needed for these):

```python
"""Aria's avatar: when it can show, what the overlay tells the 3D page, and which props orbit her."""
import datetime as dt

import pytest

import ui.avatar_view as A


@pytest.fixture
def ready(tmp_path):
    model = tmp_path / "aria.vrm"; model.write_bytes(b"x")
    vendor = tmp_path / "vendor"; vendor.mkdir()
    for name in A.VENDOR_FILES:
        (vendor / name).write_text("")
    return str(model), str(vendor)


def test_where_the_avatar_file_is(tmp_path):
    assert A.avatar_path({"ARIA_AVATAR": "0"}) is None
    assert A.avatar_path({"ARIA_AVATAR": str(tmp_path / "me.vrm")}) == str(tmp_path / "me.vrm")
    assert A.avatar_path({}).endswith("ui/avatar/aria.vrm")


def test_each_missing_piece_is_named(ready, tmp_path):
    model, vendor = ready
    assert A.available(None) == (False, "switched off (ARIA_AVATAR=0)")
    gone = str(tmp_path / "nope.vrm")
    assert A.available(gone, vendor, True) == (False, f"no avatar file at {gone}")
    assert A.available(str(tmp_path), vendor, True)[0] is False                      # a folder is not a file
    assert A.available(model, str(tmp_path / "empty"), True) == (False, "the 3D libraries aren't installed (ui/avatar/vendor)")
    assert A.available(model, vendor, False) == (False, "QtWebEngine isn't installed")
    assert A.available(model, vendor, True) == (True, "ready to load")


NOW = dt.datetime(2026, 11, 13, 15, 0).timestamp()

def test_props_say_what_is_going_on():
    timers = [{"kind": "reminder", "text": "call mum", "due": NOW + 3600, "created": NOW},
              {"kind": "timer", "text": "tea", "due": NOW + 125, "created": NOW},
              {"kind": "focus", "text": "", "due": NOW + 900, "created": NOW}]
    assert A.props_for("listening", True, timers, NOW) == [
        {"kind": "mic", "caption": "listening"}, {"kind": "clock", "caption": "2:05 left"},
        {"kind": "note", "caption": "call mum"}]
    assert A.props_for("listening", False, [], NOW) == []
    assert A.props_for("thinking", True, [], NOW) == [{"kind": "dots", "caption": "thinking"}]

def test_past_timers_tomorrows_reminders_and_odd_texts():
    tomorrow = NOW + 20 * 3600
    timers = [{"kind": "timer", "text": "", "due": NOW - 5, "created": NOW - 60},
              {"kind": "reminder", "text": "x" * 80, "due": NOW + 60, "created": NOW},
              {"kind": "reminder", "text": "later", "due": tomorrow, "created": NOW}]
    props = A.props_for("speaking", False, timers, NOW)
    assert props == [{"kind": "note", "caption": "x" * 39 + "…"}]
    assert A.props_for("speaking", False, [{"kind": "reminder", "text": " ", "due": NOW + 60, "created": NOW}], NOW) == [
        {"kind": "note", "caption": "reminder"}]


@pytest.fixture
def link():
    sent = []
    l = A.AvatarLink(sent.append); l.sent = sent
    return l

def test_calls_wait_for_the_page_and_only_the_latest_of_each_kind_is_replayed(link):
    link.set_state("thinking"); link.set_state("speaking"); link.set_level(0.12345, 0); link.hop()
    link.set_props([{"kind": "mic", "caption": "listening"}]); link.fade(True); link.pause(); link.resume()
    assert link.sent == [] and link.ready is False
    link.mark_ready()
    assert link.sent == ['window.aria.setState("speaking")',
                         'window.aria.setProps([{"kind": "mic", "caption": "listening"}])',
                         'window.aria.setLevel(0.123,0)', 'window.aria.fade(true)', 'window.aria.resume()']

def test_once_ready_calls_go_straight_through_and_repeats_are_skipped(link):
    link.mark_ready()
    link.set_state("idle"); link.set_state("idle"); link.look_at(0.5, -0.25); link.hop(); link.fade(False); link.fade(False)
    assert link.sent == ['window.aria.setState("idle")', 'window.aria.lookAt(0.5,-0.25)', 'window.aria.hop()',
                         'window.aria.fade(false)']

def test_a_caption_cannot_break_out_of_the_call(link):
    link.mark_ready()
    link.set_props([{"kind": "note", "caption": 'x"); alert(1); ("'}])
    assert link.sent == ['window.aria.setProps([{"kind": "note", "caption": "x\\"); alert(1); (\\""}])']

def test_after_a_failure_nothing_is_sent(link):
    link.set_state("thinking"); link.mark_failed("no WebGL")
    link.mark_ready(); link.set_state("speaking"); link.resume()
    assert link.sent == [] and link.failed == "no WebGL" and link.ready is False
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_avatar.py -q`. Expected: FAIL at import.
- [ ] **Step 3: Implement** `avatar_path`, `available`, `props_for`, `AvatarLink` and `make_view`. `make_view` is not unit-tested (it needs a real web view); keep it short and free of decisions.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_avatar.py -q`. Expected: all pass.

---

### Task 4: The overlay switches between orb and avatar

**Files:**
- Modify: `ui/overlay.py` (`Overlay.__init__` ~396, geometry helpers ~455–470, `_tick` ~580, `paintEvent` ~755, `_on_state`, `_restore_position`, `run_with_overlay` ~1160, the demo at the bottom)
- Test: `tests/test_avatar.py`

**Interfaces:**
- Consumes: `AvatarLink`, `props_for`, `available`, `avatar_path`, `make_view` (Task 3); `bridge.mic_open`, `micOpenChanged` (Task 2).
- Produces:
  - Constants `AVATAR_W, AVATAR_H = 300, 400`, `FADE_MS = 250`.
  - `Overlay(bridge, make_avatar=None)`: `make_avatar(parent)` returns the view, any object with `.link` (an `AvatarLink`), `show()`, `hide()`, `setGeometry(QRect)`; `None`, or a factory that raises, = orb only. (As built: a factory, because the real view needs the overlay as its parent and the window's size depends on whether there is one. The view is kept as `overlay.avatar`; `overlay._avatar_on` is true while she shows.)
  - `Overlay._shows_avatar() -> bool`: `avatar` present, `avatar.link.ready`, not `avatar.link.failed`, the overlay visible, and `self.state` not in `("sleeping", "booting", "error")`.
  - `Overlay._avatar_rect() -> QRect`: `AVATAR_W × AVATAR_H`, bottom-right of the window, sharing the orb box's bottom-right corner.
  - `Overlay._anchor_rect() -> QRect`: `_avatar_rect()` while `_shows_avatar()`, else `_orb_rect()`. Bubbles, caption, text box and cards are laid out against it (today they use the orb's rect and centre).
  - As built: `Overlay._stack_origin()` gives the (right, bottom) that cards and bubbles stack up from (above her head while she shows); while she shows, the text box and the hover caption are a bar across the bottom of her box; `overlay.win_w` / `overlay.win_h` replace the module constants inside the class.
  - `run_with_overlay` builds the view (through `_avatar_maker(bridge)`): `path = avatar_path()`; when `available(path)[0]`, `avatar = make_view(overlay, path)` inside a `try` that falls back to `None` and prints the type name; the reason from `available` is kept on `bridge.avatar_status: str` for the self-check (Task 7).
- Behaviour:
  - When an avatar is given, the window is `AVATAR_H - ORB_BOX` (240 px) taller so cards keep their room above her; a restored position that would put the window's top above the screen's available area is moved down to fit. Without an avatar the window size is unchanged.
  - On every state change, visibility change and `mark_ready`: if `_shows_avatar()` → `avatar.setGeometry(_avatar_rect())`, `avatar.show()`, `link.resume()`, `link.fade(True)`, and the orb is not painted; else → `link.fade(False)`, `link.pause()`, the view hidden after `FADE_MS`, and the orb painted as today. A later "show" cancels a pending "hide".
  - The first time `avatar.link.failed` is seen, the overlay logs it once with `Engines.Diagnostics.problem("avatar", why)`, sets `bridge.avatar_status = why`, hides the view and stays with the orb for the rest of the session (test: `test_a_failure_is_logged_once_and_the_orb_stays`, with `Diagnostics.problem` patched to record).
  - A flash state (`alert`, `unknown`) never changes `self.state` (as today) and so never shows the avatar; while she shows it calls `link.hop()`.
  - While she shows, `_tick` sends `link.set_state(state)` on change, `link.set_level(bridge.mic, bridge.out)` at most 20×/s, `link.look_at(x, y)` at most 15×/s (mouse position relative to the avatar rect's centre, each axis clamped to −1…1, y up), and `link.set_props(props_for(state, bridge.mic_open, bridge.timers, time.time()))` at most once a second. While the orb shows, none of these are sent.
  - `_in_orb(pos)` also accepts a point inside an ellipse inscribed in the upper 80% of `_avatar_rect()` while she shows, so click, drag, right-click and hover work on her as on the orb.

- [ ] **Step 1: Write the failing tests** in `tests/test_avatar.py`, off-screen like `tests/test_overlay.py` (copy its `app` fixture and the `QSettings` redirection), with a fake view:

```python
class FakeView:
    def __init__(self):
        self.sent, self.shown, self.rect = [], False, None
        self.link = A.AvatarLink(self.sent.append)
    def show(self): self.shown = True
    def hide(self): self.shown = False
    def setGeometry(self, r): self.rect = r
```

Tests (one behaviour each; the name is the requirement):
  - `test_asleep_the_orb_shows_and_nothing_is_sent`: ready link, overlay shown, state `sleeping`, a few `_tick()`s → `_shows_avatar()` False, `view.shown` False, no `setState`/`setLevel`/`lookAt`/`setProps` in `view.sent`.
  - `test_waking_brings_the_avatar_and_sleeping_takes_her_away`: `bridge.set_state("listening")` → `view.shown`, `resume()` then `fade(true)` sent, `view.rect` is 300 × 400; then `"sleeping"` → `fade(false)` and `pause()` sent, and after `QTest.qWait(FADE_MS + 60)` `view.shown` is False.
  - `test_wake_then_sleep_then_wake_inside_the_fade_ends_with_her_shown` (Review Focus 1): three state changes without waiting, then `qWait(FADE_MS + 60)` → `view.shown` True and `_shows_avatar()` True.
  - `test_a_flash_while_asleep_does_not_show_her_and_while_awake_makes_her_hop` (Review Focus 1).
  - `test_until_the_page_is_ready_and_after_a_failure_the_orb_stays`: link not ready → False; `mark_ready()` while awake → shown; a second overlay with `mark_failed("x")` → never shown.
  - `test_a_hidden_overlay_never_resumes_her_and_showing_it_does` (Review Focus 2): overlay not shown, state `listening` → no `resume()`; `overlay.show()` → `resume()` sent.
  - `test_she_is_told_the_state_the_microphone_and_the_props`: awake, `bridge.set_mic_open(True)`, a timer in `bridge.timers`, ticks → `view.sent` contains `window.aria.setState("listening")` and a `setProps` whose JSON has kinds `mic` and `clock`.
  - `test_levels_and_mouse_are_rate_limited`: 100 `_tick()`s within one mocked second (patch `time.monotonic`) → at most 20 `setLevel` and at most 15 `lookAt` calls.
  - `test_without_an_avatar_the_window_and_the_orb_are_as_before`: `Overlay(bridge)` has the old `WIN_W × WIN_H` size and `_anchor_rect() == _orb_rect()`.
  - `test_with_an_avatar_the_window_is_taller_and_stays_on_screen` (Review Focus 5): size is `WIN_W × (WIN_H + 240)`; with a saved position of y = 0 for the old window, the restored window's top is not above the screen's available top.
  - `test_clicking_her_opens_the_text_box`: awake, `QTest.mouseClick` at the centre of `_avatar_rect()` → `overlay.input.isVisible()`.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_avatar.py -q`. Expected: the new tests FAIL (`Overlay` takes no `avatar`).
- [ ] **Step 3: Implement.** Keep `_paint_orb` untouched; guard its call. Put the show/hide decision in one method called from the state slot, `showEvent`/`hideEvent` and a `ready` callback.
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_avatar.py tests/test_overlay.py -q` and then `.venv/bin/python -m pytest -q; echo "exit $?"`. Expected: all pass, exit 0.

---

### Task 5: The 3D page: libraries, model, rest pose, idle life

**This task needs the avatar file from Lala.** Stop with status BLOCKED if there is no `.vrm` at `avatar_path()`. The libraries are already vendored (done 2026-11-13 with Lala's OK: `three` 0.187.0 and `@pixiv/three-vrm` 3.5.5, six files listed in `ui/avatar/vendor/VERSIONS.md` and in `VENDOR_FILES`; Steps 1 and 2 below are done apart from asking for the file).

**Full body (decided 2026-11-13):** she is shown and moved with her whole body. `logic.mjs` now also exports `BONES` (thirteen bones), `poseFor(state) -> { bones: {name: [x,y,z]}, expressions }` for all of them, `idleMotion(t)` (added on top), `gesture(name, t) -> { weight, bones, lift } | null` for `wave` and `hop`, and `GESTURES` (their lengths). `AvatarLink` has `wave()` next to `hop()`, and the overlay calls it when she appears. Where this task or Task 6 says "spine, neck and head", read "every bone in `BONES`"; where it says "head to waist", read "her whole body, feet to hair, with room above for the hop". `window.aria` therefore also needs `wave()`. The angles in `logic.mjs` were written without a model: tuning them by eye on the real one (which axis bends an elbow, how far the arms come down) is part of this task, changing `logic.mjs` and keeping its tests' signs true.

**Files:**
- Create: `ui/avatar/vendor/` (the library builds and `VERSIONS.md`), `ui/avatar/avatar.html`, `ui/avatar/avatar.js`
- Modify: `ui/avatar_view.py` (`VENDOR_FILES` if the names differ; the readiness report in `make_view`), `.gitignore` (add `*.vrm`)
- Test: `tests/test_avatar.py` (vendor names), by eye in demo mode

**Interfaces:**
- Consumes: `logic.mjs` (Task 1); the `window.aria.*` calls `AvatarLink` sends (Task 3).
- Produces:
  - `vendor/`: ES-module builds of `three` (with its `GLTFLoader` addon) and `@pixiv/three-vrm`, fetched once with `npm pack` into the scratchpad and copied over (no `node_modules`, no `package.json` in the repo). `VERSIONS.md` lists each file, its package, exact version and licence (both MIT). An import map in `avatar.html` maps `three` and `three/addons/` to the vendored files.
  - `avatar.html`: transparent body, one full-size canvas, no network references.
  - `avatar.js` defines `window.aria` with `setState, setLevel, lookAt, setProps, fade, hop, pause, resume` (Tasks 5 and 6 fill them in; in this task `setState`, `setLevel`, `setProps` and `hop` may be stored and ignored) and reports exactly once: `window.ariaStatus = "ready"` after the first rendered frame with the model, or `"failed: <short reason>"` (no WebGL, model didn't load, not a VRM). `make_view` polls `window.ariaStatus` every 250 ms for up to 20 s, then `mark_failed("the avatar took too long to load")`.
- What the page does in this task:
  - Loads the model named in the `model` query parameter with `GLTFLoader` + `VRMLoaderPlugin`; applies `VRMUtils.rotateVRM0` for VRM 0.x models so every model faces the camera.
  - Camera frames head to waist; soft two-light setup; renderer with `alpha: true`, clear alpha 0, pixel ratio capped at 2.
  - Rest pose: both upper arms rotated down from the T-pose (about 1.2 rad), via the normalised humanoid bones.
  - Idle: breathing on the chest, a slow sway, blinking from `nextBlink`/`blinkWeight` on the `blink` expression, spring bones updated each frame (`vrm.update(dt)`), look-at toward the last `lookAt(x, y)` with the eyes leading and the head following about a third of the way.
  - Runs at 30 fps (skip frames, don't use a timer); `pause()` cancels the animation frame so nothing runs; `resume()` restarts and resets the clock so there is no jump; `fade(v)` eases the canvas' CSS opacity over 250 ms.
  - Any bone or expression the model lacks is skipped without an error.

- [ ] **Step 1: Ask Lala** for the OK to download `three` and `@pixiv/three-vrm` from npm, and where the `.vrm` is. Stop here until both are answered.
- [ ] **Step 2: Vendor the libraries** as described; add the test:

```python
def test_the_vendored_libraries_are_all_there():
    import os
    for name in A.VENDOR_FILES:
        assert os.path.isfile(os.path.join(A.AVATAR_DIR, "vendor", name)), name
    assert os.path.isfile(os.path.join(A.AVATAR_DIR, "vendor", "VERSIONS.md"))
```

- [ ] **Step 3: Write `avatar.html` and `avatar.js`** to the list above.
- [ ] **Step 4: Check failure reporting without the model:** `make_view` on a copy of any small non-VRM file → within 20 s `link.failed` starts with `failed:`'s reason and the demo overlay keeps the orb (Review Focus 3). Record what the reason said.
- [ ] **Step 5: Check by eye.** `.venv/bin/python -m ui.overlay` (demo mode cycles the states without Aria): when the demo leaves `sleeping`, the avatar fades in where the orb was, arms down, blinking, breathing, hair moving, eyes following the mouse; the desktop shows through around her; in `sleeping` only the orb is there. Note the frame rate (`requestAnimationFrame` count, logged once after 5 s) and the overlay process's memory. Report exactly what was and wasn't seen; a screenshot of the corner goes to Lala.
- [ ] **Step 6: Run** `.venv/bin/python -m pytest -q; echo "exit $?"` and `node --test ui/avatar/logic.test.mjs`. Expected: exit 0, all passing.

---

### Task 6: States, mouth, and the things in orbit

**Files:**
- Modify: `ui/avatar/avatar.js`, `ui/avatar/avatar.html` (the caption element)
- Test: `ui/avatar/logic.test.mjs` (only if a pure helper is added), by eye in demo mode

**Interfaces:**
- Consumes: `avatarState`, `poseFor`, `ease`, `mouthWeight`, `ringPosition` (Task 1); the props `{"kind", "caption"}` with kinds `mic`, `dots`, `clock`, `note` (Task 3).
- `setState(uiState)` and a new stored microphone flag: the page works out `avatarState(uiState, micOpen)` where `micOpen` is true exactly when the current props contain a `mic` prop (so no extra call is needed).
- What the page does:
  - Each frame, spine, neck and head ease toward `poseFor(state)` on top of the idle motion and look-at; expression weights ease the same way; `relaxed`/`surprised` are skipped when the model lacks them.
  - `setLevel(mic, out)`: while speaking, the `aa` expression follows `mouthWeight(prev, out, dt)`; otherwise it eases to 0. While listening, the head nods slightly with `mic`.
  - `hop()` and `wave()`: start `gesture('hop' | 'wave', t)` from `logic.mjs`; while it runs its bones replace the pose by its weight and its `lift` raises the whole model; `surprised` is at full weight during a hop.
  - `setProps(list)`: one small flat-shaded mesh per kind (builder's shapes: a disc with hands for `clock`, a folded sheet for `note`, a capsule for `mic`, three spheres for `dots`), placed with `ringPosition(i, n, t)` around her chest, depth-tested against her so they pass behind; a prop fades in and out over 300 ms when the list changes.
  - Hover: the last `lookAt(x, y)` is also the pointer. A raycast from it picks the nearest prop; that prop scales to 1.4× and an HTML caption (one absolutely positioned element, the overlay's bubble look: dark, rounded, 12 px text) shows its `caption` beside it. Nothing hovered → no caption. The caption text is set with `textContent`, never as HTML.

- [ ] **Step 1: Implement** the list above.
- [ ] **Step 2: Extend the demo** at the bottom of `ui/overlay.py` so its cycle also opens the microphone for one `listening` phase, sets a 3-minute timer and a reminder for later today, and fires one `alert` flash, so every state and prop can be seen without Aria.
- [ ] **Step 3: Check by eye** in demo mode and report per item, seen or not seen: leaning in only when the microphone is open; looking up while thinking; mouth moving while speaking and closed in silence; the hop; each of the four props appearing, passing behind her, and showing its caption under the mouse; captions for an 80-character reminder cut with `…`.
- [ ] **Step 4: Run** `node --test ui/avatar/logic.test.mjs` and `.venv/bin/python -m pytest -q; echo "exit $?"`.

---

### Task 7: Clicks pass beside her; self-check; documentation

**Files:**
- Create: `ui/xshape.py`
- Modify: `ui/overlay.py` (the mask update, ~733–751), `Engines/Health.py`, `FEATURES.md` (Overlay UI section), `CLAUDE.md` (UI threading paragraph: one sentence)
- Test: `tests/test_avatar.py`, `tests/test_health.py`

**Interfaces:**
- Consumes: `Overlay._shows_avatar()`, `_avatar_rect()`, `bridge.avatar_status` (Task 4).
- Produces:
  - `ui/xshape.py`:
    - `avatar_click_rects(avatar: QRect, step: int = 8) -> list[QRect]`: horizontal strips approximating the ellipse inscribed in the upper 80% of `avatar` (the same shape `_in_orb` uses), pure geometry.
    - `set_input_rects(win_id: int, rects: list[QRect]) -> bool`: sets the window's X11 **input** shape to the union of `rects` through `libXfixes` (`XFixesCreateRegion`, `XFixesSetWindowShapeRegion` with `ShapeInput`, `XFixesDestroyRegion`) with `ctypes`; returns `False` (and changes nothing) when the library, the display or the call isn't available. Never raises.
    - `clear_input_rects(win_id: int) -> bool`: back to the default input shape.
  - Overlay: while `_shows_avatar()`, the mask update calls `clearMask()` once and `set_input_rects(winId, <the rectangles it unites today for bubbles, text box, caption and card> + avatar_click_rects(_avatar_rect()))`; when that returns `False` it falls back to `setMask` with the same rectangles plus the whole `_avatar_rect()` and sets `bridge.avatar_status = "showing, but clicks beside her are blocked (XFixes missing)"`. When the orb comes back: `clear_input_rects`, then today's `setMask` path unchanged.
  - Health: a check named `"Avatar"`: `(True, bridge.avatar_status)` when the status starts with `ready`, `showing` or `switched off`; `(False, status)` otherwise (`no avatar file at …`, libraries, QtWebEngine, a page failure). With no overlay (`NullUI`) the check is left out.

- [ ] **Step 1: Write the failing tests.**

```python
def test_the_click_area_follows_her_outline_not_her_box(app):
    from PySide6.QtCore import QRect
    from ui.xshape import avatar_click_rects
    box = QRect(100, 200, 300, 400)
    rects = avatar_click_rects(box)
    assert rects and all(box.contains(r) for r in rects)
    assert max(r.bottom() for r in rects) <= box.top() + 0.8 * box.height() + 1
    area = sum(r.width() * r.height() for r in rects)
    assert 0.5 * box.width() * box.height() < area < 0.7 * box.width() * box.height()   # an ellipse in 80% of the box
    assert not any(r.contains(box.topLeft()) for r in rects)                             # the corners stay click-through

def test_setting_the_input_shape_never_raises(monkeypatch):
    import ui.xshape as X
    monkeypatch.setattr(X.ctypes.util, "find_library", lambda name: None)
    assert X.set_input_rects(0, []) is False and X.clear_input_rects(0) is False
```

plus, with the `FakeView` overlay of Task 4 and `ui.xshape.set_input_rects` patched to record: `test_awake_the_picture_is_not_clipped_and_clicks_get_her_outline` (no mask on the widget: `overlay.mask().isEmpty()`; the recorded rects include the avatar strips), `test_without_xfixes_her_whole_box_takes_clicks_and_the_self_check_says_so` (patched to return `False` → the mask contains `_avatar_rect()`; `bridge.avatar_status` as above), `test_back_to_the_orb_the_old_mask_is_used` (mask non-empty, `clear_input_rects` called).

In `tests/test_health.py`: `test_the_avatar_is_reported_with_its_reason` for the statuses `"ready to load"` (OK), `"switched off (ARIA_AVATAR=0)"` (OK), `"no avatar file at /x/aria.vrm"` (problem), and no `"Avatar"` row with `NullUI`.

- [ ] **Step 2: Run** the new tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Check by eye:** with the avatar showing, click the desktop just beside her shoulder and above her head → the window behind gets the click; click her → the text box opens; her hair's edge is smooth, not jagged. Report which of the two paths (XFixes or fallback) is active.
- [ ] **Step 5: Write the docs.** `FEATURES.md`, Overlay UI section: what shows asleep and awake, the poses per state, the four props and their captions, how to set or switch off the avatar (`ARIA_AVATAR`), that she never draws while asleep or hidden, the fallbacks, the memory cost measured in Task 5, the files and tests. `CLAUDE.md`: one sentence in the UI threading paragraph naming `ui/avatar_view.py`, `ui/avatar/` and the rule that the orb shows whenever `_shows_avatar()` is false.
- [ ] **Step 6: Run** `.venv/bin/python -m pytest -q; echo "exit $?"` and `node --test ui/avatar/logic.test.mjs`. Then start the real Aria once with the `aria-restart` skill and confirm with Lala: asleep = orb; clicking and typing wakes her and the avatar appears; `listen` makes her lean in and the microphone prop appear; `go to sleep` brings the orb back. Report what was seen.
