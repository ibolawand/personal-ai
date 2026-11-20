// The pure parts of her motion clips (motions.mjs): which frame a time falls on, and that the bone map is whole.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { frameAt, RIGS, PARENT, MOVED, SOURCES, MASKS, walkTime } from './motions.mjs';
import { BONES } from './logic.mjs';

test('a clip loops: time past its end comes round to the start, and in between frames is a share', () => {
  assert.deepEqual(frameAt(0, 30), [0, 1, 0]);
  const [i, j, k] = frameAt(0.5 + 1 / 60, 30);
  assert.equal(i, 15); assert.equal(j, 16); assert.ok(Math.abs(k - 0.5) < 1e-6);
  assert.deepEqual(frameAt(29.5 / 30, 30).slice(0, 2), [29, 0]);           // the last frame blends into the first
  assert.deepEqual(frameAt(-1 / 30, 30).slice(0, 2), [29, 0]);
});

test('every bone her code moves gets the clip, and every bone has its parent in the map', () => {
  for (const rig of Object.values(RIGS)) {
    for (const b of BONES) assert.ok(rig[b], b);
    for (const b of MOVED) assert.ok(rig[b], b);
    assert.ok(rig.toes);
  }
  for (const b of BONES) assert.ok(MOVED.includes(b), b);
  assert.equal(PARENT.hips, undefined);
  const keys = SOURCES.flatMap(s => Object.keys(s.clips));
  for (const k of ['sit', 'sitTalk', 'walk']) assert.ok(keys.includes(k), k);
});

test('sitting moves only her body above the hips; walking all of her', () => {
  for (const leg of ['leftUpperLeg', 'rightLowerLeg', 'leftFoot']) {
    assert.ok(!MASKS.sit[leg]);
    assert.equal(MASKS.full[leg], 1);
  }
  assert.ok(!MASKS.sit.hips && MASKS.full.hips && MASKS.sit.chest && MASKS.sit.leftHand);
});

test('a walk clip follows her steps: her left leg forward (phase π/2) is the clip\'s left leg forward', () => {
  const clip = { duration: 1.2, lead: 0.3, cycles: 1 };
  assert.ok(Math.abs(walkTime(Math.PI / 2, clip) - 0.3) < 1e-9);
  assert.ok(Math.abs(walkTime(Math.PI / 2 + Math.PI, clip) - 0.9) < 1e-9);             // half a stride on
  assert.ok(Math.abs(walkTime(Math.PI / 2 + 4 * Math.PI, clip) - 0.3) < 1e-9);         // two strides on: the same
  assert.ok(Math.abs(walkTime(Math.PI / 2 + Math.PI, { ...clip, cycles: 2 }) - 0.6) < 1e-9);
});
