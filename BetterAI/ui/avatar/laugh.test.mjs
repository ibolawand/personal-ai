import test from 'node:test';
import assert from 'node:assert/strict';
import { laughMotion, gesture } from './logic.mjs';
import { characterAccent } from './presence.mjs';
const segments = [[0, .17, 'aa', .85, 0, 'laugh'], [.225, .415, 'aa', .85, 0, 'laugh'], [.48, .69, 'aa', .85, 0, 'laugh']];
test('only playing laugh cues move the shoulders, not speech stress or a smile', () => {
  for (const timeline of [null, [], [[0, .5, 'aa', 1, 1]]]) {
    assert.equal(laughMotion(timeline, .1).happy, 0);
    assert.equal(laughMotion(timeline, .1).bones.leftShoulder[2], 0);
  }
  for (const at of [-.1, 1.0]) assert.equal(laughMotion(segments, at).happy, 0);
  assert.deepEqual(characterAccent('amused').bones, {});
  for (let t = 0; t < 2.6; t += .05) {
    const pose = gesture('smile', t, 1);
    assert.ok(!pose.bones?.leftShoulder && !pose.bones?.rightShoulder);
    assert.ok(!pose.lift);
  }
});
test('each audible ha gets a bounce, head tips back and eyes smile, then settle', () => {
  for (const [start] of segments) {
    const p = laughMotion(segments, start + .08);
    assert.ok(p.bones.leftShoulder[2] > .09);
    assert.ok(p.bones.head[0] < -.05 && p.eyes > .5 && p.happy > .6);
  }
  assert.equal(laughMotion(null, .1).eyes, 0); // cleared playback / interruption
  let last = laughMotion(segments, 0);
  for (let t = 1 / 60; t < 1.2; t += 1 / 60) {
    const p = laughMotion(segments, t);
    for (const name of Object.keys(p.bones))
      p.bones[name].forEach((v, i) => assert.ok(Math.abs(v - last.bones[name][i]) < .08));
    last = p;
  }
});
