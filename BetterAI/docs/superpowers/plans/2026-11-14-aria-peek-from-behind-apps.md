# Peeking From Behind an App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aria's avatar can go behind an open app (cut out where it covers her) and lean out from its side edge to look at you, on her own while idle and when you raise a window over her.

**Architecture:** The overlay reads the windows (`ui/desktop_windows.py`), tells the page which side edges she could hide behind and when a window was raised over her, and while she is behind one sends that window's rectangle in her box's coordinates every tick. The page decides the walk, the lean-out and the timing (pure functions in `logic.mjs`), applies the rectangle as a CSS `clip-path` hole in her canvas, and reports which window she is behind. Her window moves through the existing `Travel`.

**Tech Stack:** Python 3 / PySide6 / python-xlib; three.js page (ES modules); tests with pytest and `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-14-aria-aware-of-apps-design.md` (section "Design: peeking from behind an app").

## Global Constraints

- No camera, nothing that wakes her by herself; never read window titles or contents, only geometry.
- Her text box, bubbles and cards are never cut or hidden; clicks on the covered part of her go to the app.
- No popping: hiding and coming out are smooth; joints go through the existing follow filter.
- Only windows that reach from above her head to below her feet, not maximized, fullscreen or minimized (as `open_windows` already filters).
- Only with a full-size character (`rig.canSit`), like sitting.
- Commit only when the user asks (project rule); update `FEATURES.md`.

## Review Focus

- The app she is behind is closed or minimized while she is behind it → the cut-out disappears at once and she simply stands there (no hole left in her picture). Test in Task 4.
- The app she is behind is dragged away while she peeks → the hole follows the window; if it no longer overlaps her box the hole is gone. Test in Task 4.
- You talk to her while she is behind → she comes out from the nearer edge, the hole stays until she is out. Test in Task 3 (logic: `comeOut`) and Task 4.
- You drag her while she is behind → the walk ends, the hole is removed, she stands where dropped. Test in Task 4.
- A window raised over her while she sits on the floor, on a window, or walks → no reaction (only while standing idle). Test in Task 4.

---

### Task 1: Where she can hide (pure geometry)

**Files:**
- Modify: `ui/desktop_windows.py`
- Test: `tests/test_desktop_windows.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Edge: id: int; x: int; out: int` (x: the edge's screen x; out: -1 for a window's left edge, she leans out to the left; +1 for its right edge).
- Produces: `hideouts(windows, box, reach=700, below=20) -> list[Edge]`; `box` is her box `(left, top, right, bottom)` on screen; a window qualifies if `w.top <= box_head` and `w.bottom >= box_feet - below`, where `box_head = top + 0.18*(bottom-top)` and `box_feet = bottom - 0.12*(bottom-top)` (her head and feet in the box); each side edge within `reach` px of the box centre, on the screen and not covered at her height by a window above it in the stacking order, is an `Edge`.
- Produces: `covering(windows, box) -> Win | None`: the topmost window that contains the box's centre x and reaches from `box_head` to `box_feet` (the window she would be behind).

