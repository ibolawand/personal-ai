---
name: aria-avatar-animation
description: Use for any work on Aria's 3D avatar in ui/avatar/ (new gestures, idle moments, reactions, poses, timing, refining how she moves). Holds the bone convention, the gesture machinery, the craft rules learned from filming her, and the workflow.
---

# Aria's avatar: how to build and refine her movement

Also read `senior-3d-audio-engineer` (references/aria-avatar.md, references/animation-craft.md). Lala values, in
order: detailed animation > how alive she feels > how human > useful.

## Where things live
- `ui/avatar/logic.mjs`, `ui/avatar/presence.mjs`: every decision, as pure functions (poses, gestures, timing, when
  something fires). Tests: `ui/avatar/logic.test.mjs`, `presence.test.mjs` (`node --test ui/avatar/*.test.mjs`).
- `ui/avatar/avatar.js`: applies decisions each frame in `move(dt)`; `window.aria` is what the overlay calls.
  Keep it thin. `start(name, side)` / `begin(...)` start gestures; `doing` is the gesture under way.
- Rigs: `vrmrig.mjs` (the VRM Lala uses) and `figure.mjs` (built-in fallback; NO shoulder bones: shoulder detail may
  be missing there, the movement must still work). Shared methods: `setBone, setBlink, setExpression, look, node,
  wrist, fingerTip`. IK: `makeIK(THREE).reach(rig, side, target, pole, w, point, weights, pointTarget)` in piano.mjs.
- Host: `ui/avatar_view.py` (`AvatarLink`: Python → page calls; `_send(kind, js, value, repeat=False)` dedupes; kind
  None = one-off, dropped if the page isn't ready), `ui/overlay.py` (`_feed_avatar`, `_watch_seats`, mouse events),
  `ui/desktop_windows.py` (pure window geometry).

## Bone convention (radians [x, y, z, twist?], figure facing the viewer)
- HER LEFT arm is along +x = the viewer's RIGHT. Screen look x positive = viewer's right = her left.
- x: positive = spine/head forward (nod); negative = an arm or thigh forward.
- y: turn; elbow bend (left arm negative, right arm positive, up to 2.5).
- z: tilt; arm lowering: rest about -1.3 left / +1.3 right (toward 0 raises the arm out sideways). A shoulder comes UP
  with +z on the left, -z on the right. Positive z on chest/head tilts her toward HER right (viewer's left).
- `mirrorSide(bones, side)` mirrors angle dicts for side -1 (names left↔right, y and z negated). It does NOT work on
  weight dicts: build those with names (`const sl = side === 1 ? 'left' : 'right'`).

## Gesture machinery (logic.mjs)
`gesture(name, t, side)` returns `{ weight, bones (replace, blended by weight), weights (per-bone lead), adds (added on
top of any pose), hands, eyes, look, face, lift, ik, calm, ownBlinks, alert }`. Register: `GESTURES` (length s),
`FIDGETS` (gives way when something happens), `IDLE` (`weight`, `after`, `every`), `SEATED_FIDGETS`,
`PERCHED_FIDGETS`; rules in `chooseIdle`. Breaking off: `cutShort`. Helpers: `smooth`, `windUp`, `overshoot`,
`armEntry`/`armRelease`, `HANDS`, `mixHand`, `otherHands`. Seated/perched-safe gestures use `adds` only.

## Craft rules (each one came from a real defect seen on film)
- Every movement: anticipation, action, follow-through, settle. Offset parts: eyes → head → chest; shoulder → upper
  arm → elbow → wrist → fingers (fingers last, one after another). Ease everything; nothing linear; no pops.
- **Arm going UP: the upper arm leads, the elbow folds after it** (else the hand flies to her face first: the sleeve
  brush looked like rubbing her eye). **Arm coming DOWN: the upper arm leads, the forearm keeps its bend until the
  upper arm is mostly down** (else a straight arm sticks out sideways, then snaps down). Use `armEntry`/`armRelease`.
- **Hands near the face**: keep them where they mean something (under the nose for a sneeze, temple for a hair tuck,
  mouth for a gasp) and nowhere else; a hand to inspect sits in front of the upper chest, a forearm's length away.
  Fingers raised past a wrist at head height cover the face (read as a salute).
- **Big enough to see**: a 0.03 rad change is invisible at her size; a visible flinch is ~0.07 chest, ~0.05
  shoulders. Subtle is fine for breathing, not for a reaction meant to be noticed.
- **Measure, don't guess** poses that must land somewhere: `aria-film` (tune + where). Guessed arm angles failed
  three times in a row for one gesture.
- Frame-rate independent (`dt`, `ease`, `spring`), capped after pauses. State always resets. Every behaviour gives
  way cleanly to carry, walk, sit, perch, the piano, a duet and speech (check `idleNow`, `doing`, `walk`, `sit`,
  `perched`, `jumping`, `hide`, `visit`, `carry`, `held`, `atPiano`, `atDesk`).
- Idle GPU stays low; nothing new renders when nothing moves.

## Workflow
1. Decision + timing in logic.mjs/presence.mjs; tests for order of parts, when it fires and when it must not,
   cancellation, continuity (no per-frame jump above ~0.08 rad at 60 fps).
2. Thin application in avatar.js.
3. Look at it (`aria-film`). If the sandbox can't open a display, say so and give the exact command.
4. `FEATURES.md` (avatar section) when what she does changes.
