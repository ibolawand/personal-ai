# Test card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a WebUntis test is within 7 days, Aria now and then (at most once an hour, while idle and standing) holds up a small paper card in both hands with the subject and when ("Maths · Thursday"), looks at you with a little smile, and puts it away.

**Architecture:** Python only supplies the data: the companion loop already reads the next test (`Probes.next_test`, a `TestPrep` card dict) and now pushes `{subject, when}` (or `None`) through a new UI call `set_test`, replayed to the page like other state (`AvatarLink.set_test` → `window.aria.setTest`). The page owns the rest: a new gesture `showCard` (bones fitted on her model, plus `card` 0…1 for how far it is up), an idle entry that is only offered while a test is set and an hour has passed, and the card itself built in three.js and placed between her two hands every frame (so it stays in her grip whatever the arms do).

**Tech Stack:** three.js (vendored), `ui/avatar/logic.mjs` + `node --test`, PySide6 overlay, pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-aria-reacts-and-props-design.md` (piece 2, "Test card").

## Global Constraints

- Card look (spec): paper-coloured rounded rectangle with a slight bend and an outline; text on a canvas texture: subject + "Thursday"/"tomorrow"/"today"/"in N days"; held in both hands, raised to chest height, small tilt, she looks at the viewer; ~4 s; then put away.
- Her style: flat unlit colours like the other props (`MeshBasicMaterial`), a dark outline (inverted hull), no downloaded assets or fonts beyond the page's own.
- At most about once an hour; only while a test is within 7 days (TestPrep's window); only while she stands free (not sitting, perched, walking, jumping or hiding — the idle picker already keeps standing-only moves out of the sitting/perched lists).
- Text comes from Python, drawn as text only (canvas `fillText`, never HTML).
- Commit only when the user asks; FEATURES.md updated in the last task.

## Review Focus

1. A subject name that's long ("Softwareentwicklung") or has umlauts: the text must shrink to fit the card, never spill off it.
2. The test passes (no test within 7 days, or TestPrep fails): `setTest(null)` — the card is never offered again until a new test appears; one already in her hands finishes normally.
3. A page reload (Aria restarted, page re-created): the current test is replayed so the card works without waiting 10 min.
4. She's told to do something else mid-card (spoken to, a wave): the gesture is cut like other fidgets and the card goes with her hands (no card left floating).
5. A model without hand bones (the built-in figure): no card, no crash.

---

### Task 1: The gesture and when it's offered (logic.mjs)

**Files:**
- Modify: `ui/avatar/logic.mjs` (`GESTURES`, `FIDGETS`, `IDLE`, `chooseIdle`, `gesture`, new `cardText`)
- Test: `ui/avatar/logic.test.mjs`

**Interfaces:**
- Produces:
  - `GESTURES.showCard = 4.6` (seconds); `'showCard'` in `FIDGETS` (so it gives way like other fidgets).
  - `IDLE.showCard = { weight: 3, after: 8 }`; `chooseIdle({... canCard = false })` gives it weight 0 unless `canCard`.
  - `gesture('showCard', t)` → `{ weight, lift: 0, bones, card, look: [0, 0.05], face: { happy } }`; `card` 0→1 over 0.25–0.9 s, 1 until 3.7 s, →0 by 4.4 s. Bones: both arms bring the hands up in front of her chest, about a card's width apart (fitted on her model in Task 3; until then a reasonable first guess), head tilted a little (`head: [0.04, 0, 0.1]`), chest a touch forward.
  - `cardText({subject, when})` → `{ big, small }`: `big` = subject trimmed to ≤ 18 chars (with "…"), `small` = `when` ("today", "tomorrow", a weekday) or "" ; null/invalid input → null.

- [ ] **Step 1: Write the failing tests** (in `logic.test.mjs`)

```js
import { cardText } from './logic.mjs';   // plus GESTURES, IDLE, FIDGETS, gesture, chooseIdle already imported

test('the card is up in the middle of the gesture and away at both ends', () => {
  assert.equal(gesture('showCard', 0).card, 0);
  assert.equal(gesture('showCard', 2).card, 1);
  assert.ok(gesture('showCard', 4.45).card < 0.05);
  assert.deepEqual(gesture('showCard', 2).look, [0, 0.05]);
  assert.ok(gesture('showCard', 2).face.happy > 0.3);
  assert.equal(gesture('showCard', 4.7), null);
});

test('the card is offered only when there is a test to show', () => {
  const pick = canCard => chooseIdle({ idleFor: 60, canCard, recent: Object.keys(IDLE).filter(n => n !== 'showCard') }, 0.0, 0.3);
  assert.equal(pick(true).gesture, 'showCard');
  assert.notEqual(pick(false).gesture, 'showCard');
  assert.ok(!chooseIdle({ idleFor: 60, canCard: true, seated: true }, 0.99, 0.3).gesture?.includes('showCard'));
});