- [ ] **Step 1: Write the failing tests** in `tests/test_desktop_windows.py`:
  `test_a_tall_window_beside_her_gives_two_edges` (box (1000,400,1300,920), Win(1, 300, 200, 800, 1000) → `[Edge(1, 300, -1), Edge(1, 800, 1)]`);
  `test_a_short_or_far_window_gives_none` (Win top 700 → []; Win at 3000..3500 → []);
  `test_an_edge_covered_by_a_higher_window_is_left_out` (Win(2, 750, 100, 900, 1000) above window 1 → only `Edge(1, 300, -1)` and window 2's own edges);
  `test_covering_is_the_topmost_window_over_her_middle` (two windows over the centre → the later one; none → None).
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_desktop_windows.py -q`; expect the new tests to fail (ImportError for `Edge`).
- [ ] **Step 3:** Implement `Edge`, `hideouts`, `covering` in `ui/desktop_windows.py` (reuse `_minus` style checks; "covered at her height" = a later window whose x-span contains the edge x and whose y-span overlaps `[box_head, box_feet]`).
- [ ] **Step 4:** Run the same command; expect all pass.

### Task 2: The peek itself (pure logic)

**Files:**
- Modify: `ui/avatar/logic.mjs`
- Test: `ui/avatar/logic.test.mjs`

**Interfaces:**
- Produces: `export const PEEK = { inset: 0.13, length: 4.2 }` (inset: units behind the edge her middle stops; length: seconds of the lean-out).
- Produces: `export function planHide(edges, r)` → `{ id, dx, out }` or null; `edges` are `[{ id, x, out }]` with x in **units** from her middle (the page converts); picks the nearest edge as likelier (weight `1/(1+|x|)`), `dx = x - out * PEEK.inset` (her stopping point just behind the edge).
- Produces: `export function peekOut(t, out)` → `{ bones, look, face, wave }` or null after `PEEK.length`: from 0 to 0.6 s she leans sideways toward `out` (spine z, chest z, neck z, head z adding up to about 0.55 rad, hips shifting the other way by `[0, 0, -0.08*out]`), holds and looks at you (`look [0, 0]`, `face.happy` up to 0.4), in about half the peeks a small wave of the hand on the `out` side (`wave: true` → avatar.js starts the existing `wave` gesture with that side), leans back in from `length-0.7` to `length`.
- Produces: `export function headPastEdge(out)` → units her head moves toward `out` at full lean (used by the test and by the overlay check): must exceed `PEEK.inset + 0.04`.

- [ ] **Step 1: Write the failing tests** in `ui/avatar/logic.test.mjs`:
  `planHide picks the nearer edge and stops just behind it` (edges `[{id:1,x:-0.8,out:-1},{id:1,x:2.5,out:1}]`, r=0.2 → `{id:1, dx:-0.8+0.13, out:-1}`; `[]` → null);
  `the lean-out brings her head past the edge and back` (`headPastEdge(1) > PEEK.inset + 0.04`; `peekOut(0,1)` bones near zero lean; `peekOut(1.5,1)` lean ≥ 0.5 rad summed over spine/chest/neck/head z, sign toward out; `peekOut(PEEK.length - 0.01, 1)` lean < 0.05; `peekOut(PEEK.length, 1)` null);
  `the lean-out is smooth` (sampled every 0.01 s, no bone angle changes by more than 0.05 per step).
- [ ] **Step 2:** Run `node --test ui/avatar/logic.test.mjs`; expect the new tests to fail.
- [ ] **Step 3:** Implement `PEEK`, `planHide`, `peekOut`, `headPastEdge` (headPastEdge from the lean angles and the measured heights: hips 0.512 → head ≈ 0.80, `Σ sin(angle_i) * segment_i`).
- [ ] **Step 4:** Run the tests; expect all pass.

### Task 3: The page runs it

**Files:**
- Modify: `ui/avatar/avatar.js`, `ui/avatar/logic.mjs` (`IDLE` gets `hide: { weight: 1.5, after: 10 }`, `chooseIdle` gets `canHide` and returns `{ hide: true }`)
- Test: `ui/avatar/logic.test.mjs`

**Interfaces:**
- Consumes: Task 2's functions; existing `trip`, `legLength`, `Travel` reporting.
- Produces (page API, called by the overlay):
  `window.aria.setHideouts(list)` with `list = [{ id, x, out }]`, x in **pixels** from her box centre;
  `window.aria.hiddenBy({ id, left, right })` (pixels from her box centre: she is behind that window now; she walks hidden to the nearer edge and peeks);
  `window.aria.setCover(rect)` with `rect = { left, top, right, bottom }` in her box's pixels, or `null` (CSS `clip-path: path(evenodd, ...)` on the canvas: the box minus the rect);
  `window.ariaBehind` = the window id she is behind, or null (the overlay polls it with `ariaTravel`, in the same `JSON.stringify` call: `ask_travel` returns `{ travel, behind }`).
- Sequence on `{ hide: true }`: `planHide` → walk (`trip` with `leg = legLength(|dx|)`), `ariaBehind = id` from the moment her middle passes the edge (the overlay starts sending the cover), turn to face front, `peekOut`, then walk back out by `-dx` to where she started, `ariaBehind = null` once her middle is out by `PEEK.inset + 0.15`. Talking to her (`!waiting`) during it: `comeOut()` cuts to the walk out from the nearer edge.
- `chooseIdle` test: `canHide: true` makes `hide` possible; never while `seated` or `perched`.

- [ ] **Step 1: Write the failing test** `hiding is only chosen standing, with somewhere to hide` in `logic.test.mjs`.
- [ ] **Step 2:** Run node tests; expect fail.
- [ ] **Step 3:** Implement the `IDLE`/`chooseIdle` change, then the page state (`hide = { phase: 'in'|'peek'|'out', id, out, dx, start }`), the API above and the clip.
- [ ] **Step 4:** Run node tests; expect all pass.

### Task 4: The overlay drives it

**Files:**
- Modify: `ui/overlay.py`, `ui/avatar_view.py`
- Test: `tests/test_avatar.py`

**Interfaces:**
- Consumes: Task 1 (`hideouts`, `covering`), Task 3's page API.
- Produces: `AvatarLink.set_hideouts(list)`, `AvatarLink.hidden_by(id, left, right)`, `AvatarLink.set_cover(rect | None)` (`rect` a dict of ints; `set_cover` skips repeats); `AvatarView.ask_travel(answer)` now answers `(travel, behind)`.
- Overlay behaviour, in `_watch_seats` (rename to `_watch_windows`): sends hideouts (edges converted to pixels from her box centre) when not perched; tracks `covering(...)`'s id while she stands idle on her floor (`not self._aloft`, travel done, no hide under way): a *new* id appearing (a window opened or raised over her) → `hidden_by`. Every tick while `behind` is a window id: its rectangle relative to her box → `set_cover`; the window gone → `set_cover(None)` and stop. The covered part of her outline is removed from the X input shape (`xshape.avatar_click_rects` result minus the cover rect) in `_update_mask` (include the cover in the mask key).
- Drag while behind: `set_cover(None)` (the page's `stopTrip` also ends the hide).

- [ ] **Step 1: Write the failing tests** in `tests/test_avatar.py` with fake `open_windows` (pattern of `test_she_is_told_where_to_sit...`):
  `test_she_is_told_where_she_could_hide`;
  `test_a_window_raised_over_her_hides_her_and_she_is_told`;
  `test_while_behind_the_cut_out_follows_the_window_and_goes_with_it` (window moved → new rect; window removed → `setCover(null)`);
  `test_no_hiding_reaction_while_sitting_or_walking`;
  `test_a_drag_while_behind_removes_the_cut_out`;
  `test_clicks_on_the_hidden_part_of_her_go_to_the_app` (input rects exclude the cover).
- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_avatar.py -q`; expect the new tests to fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite `.venv/bin/python -m pytest -q`; expect all pass.

### Task 5: See it, document it, restart

**Files:**
- Modify: `tools/avatar_look.py` (the `--seat` window can be placed on her floor line; it also sends hideouts, cover and `hidden_by` the way the overlay does, sharing the conversion helpers from `ui/overlay.py` if practical), `FEATURES.md`, `CLAUDE.md` (one clause in the avatar paragraph)

- [ ] **Step 1:** Screenshots with a tall test window beside her: `act("hide")` → she walks behind (the covered part not drawn, clean edge), leans out (head and shoulder past the edge), comes back out; and a window opened over her → she peeks from its nearer edge. Fit the lean on her model if her head doesn't clear the edge.
- [ ] **Step 2:** `node --test ui/avatar/logic.test.mjs` and `.venv/bin/python -m pytest -q` all pass.
- [ ] **Step 3:** Update `FEATURES.md` (the idle list: "peeking from behind an app") and restart Aria (aria-restart skill); check the log for `Avatar: ready`.
- [ ] **Step 4:** Ask the user whether to commit.
