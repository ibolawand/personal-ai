# Umbrella Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When rain is likely in the next hours, Aria now and then pulls an umbrella from behind her back, opens it with a little snap, rests it on her shoulder for a while (twirling it now and then), then closes it and puts it away.

**Architecture:** Same split as the test card. Python supplies one fact: rain likely or not (`Weather.rain_soon`, already cached 30 min), pushed by the companion loop through a new UI call `set_rain(bool)` → `AvatarLink.set_rain` → `window.aria.setRain`, replayed like other state, also with the companion switched off. The page owns the rest: a long gesture `umbrella` in `logic.mjs` (her right arm's bones per phase, plus `umbrella: { shown, open, dir: [x, y, z], spin }`), an idle entry offered only while rain is set and 20 min have passed, and the umbrella model built in three.js, placed every frame with its handle in her right hand and its shaft along `dir` (turned with her body), so it stays in her grip whatever the arm does.

**Tech Stack:** three.js (vendored), `ui/avatar/logic.mjs` + `node --test`, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-aria-reacts-and-props-design.md` (piece 4 "Umbrella"; built third, as the user asked for it after the card).

## Global Constraints

- Look (spec): canopy of 8 ribbed segments with a slightly scalloped edge, thin shaft, J-handle; colours from her palette (pink / purple); flat unlit colours and a dark outline like her and the card; built in code, no downloads.
- Motion (spec): reach behind her back, bring it forward closed, open with a quick overshoot ("snap"), rest on her shoulder, twirl now and then; closes and goes away after a while.
- Shown when rain probability ≥ 60 % in the next 3 h (`rain_soon(hours=3, threshold=60)`, refreshed at most every 30 min).
- At most every 20 min; only while she stands free (not sitting, perched, walking, jumping, hiding); a fidget, so it gives way when something happens (umbrella goes with her hand, then is gone).
- Commit only when the user asks; FEATURES.md updated.

## Review Focus

1. Rain stops being likely (or the weather can't be read: `None`): `setRain(false)` — no new umbrella; one in her hand finishes.
2. Interrupted mid-umbrella (spoken to): the umbrella shrinks/fades with her arm within ~0.5 s, never left floating or open in the air.
3. A page reload: the rain flag is replayed.
4. A model without hand bones (built-in figure): no umbrella, no crash.
5. She is turned (walking ended mid-turn, `seatYaw`, peeking): the shaft direction turns with her body, not fixed to the screen.

---

### Task 1: The motion and when it's offered (logic.mjs)

**Files:** Modify `ui/avatar/logic.mjs`; Test `ui/avatar/logic.test.mjs`

**Interfaces — Produces:**
- `GESTURES.umbrella = 16`; `'umbrella'` in `FIDGETS`; `IDLE.umbrella = { weight: 4, after: 5 }`; `chooseIdle({... canUmbrella = false })` → weight 0 unless `canUmbrella`.
- `gesture('umbrella', t, side)` → `{ weight, lift: 0, bones, umbrella: { shown, open, dir, spin }, look, face }`. Phases (s): reach behind 0–0.9 (shown rises 0.5→0.9, hand behind her hip, closed, `dir` pointing down); forward and up 0.9–1.8 (closed, `dir` upright); open 1.8–2.3 with overshoot (`open` peaks ≈ 1.12 then settles to 1); onto her shoulder 2.3–3.0 (`dir` tilted back over her right shoulder ≈ [-0.3, 1, -0.45] normalised); hold to 14.4 with a twirl burst now and then (`spin` grows, 1–1.5 turns per burst, twice); close 14.4–15.1 (`open` → 0, `dir` upright); put away behind her 15.1–16 (`shown` → 0). `face.happy` small while held; `look` up at the canopy briefly after it opens.
- Right-arm bones per phase: placeholders now, fitted in Task 3.

- [ ] **Step 1: Write the failing tests**

```js
test('the umbrella comes out closed, snaps open past full, rests open and goes away closed', () => {
  const u = s => gesture('umbrella', s).umbrella;
  assert.equal(u(0).shown, 0);
  assert.ok(u(1.2).shown > 0.9 && u(1.2).open < 0.05);
  assert.ok(Math.max(...[2.0, 2.1, 2.2, 2.3].map(s => u(s).open)) > 1.05);
  assert.ok(Math.abs(u(8).open - 1) < 0.01 && u(8).shown === 1);
  assert.ok(u(8).dir[2] < -0.2 && u(8).dir[1] > 0.6);          // tilted back over her shoulder
  assert.ok(u(15.2).open < 0.05);
  assert.ok(u(15.95).shown < 0.05);
  assert.equal(gesture('umbrella', 16.1), null);
  assert.ok(FIDGETS.includes('umbrella'));
});

test('she twirls it now and then while it rests', () => {
  const spin = s => gesture('umbrella', s).umbrella.spin;
  assert.ok(spin(13) - spin(3.5) > 2 * Math.PI * 1.5);
  assert.equal(spin(4.5), spin(4.6));                             // still between twirls
});

test('the umbrella is offered only when rain is coming, and never sitting', () => {
  const others = Object.keys(IDLE).filter(n => n !== 'umbrella');
  const pick = canUmbrella => chooseIdle({ idleFor: 60, canUmbrella, recent: others }, 0.0, 0.3);
  assert.equal(pick(true).gesture, 'umbrella');
  assert.notEqual(pick(false).gesture, 'umbrella');
  for (const r of [0, 0.5, 0.99]) {
    assert.notEqual(chooseIdle({ idleFor: 60, canUmbrella: true, seated: true }, r, 0.3).gesture, 'umbrella');
    assert.notEqual(chooseIdle({ idleFor: 60, canUmbrella: true, perched: true }, r, 0.3).gesture, 'umbrella');
  }
});
```

- [ ] **Step 2:** `node --test ui/avatar/logic.test.mjs` → the new tests fail (`umbrella` undefined).
- [ ] **Step 3:** Implement. Phase timing via the existing `smooth`; overshoot: `1 + 0.14·e^(−k·u)·sin(…)` style settle after a fast rise.
- [ ] **Step 4:** All node tests pass.

### Task 2: The umbrella on the page, and the rain flag from Python

**Files:** Modify `ui/avatar/avatar.js`, `ui/avatar_view.py`, `ui/overlay.py`, `main.py` (NullUI), `Engines/Companion.py`; Test `tests/test_avatar.py`, `tests/test_companion.py`

**Interfaces:**
- Produces: `AvatarLink.set_rain(on: bool)` → `window.aria.setRain(true|false)`, kind `"rain"`, in `REPLAY`, repeats skipped. `OverlayBridge.set_rain(on)` (signal `rainChanged = Signal(bool)`) → link. `NullUI.set_rain`. `Companion._send_rain()` called next to `_send_test` (also when disabled): `ui.set_rain(bool(_ask(p.rain_soon)))` when it changed (None → False).
- Page: `rainComing` flag; `umbrellaAt` (−∞); `canUmbrella: rainComing && t - umbrellaAt > 1200 && hand bones`; `begin` sets `umbrellaAt` for `'umbrella'` (inside the gesture branch). Model: shaft (thin cylinder, 0.36 long), J-handle (half torus + short stub) at the bottom, ferrule tip at top, 8 ribs, canopy of 8 panels whose rim sags between rib tips (scallop), panels alternating `0xffb3d1` / `0xc9a8ff`, inner side a darker shade (BackSide mesh), dark outline lines `0x3a2a4a` along the rim and ribs. Openness changes the rib angle (closed ≈ 0.12 rad from the shaft, open ≈ 1.2 rad) by rewriting the few vertex positions each frame. Placement each frame while `shown > 0`: handle grip point at `rig.where('rightHand')`; shaft direction = `dir` rotated by her body's yaw (`rig.root` world quaternion); rotation about the shaft = `spin`; scale 0.7 + 0.3·shown; opacity = shown. Hidden otherwise.

- [ ] **Step 1: Failing tests:** `test_rain_flag_is_replayed_and_repeats_skipped(link)`; `test_bridge_set_rain_reaches_the_page(app, stage)`; `test_rain_is_sent_when_it_changes(world)` (FakeUI `set_rain` → `ui.rains`; `world.rain=True` → `[True]`; same → once; `None` → `False` appended); disabled companion still sends it.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** pytest + node pass; load the page, `setRain(true); act('umbrella')`, no JS error.

### Task 3: Fit the arm and check by eye

- [ ] Fit (in-page, `tune` + `advance` + `where` relative to `upperChest`, `setEngaged(true)`) right-arm poses for: behind her hip (≈ [-0.10, -0.30, -0.10]), up in front (≈ [-0.07, +0.02, 0.14]), resting near her right shoulder (≈ [-0.09, -0.11, 0.09]); put them in `gesture('umbrella')`.
- [ ] Film it (locked-screen mode works): 0.5, 1.4, 2.05 (snap), 2.6, 6, a twirl, 14.8, 15.6; plus an interrupted one. Fix what looks wrong (size, grip point, tilt, colours, outline).

### Task 4: Docs, suites, review

- [ ] FEATURES.md bullet; full suites; fresh reviewer; fix pass; restart Aria; report.
