import test from 'node:test';
import assert from 'node:assert/strict';
import { resting, sleepAction, wakeAction, sleepAllowsActivity } from './sleep.mjs';
const free = { asleep: true, busy: false, seated: false, perched: false, sinceRest: 20, sinceDoze: 60 };
test('sleep and companion rest; focus and waking take ownership', () => {
  for (const state of ['sleeping', 'companion']) {
    assert.equal(resting(state), true);
    assert.equal(resting(state, 'work'), false);
  }
  for (const state of ['idle', 'listening', 'thinking', 'speaking']) assert.equal(resting(state), false);
});
test('find an edge, otherwise sit on the floor; remain seated and doze occasionally', () => {
  assert.deepEqual(sleepAction({...free, canPerch: true}), {perch: true});
  assert.deepEqual(sleepAction(free), {sit: true});
  for (const seat of ['seated', 'perched']) {
    assert.deepEqual(sleepAction({...free, [seat]: true}), {gesture: 'doze'});
    assert.equal(sleepAction({...free, [seat]: true, sinceDoze: 10}), null);
    assert.equal(sleepAction({...free, [seat]: true, sinceRest: 2}), null);
  }
});
test('wake, carry, travel, reactions and sitting transitions preempt sleep choices', () => {
  assert.equal(sleepAction({...free, asleep: false}), null);
  assert.equal(sleepAction({...free, busy: true}), null);
});

test('waking stands from the floor and leaves an edge after any jump finishes', () => {
  assert.deepEqual(wakeAction({waking: true, seated: true}), {stand: true});
  assert.deepEqual(wakeAction({waking: true, perched: true}), {hopDown: true});
  assert.equal(wakeAction({waking: true, perched: true, jumping: true}), null);
  assert.equal(wakeAction({waking: false, perched: true}), null);
});

test('quiet sleep ignores music and window surprises, companion keeps its reactions', () => {
  assert.equal(sleepAllowsActivity('sleeping'), false);
  for (const state of ['companion', 'idle', 'listening']) assert.equal(sleepAllowsActivity(state), true);
});
