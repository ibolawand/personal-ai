// node --test ui/avatar/claudelogic.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { gestureFor, facing, entrance, exit, ENTER_S, LEAVE_S, expressionFor, visibility, boneFollow, voiceLevel } from './claudelogic.mjs';
import { GESTURES } from './logic.mjs';

test('every feeling has a gesture Aria\'s logic knows, or none', () => {
  for (const f of ['happy', 'excited', 'laugh', 'teasing', 'curious', 'thinking', 'soft', 'sad', 'neutral', 'unknown']) {
    const g = gestureFor(f);
    assert.ok(g === null || g in GESTURES, f);
  }
  assert.equal(gestureFor('thinking'), 'think');
  assert.equal(gestureFor('neutral'), null);
});

test('he turns toward Aria, most while listening', () => {
  const listen = facing('listening', 1), talk = facing('talking', 1);
  assert.ok(listen.head > talk.head && talk.head > 0);
  assert.ok(facing('listening', -1).head < 0);
  assert.ok(Math.abs(listen.eyes) <= 1);
});

test('he pops in a touch too big and settles, and shrinks away', () => {
  assert.deepEqual(entrance(0), { scale: 0, lift: 0 });
  assert.equal(entrance(ENTER_S).scale, 1);
  const peak = Math.max(...Array.from({ length: 50 }, (_, i) => entrance(i * ENTER_S / 50).scale));
  assert.ok(peak > 1 && peak < 1.2, peak);
  assert.equal(exit(LEAVE_S).scale, 0);
  assert.ok(exit(LEAVE_S * 0.8).scale < exit(LEAVE_S * 0.4).scale);
});

test('his face follows the feeling', () => {
  assert.equal(expressionFor('happy').happy, 1);
  assert.ok(expressionFor('sad').relaxed > 0 && expressionFor('sad').happy === 0);
});

test('interrupting an entrance or exit preserves the visible pose and still finishes', () => {
  const arriving = visibility(0.2, true);
  assert.deepEqual(visibility(0, false, arriving), arriving);
  const leaving = visibility(0.1, false, arriving);
  assert.deepEqual(visibility(0, true, leaving), leaving);
  assert.deepEqual(visibility(ENTER_S, true, leaving), { scale: 1, lift: 0 });
  assert.deepEqual(visibility(LEAVE_S, false, arriving), { scale: 0, lift: 0 });
  for (const entering of [false, true]) {
    for (let i = 0; i <= 100; i++) {
      const pose = visibility(i / 100, entering, arriving);
      assert.ok(Number.isFinite(pose.lift) && pose.scale >= 0 && pose.scale < 1.2);
    }
  }
});

test('bone smoothing converges equally over a second at different frame rates', () => {
  const advance = fps => {
    let angle = 0;
    for (let i = 0; i < fps; i++) angle += (1 - angle) * boneFollow(1 / fps);
    return angle;
  };
  assert.equal(boneFollow(0), 0);
  assert.ok(Math.abs(boneFollow(1 / 30) - 0.5) < 1e-12);
  assert.ok(Math.abs(advance(15) - advance(60)) < 1e-12);
});

test('invalid voice levels never reach the animation', () => {
  for (const value of [NaN, Infinity, -Infinity, undefined, 'bad', -0.2]) assert.equal(voiceLevel(value), 0);
  assert.equal(voiceLevel(2), 1);
  assert.equal(voiceLevel('0.4'), 0.4);
});