test('card text fits', () => {
  assert.deepEqual(cardText({ subject: 'Maths', when: 'Thursday' }), { big: 'Maths', small: 'Thursday' });
  assert.equal(cardText({ subject: 'Softwareentwicklung und Projektmanagement', when: 'tomorrow' }).big.length, 18);
  assert.equal(cardText(null), null);
  assert.equal(cardText({ subject: '  ' }), null);
});
```

- [ ] **Step 2: Run, expect failures** — `node --test ui/avatar/logic.test.mjs` → SyntaxError (no export `cardText`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect pass** — all node tests pass.

---

### Task 2: The card on the page, and the data from Python

**Files:**
- Modify: `ui/avatar/avatar.js` (card mesh, `setTest`, `canCard` + hourly cooldown in the idle call, placing the card each frame from `rig.where('leftHand'/'rightHand')`)
- Modify: `ui/avatar_view.py` (`AvatarLink.set_test`), `ui/overlay.py` (`OverlayBridge.set_test` + signal → link), `main.py` (`NullUI.set_test`), `Engines/Companion.py` (push the next test each tick when it changed)
- Test: `tests/test_avatar.py`, `tests/test_companion.py`

**Interfaces:**
- Consumes: Task 1 `cardText`, `gesture('showCard').card`, `chooseIdle({canCard})`.
- Produces:
  - `AvatarLink.set_test(card: dict | None)` → `window.aria.setTest(<json {subject, when} | null>)`, kind `"test"`, replayed, repeats skipped.
  - `OverlayBridge.set_test(card)` (thread-safe signal `testChanged = Signal(object)`); overlay calls `avatar.link.set_test` (the link queues it until the page is ready).
  - `Companion.tick()` calls `ui.set_test({"subject", "when"} | None)` whenever the next test (`_ask(p.next_test)`) differs from the last one sent — also while Aria is awake (it's data, not a state change).
  - Page: `window.aria.setTest(obj|null)`; `cardAt` (time of the last card, start −∞); `canCard = !!testCard && t - cardAt > 3600 && rig.hasHands`; begin of `showCard` sets `cardAt = t`. The card group: a bent rounded-rectangle `ShapeGeometry`/plane (≈0.17 × 0.12 units, 12×1 segments bent ~0.012 at the middle), paper `0xfff6e8`, outline inverted hull `0x3a2a4a` (scaled 1.05, `BackSide`), text texture (canvas 512×360: subject bold in `#5b3fa0`, auto-shrunk to fit; `when` below in `#2b2740`; a tiny star doodle). Each frame while `card > 0`: position = midpoint of the hands + 0.02 toward the viewer, faces the camera, `rotation.z` = slope between the hands, scale × (0.6 + 0.4·card), opacity = card. Hidden otherwise. No hand bones (`where` returns null) → no card.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_avatar.py::test_test_card_data_is_replayed_and_repeats_skipped(link)`: `link.set_test({"subject": "Maths", "when": "Thursday"})` before ready → after `mark_ready()` sent once as `window.aria.setTest({"subject": "Maths", "when": "Thursday"})`; same again → nothing; `set_test(None)` → `window.aria.setTest(null)`.
  - `tests/test_avatar.py::test_bridge_set_test_reaches_the_page(app, stage)`: `bridge.set_test({...})`, processEvents → the call is in `view.sent`.
  - `tests/test_companion.py::test_next_test_is_sent_when_it_changes(world)`: step → `ui` log has `("test", {"subject": "Maths", "when": "Thursday"})` once; two more steps → still once; `world.test = None`; step → `("test", None)`. (FakeUI gets `set_test`.) Also sent while `aria.awake`.
- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement** the Python side, then the page side.
- [ ] **Step 4: Run** `pytest -q` and `node --test ui/avatar/logic.test.mjs` → all pass. Load the page with `tools/avatar_look.py` and call `window.aria.setTest({subject:'Maths',when:'Thursday'}); window.aria.act('showCard')`, push `window.aria.where('leftHand','rightHand')` to `ariaLog`: no JS error.

---

### Task 3: Fit the holding pose and check it by eye

**Files:**
- Modify: `ui/avatar/logic.mjs` (the `showCard` bone values)

- [ ] **Step 1:** In the page (`tools/avatar_look.py`, `window.aria.tune`, `window.aria.where`, 85 ms per evaluation, gaze held), fit left upper arm (x, y, z, twist) and lower arm (y) so the left hand lands at chest height (`where('upperChest')` y, or chest + 0.02), 0.085 units to her left of her midline and 0.11 in front of the chest; mirror for the right. Record the values.
- [ ] **Step 2:** Put the fitted values in `gesture('showCard')`; rerun the node tests (still pass).
- [ ] **Step 3: Look at her.** Screenshots at 0.5 s, 2 s (card up) and 4.2 s; front and slightly turned. The card must sit in her hands, text readable, outline visible, not cutting into her body. Fix what looks wrong (card offset, size, bend) and shoot again.

---

### Task 4: Docs and real check

- [ ] **Step 1:** `FEATURES.md`: a "test card" bullet under the companion / avatar section (when, how often, what's on it).
- [ ] **Step 2:** Full suites; restart Aria; log shows no traceback. (The card only appears when TestPrep finds a test within 7 days; say so if there is none now.)
- [ ] **Step 3:** Report; no commit unless asked.
