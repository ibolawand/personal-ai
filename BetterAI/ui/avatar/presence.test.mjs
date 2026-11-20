import test from 'node:test';
import assert from 'node:assert/strict';
import { acknowledgement, focusStage, focusBody, writing, conversationMotion, activeBody, LISTEN, listenStep, listenAway, listenNod, turnCue, WINDOW_VISIT, planWindowVisit, windowVisitMotion, CHARACTER_MOODS, characterAccent, characterMood, vrmCharacterExpressions, poseTransitionTime } from './presence.mjs';
import { listeningNod } from './claudelogic.mjs';
import * as THREE from './vendor/three.module.js';
import { buildFigure } from './figure.mjs';
import { makeIK } from './piano.mjs';
import { buildFocusDesk } from './focusdesk.mjs';
import { BONES, poseFor, pianoLayout, PIANO, chooseIdle, gesture, GESTURES } from './logic.mjs';

test('acknowledgements are brief, bounded and reject unknown events', () => {
  assert.equal(acknowledgement('failed', 1), null);
  assert.equal(acknowledgement('taskDone', -1), null);
  assert.equal(acknowledgement('taskDone', 2.4), null);
  assert.equal(acknowledgement('noteSaved', 0).shown, 0);
  for (let t = 0; t < 2.4; t += 0.02) {
    const a = acknowledgement('timerSaved', t);
    assert.ok(a.shown >= 0 && a.shown <= 1 && Number.isFinite(a.nod));
  }
});

test('desk puts hands down after sitting, lifts them before standing and survives interruptions', () => {
  assert.equal(focusStage(0.4, true).hands, 0);
  assert.equal(focusStage(2, true).sit, 1);
  assert.equal(focusStage(0.5, false).hands, 0);
  const midway = focusStage(0.7, true);
  for (const k of Object.keys(midway)) assert.ok(Math.abs(focusStage(0, false, midway)[k] - midway[k]) < 1e-12);
  const leaving = focusStage(0.3, false, midway);
  for (const k of Object.keys(leaving)) assert.ok(Math.abs(focusStage(0, true, leaving)[k] - leaving[k]) < 1e-12);
  assert.deepEqual(focusStage(2, false, midway), { hands: 0, sit: 0, turn: 0, show: 0 });
  for (let t = 0; t < 3; t += 0.02) for (const v of Object.values(focusStage(t, false, midway))) assert.ok(v >= 0 && v <= 1);
  const early = focusStage(0.15, true);
  let last = early;
  for (let t = 0; t < 3; t += 0.02) {
    const current = focusStage(t, false, early);
    for (const k of Object.keys(current)) assert.ok(current[k] <= last[k] + 1e-12, 'leaving never grows an interrupted desk');
    last = current;
  }
});

test('writing pauses and conversation listening stays subtle and points toward either partner', () => {
  assert.ok(writing(10).pause > writing(3).pause);
  assert.ok(conversationMotion(1, 'claude', -1).gaze < 0);
  assert.ok(conversationMotion(1, 'claude', 1).gaze > conversationMotion(1, 'aria', 1).gaze);
  assert.deepEqual(conversationMotion(1, 'off'), { gaze: 0, nod: 0 });
  assert.equal(listeningNod(1, 'talking'), 0);
  assert.ok(listeningNod(1, 'listening') <= 0.05);
});

test('the real desk and built-in rig animate with finite transforms through a complete work/break cycle', () => {
  const rig = buildFigure(THREE);
  const rest = poseFor('idle').bones;
  for (const name of BONES) rig.setBone(name, rest[name]);
  rig.root.updateMatrixWorld(true);
  const at = name => new THREE.Vector3(...rig.where(name));
  const hip = at('leftUpperLeg'), knee = at('leftLowerLeg'), shoulder = at('leftUpperArm'), elbow = at('leftLowerArm');
  const layout = pianoLayout({ hip: hip.y, thigh: hip.distanceTo(knee), shin: knee.y,
    shoulder: shoulder.y - hip.y, upperArm: shoulder.distanceTo(elbow) });
  const desk = buildFocusDesk(THREE, layout);
  for (const on of [true, false]) for (let t = 0; t <= 3; t += 1 / 30) {
    const stage = focusStage(t, on), body = focusBody(stage, t);
    for (const name of BONES) rig.setBone(name, body[name] || rest[name]);
    rig.root.position.y = layout.lift * stage.sit;
    rig.root.rotation.y = PIANO.yaw * stage.turn;
    desk.update(rig, stage, t, 0);
    if (stage.hands > 0.5) {
      const pen = desk.group.getObjectByName('focus-pen');
      const wrist = rig.wrist('right'), actual = pen.getWorldPosition(new THREE.Vector3());
      assert.ok(actual.distanceTo(wrist) < 0.04, 'pen stays in the built-in figure’s hand');
    }
    rig.root.updateMatrixWorld(true);
    for (const root of [rig.root, desk.group]) root.traverse(node => {
      assert.ok(node.matrixWorld.elements.every(Number.isFinite), node.name);
      assert.ok(node.quaternion.toArray().every(Number.isFinite), node.name);
    });
  }
  desk.update(rig, focusStage(3, false), 3, 0);
  assert.equal(desk.group.visible, false);
});


test('active body language stays quiet in silence and alternates speaking hands', () => {
  assert.deepEqual(activeBody('idle', 3, 1), {});
  for (const state of ['listening', 'speaking']) {
    for (let t = 0; t < 30; t += 0.05) {
      for (const angles of Object.values(activeBody(state, t, 0))) {
        assert.ok(angles.every(v => v === 0), `${state} moves without voice activity`);
      }
    }
  }
  assert.ok(activeBody('speaking', 1.5, 1).rightLowerArm[1] > 0.4);
  assert.ok(activeBody('speaking', 8.3, 1).leftLowerArm[1] < -0.4);
  assert.equal(activeBody('speaking', 3.5, 1).rightLowerArm[1], 0, 'hands rest between phrases');
  assert.equal(activeBody('listening', 1.5, 1).head, undefined, 'no nods on a clock: they come at your pauses');
  assert.ok(activeBody('thinking', 2.5).head[1] < 0);
  assert.equal(activeBody('thinking', 2.5).rightHand, undefined, 'chin hand remains anchored');
});

test('conversation movements stay bounded and continuous across repeated cycles', () => {
  for (const state of ['listening', 'thinking', 'speaking']) {
    let previous = {};
    for (let t = 0; t < 35; t += 1 / 120) {
      const body = activeBody(state, t, 1);
      for (const name of new Set([...Object.keys(body), ...Object.keys(previous)])) {
        assert.ok(BONES.includes(name));
        assert.ok(!/Leg|Foot|hips/.test(name), 'conversation never moves planted feet');
        for (let i = 0; i < 3; i++) {
          const value = body[name]?.[i] || 0, last = previous[name]?.[i] || 0;
          assert.ok(Number.isFinite(value) && Math.abs(value) <= 0.5);
          assert.ok(Math.abs(value - last) < 0.015, `${state}: ${name} jumps at ${t}`);
        }
      }
      previous = body;
    }
    assert.deepEqual(activeBody(state, 2, 5), activeBody(state, 2, 1));
    assert.ok(Object.values(activeBody(state, 0, 1)).flat().every(v => v === 0));
  }
});


test('turn cues prepare a reply and give attention back without inventing emotion', () => {
  assert.ok(turnCue('thinking', 'speaking', 0.4).bones.chest[0] < 0);
  for (const to of ['listening', 'idle']) {
    const cue = turnCue('speaking', to, 0.4);
    assert.ok(cue.attention > 0.9);
    assert.ok(cue.bones.chest[0] > 0);
    assert.equal(cue.face, undefined);
  }
  for (const [from, to] of [['thinking', 'speaking'], ['speaking', 'listening'], ['speaking', 'idle']]) {
    assert.ok(Object.values(turnCue(from, to, 0).bones).flat().every(v => v === 0));
    assert.deepEqual(turnCue(from, to, -1), { bones: {}, attention: 0 });
    assert.deepEqual(turnCue(from, to, 2.2), { bones: {}, attention: 0 });
    let previous = {};
    for (let t = 0; t < 2.3; t += 1 / 120) {
      const cue = turnCue(from, to, t);
      assert.ok(cue.attention >= 0 && cue.attention <= 1);
      for (const [name, angles] of Object.entries(cue.bones)) {
        assert.ok(BONES.includes(name));
        for (let i = 0; i < 3; i++) assert.ok(Math.abs(angles[i] - (previous[name]?.[i] || 0)) < 0.004);
      }
      previous = cue.bones;
    }
  }
  assert.deepEqual(turnCue('listening', 'listening', 0.4), { bones: {}, attention: 0 });
  assert.deepEqual(turnCue('idle', 'thinking', 0.4), { bones: {}, attention: 0 });
});

test('turn variations change leading hand and timing while preserving quiet gaps', () => {
  assert.ok(activeBody('speaking', 1.6, 1, 0).rightLowerArm);
  assert.ok(activeBody('speaking', 1.6, 1, 1).leftLowerArm);
  for (let variant = 0; variant < 5; variant++) {
    let previous = {}, quiet = 0;
    for (let t = 0; t < 24; t += 1 / 120) {
      const body = activeBody('speaking', t, 1, variant);
      if (Object.values(body).flat().every(v => v === 0)) quiet++;
      for (const name of new Set([...Object.keys(body), ...Object.keys(previous)])) {
        for (let i = 0; i < 3; i++) {
          const value = body[name]?.[i] || 0;
          assert.ok(Number.isFinite(value) && Math.abs(value) <= 0.5);
          assert.ok(Math.abs(value - (previous[name]?.[i] || 0)) < 0.015);
        }
      }
      previous = body;
    }
    assert.ok(quiet > 120, 'each variation includes stillness');
    assert.ok(Object.values(activeBody('speaking', 1.6, 0, variant)).flat().every(v => v === 0));
  }
});


test('window visits use visible reachable edges, stay on screen and vary destinations', () => {
  const edges = [{ id: 1, x: -0.6, out: 1 }, { id: 2, x: 0.7, out: -1 }];
  const room = { left: 1, right: 1 };
  assert.equal(planWindowVisit([], room), null);
  assert.equal(planWindowVisit(edges, null), null);
  assert.equal(planWindowVisit([{ id: 1, x: 2, out: 1 }], room), null);
  assert.equal(planWindowVisit([{ id: 1, x: NaN, out: 1 }], room), null);
  for (let r = 0; r <= 1; r += 0.01) {
    const plan = planWindowVisit(edges, room, r, 1);
    assert.equal(plan.id, 2);
    assert.ok(plan.dx >= -room.left && plan.dx <= room.right);
    assert.ok(Math.abs(plan.dx - plan.x - plan.out * WINDOW_VISIT.distance) < 1e-12);
  }
  assert.equal(planWindowVisit([edges[0]], room, 0.5, 1).id, 1);
  for (const seated of [true, false]) for (const perched of [true, false]) {
    const picks = Array.from({ length: 1000 }, (_, i) => chooseIdle({ idleFor: 40, canVisit: true, seated, perched }, i / 1000, 0.3));
    assert.equal(picks.some(p => p.windowVisit), !seated && !perched);
  }
});

test('window contact settles before reaching and releases smoothly on interruption', () => {
  assert.equal(windowVisitMotion(-1), null);
  assert.equal(windowVisitMotion(WINDOW_VISIT.duration), null);
  assert.equal(windowVisitMotion(0.3).weight, 0);
  assert.equal(windowVisitMotion(2).weight, 1);
  assert.equal(windowVisitMotion(4.6).weight, 0);
  assert.equal(windowVisitMotion(2, 1, 0.55), null);
  assert.deepEqual(windowVisitMotion(2, 1, 0), windowVisitMotion(2, 1));
  let last = 1;
  for (let cut = 0; cut < 0.55; cut += 1 / 120) {
    const m = windowVisitMotion(2 + cut, 1, cut);
    assert.ok(m.weight <= last && m.weight >= 0);
    assert.ok(last - m.weight < 0.025);
    last = m.weight;
  }
  for (let t = 0; t < WINDOW_VISIT.duration; t += 1 / 120) {
    const left = windowVisitMotion(t, -1), right = windowVisitMotion(t, 1);
    assert.equal(left.side, 'left'); assert.equal(right.side, 'right');
    assert.equal(left.look[0], -right.look[0]);
    assert.ok(right.weight >= 0 && right.weight <= 1);
    for (const [name, angles] of Object.entries(right.bones)) {
      assert.ok(BONES.includes(name));
      assert.ok(angles.every(a => Number.isFinite(a) && Math.abs(a) < 0.1));
    }
  }
});


test('window reach puts either wrist on the edge without a frame jump', () => {
  for (const out of [-1, 1]) {
    const rig = buildFigure(THREE), ik = makeIK(THREE), rest = poseFor('idle').bones;
    let previous = null;
    for (let t = 0; t < WINDOW_VISIT.duration; t += 1 / 120) {
      const motion = windowVisitMotion(t, out);
      for (const name of BONES) {
        const base = rest[name].map((v, i) => v + (motion.bones[name]?.[i] || 0));
        rig.setBone(name, base);
      }
      rig.root.updateMatrixWorld(true);
      const pole = rig.node(motion.side + 'UpperArm').getWorldPosition(new THREE.Vector3());
      const target = new THREE.Vector3(-out * WINDOW_VISIT.distance + out * 0.012, pole.y - 0.07, pole.z + 0.035);
      pole.add(new THREE.Vector3(out * 0.08, -0.22, 0.12));
      ik.reach(rig, motion.side, target, pole, motion.weight);
      rig.root.updateMatrixWorld(true);
      const wrist = rig.wrist(motion.side);
      assert.ok(wrist.toArray().every(Number.isFinite));
      if (motion.weight === 1) assert.ok(wrist.distanceTo(target) < 0.005, 'wrist stays on its window target');
      if (previous) assert.ok(wrist.distanceTo(previous) < 0.01, 'reach and release remain continuous');
      previous = wrist.clone();
    }
  }
});


test('character moods follow known cues and never infer sentiment from speech', () => {
  assert.equal(characterMood('thinking', null), 'focused');
  assert.equal(characterMood('idle', 'curious'), 'curious');
  assert.equal(characterMood('idle', 'think'), 'uncertain');
  assert.equal(characterMood('idle', 'smile'), 'amused');
  assert.equal(characterMood('speaking', null), null);
  assert.equal(characterMood('listening', null), null);
  for (const mood of CHARACTER_MOODS) {
    assert.ok(Object.values(characterAccent(mood, 0).face).every(v => v === 0));
    assert.equal(characterAccent(mood, 4).face[mood], 1);
    assert.equal(characterAccent(mood, -1).face[mood], 0);
    for (const angles of Object.values(characterAccent(mood).bones)) assert.ok(angles.every(a => Math.abs(a) <= 0.07));
  }
  assert.deepEqual(characterAccent('unknown').bones, {});
});

test('expressive brows return to neutral and a smile yields to speech', () => {
  const rig = buildFigure(THREE);
  const brow = rig.root.getObjectByName('expression-brow-1');
  const mouth = rig.root.getObjectByName('expression-mouth');
  const smile = rig.root.getObjectByName('expression-smile');
  rig.update(1 / 30);
  const rest = brow.position.y;
  rig.setExpression('curious', 1); rig.update(1 / 30);
  assert.ok(brow.position.y > rest + 0.01);
  rig.setExpression('curious', 0); rig.setExpression('amused', 1); rig.update(1 / 30);
  assert.ok(smile.material.opacity > 0.9);
  rig.setVisemes({ aa: 1 }); rig.update(1 / 30);
  assert.equal(smile.material.opacity, 0);
  assert.ok(mouth.scale.y > 1);
  rig.setExpression('amused', 0); rig.setVisemes({}); rig.update(1 / 30);
  assert.equal(brow.position.y, rest);
  assert.equal(smile.material.opacity, 0);
});


test('imported avatars get restrained mood fallbacks without stale expressions', () => {
  const supported = ['happy', 'relaxed', 'sad', 'angry', 'Surprised'];
  const curious = vrmCharacterExpressions({ curious: 1 }, supported);
  assert.equal(curious.Surprised, 0.16);
  assert.equal(vrmCharacterExpressions({ uncertain: 1 }, supported).sad, 0.18);
  assert.equal(vrmCharacterExpressions({ focused: 1 }, supported).angry, 0.12);
  assert.equal(vrmCharacterExpressions({ amused: 1, happy: 0.8 }, supported).happy, 0.8);
  const neutral = vrmCharacterExpressions({}, supported);
  assert.ok(Object.values(neutral).every(v => v === 0));
  const custom = vrmCharacterExpressions({ curious: 0.7 }, [...supported, 'curious']);
  assert.equal(custom.curious, 0.7);
  assert.equal(custom.Surprised, 0, 'custom mood does not double up with its fallback');
  assert.deepEqual(vrmCharacterExpressions({ uncertain: 1 }, []), {});
});


test('the chin-pose arm eases in and out without slowing her attention', () => {
  for (const [state, previous] of [['thinking', 'idle'], ['speaking', 'thinking'], ['listening', 'thinking']]) {
    assert.equal(poseTransitionTime(state, previous, 'rightUpperArm'), 0.75);
    assert.equal(poseTransitionTime(state, previous, 'rightHand'), 0.75);
    assert.equal(poseTransitionTime(state, previous, 'head'), 0.3);
  }
  assert.equal(poseTransitionTime('speaking', 'listening', 'rightUpperArm'), 0.3);
});

test('listening: a nod comes at a pause after you said something, not on every word and not too often', () => {
  const run = (s, level, seconds) => { for (let t = 0; t < seconds; t += 1 / 30) s = listenStep(s, level, 1 / 30); return s; };
  let s = run(null, 0.05, 2);                                  // two seconds of talking
  s = run(s, 0.005, 0.2);                                      // a gap between words: nothing yet
  assert.equal(s.nod, null);
  s = run(s, 0.05, 0.5);
  s = run(s, 0.005, 0.5);                                      // a real pause
  assert.ok(s.nod != null && s.count === 1);
  // the nod itself: head first, the neck a moment after, and it's over within a second
  const at = x => listenNod({ ...s, nod: x });
  assert.ok(at(0.08).head[0] / 0.08 > at(0.08).neck[0] / 0.03, 'her head leads, the neck follows');
  assert.ok(at(0.18).head[0] > 0.07 && at(0.9).head[0] < 0.01);
  s = run(s, 0.005, 1);
  assert.deepEqual(listenNod(s), {}, 'over');
  // more talking and a pause soon after: no second nod yet
  s = run(run(s, 0.05, 1.5), 0.005, 0.6);
  assert.equal(s.count, 1);
  // a short word and a pause doesn't count
  s = run(run(s, 0.005, 8), 0.05, 0.5);
  s = run(s, 0.005, 0.6);
  assert.equal(s.count, 1);
  // noise between on and off doesn't start talking
  assert.equal(run(null, (LISTEN.on + LISTEN.off) / 2, 3).bout, 0);
  // the next one is a tilt
  s = run(run(s, 0.05, 2), 0.005, 0.6);
  assert.equal(s.count, 2);
  const tilt = listenNod({ ...s, nod: 0.4 });
  assert.ok(Math.abs(tilt.head[2]) > 0.05 && tilt.head[0] < 0.03);
});

test('between turns she remembers her last nod: no nod every turn, and dips and tilts keep taking turns', () => {
  const run = (s, level, seconds) => { for (let t = 0; t < seconds; t += 1 / 30) s = listenStep(s, level, 1 / 30); return s; };
  let s = run(run(null, 0.05, 2), 0.005, 0.5);
  assert.equal(s.count, 1);
  for (let t = 0; t < 2; t += 1 / 30) s = listenAway(s, 1 / 30);   // she answers briefly
  assert.ok(s.nod === null && s.bout === 0 && s.count === 1);
  s = run(run(s, 0.05, 2), 0.005, 0.5);                            // you go on: under 7 s since the last nod
  assert.equal(s.count, 1);
  for (let t = 0; t < 6; t += 1 / 30) s = listenAway(s, 1 / 30);
  s = run(run(s, 0.05, 2), 0.005, 0.5);
  assert.equal(s.count, 2, 'the next one, a tilt');
  assert.equal(listenAway(null, 1), null);
});

test('pointer reach lowers the elbow, comes forward, and points from the wrist toward the pointer', async () => {
  const { pointerReach, pointerDirection } = await import('./presence.mjs');
  for (const side of ['left', 'right']) {
    const r = pointerReach([0, 1, 0], side);
    assert.equal(r.forward, 0.2);
    assert.deepEqual(r.pole, [side === 'left' ? 0.12 : -0.12, 0.65, 0.12]);
  }
  assert.deepEqual(pointerDirection([1, 1, 1], [2, 1, 1]), [1, 0, 0]);
  assert.deepEqual(pointerDirection([1, 1, 1], [1, 1, 1]), [0, 0, 1]);
  const direction = pointerDirection([0, 0, 0], [1, 2, 3]);
  assert.ok(Math.abs(Math.hypot(...direction) - 1) < 1e-12);
  // A small articulated rig includes a fingertip, so this exercises the VRM hand-orientation path too.
  for (const side of ['left', 'right']) {
    const sign = side === 'left' ? 1 : -1, root = new THREE.Group();
    const upper = new THREE.Bone(), lower = new THREE.Bone(), hand = new THREE.Bone(), tip = new THREE.Bone();
    root.add(upper); upper.add(lower); lower.add(hand); hand.add(tip);
    lower.position.x = sign * 0.3; hand.position.x = sign * 0.25; tip.position.x = sign * 0.08;
    const rig = { root, node: name => ({ [side + 'UpperArm']: upper, [side + 'LowerArm']: lower, [side + 'Hand']: hand })[name],
      wrist: (_, out) => hand.getWorldPosition(out), fingerTip: (_, out) => tip.getWorldPosition(out) };
    const target = new THREE.Vector3(sign * 0.3, -0.15, 0.2), pole = new THREE.Vector3(sign * 0.12, -0.35, 0.12);
    const point = new THREE.Vector3().fromArray(pointerDirection(target.toArray(), [sign * 0.4, -0.1, 0.2]));
    const ik = makeIK(THREE);
    ik.reach(rig, side, target, pole, 1, point);
    const actual = tip.getWorldPosition(new THREE.Vector3()).sub(hand.getWorldPosition(new THREE.Vector3())).normalize();
    assert.ok(actual.dot(point) > 0.9999, 'fingers aim at the pointer instead of upright');
    const pointer = new THREE.Vector3(sign * 0.4, -0.1, 0.2);
    upper.quaternion.identity(); lower.quaternion.identity(); hand.quaternion.identity();
    const before = new THREE.Vector3().fromArray(pointerDirection(hand.getWorldPosition(new THREE.Vector3()).toArray(), pointer.toArray()));
    ik.reach(rig, side, target, pole, 1, before, null, pointer);
    const wrist = hand.getWorldPosition(new THREE.Vector3());
    const after = tip.getWorldPosition(new THREE.Vector3()).sub(wrist).normalize();
    assert.ok(after.dot(pointer.clone().sub(wrist).normalize()) > 0.9999, 'direction uses the reached wrist, not its old position');
    const bent = lower.quaternion.clone();
    upper.quaternion.identity(); lower.quaternion.identity(); hand.quaternion.identity();
    ik.reach(rig, side, target, pole, 1, point, { UpperArm: 0.3, LowerArm: 1, Hand: 1 });
    assert.ok(lower.quaternion.angleTo(bent) < 1e-7, 'IK release keeps the solved elbow bend while the upper arm lowers');
  }
});


test('sleeve target stays below the chest and fan stays forward on an articulated arm', () => {
  // Representative 30 cm upper arm / 25 cm forearm; spatial check complements the pose bounds.
  for (const side of [1, -1]) {
    const h = side === 1 ? 'left' : 'right', sign = side;
    const upper = new THREE.Bone(), lower = new THREE.Bone(), hand = new THREE.Bone();
    upper.add(lower); lower.add(hand);
    lower.position.x = sign * 0.3; hand.position.x = sign * 0.25;
    const apply = (bone, target, rest, weight) => {
      bone.quaternion.setFromEuler(new THREE.Euler(...rest));
      bone.quaternion.slerp(new THREE.Quaternion().setFromEuler(new THREE.Euler(...target)), weight);
    };
    for (let t = 0; t < GESTURES.brushSleeve; t += 1 / 60) {
      const g = gesture('brushSleeve', t, side);
      apply(upper, g.bones[h + 'UpperArm'], [0, 0, -sign * 1.4], g.weights[h + 'UpperArm']);
      apply(lower, g.bones[h + 'LowerArm'], [0, -sign * 0.15, 0], g.weights[h + 'LowerArm']);
      const elbow = lower.getWorldPosition(new THREE.Vector3());
      const wrist = hand.getWorldPosition(new THREE.Vector3());
      const target = elbow.lerp(wrist, g.ik.along); target.y += g.ik.above;
      assert.ok(target.y < -0.15, `below chest on entry, hold and exit at ${t}`);
    }
    const fan = gesture('fingerFan', 2, side);
    upper.rotation.set(...fan.bones[h + 'UpperArm']); lower.rotation.set(...fan.bones[h + 'LowerArm'].slice(0, 3));
    lower.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), fan.bones[h + 'LowerArm'][3] || 0));
    const wrist = hand.getWorldPosition(new THREE.Vector3());
    assert.ok(wrist.z > 0.35 && wrist.z < 0.42, 'hand stays forward on the representative arm');
    assert.ok(wrist.y > -0.21 && wrist.y < -0.17, 'chest height rather than under the chin');
    assert.ok(wrist.x * sign > 0.12, 'hand sits out from her centre');
    hand.rotation.set(...fan.bones[h + 'Hand']);
    const rotation = hand.getWorldQuaternion(new THREE.Quaternion());
    const palmNormal = new THREE.Vector3(0, 1, 0).applyQuaternion(rotation);
    const fingers = new THREE.Vector3(sign, 0, 0).applyQuaternion(rotation);
    assert.ok(Math.abs(palmNormal.z) > 0.5, 'fan plane faces the viewer instead of being edge-on');
    assert.ok(fingers.y > 0.85, 'fingers point up, clear of the sleeve');
  }
});


test('brace protects the upper chest without raising the hand over her mouth, on either side', () => {
  for (const side of [1, -1]) {
    const name = side === 1 ? 'right' : 'left', sign = -side;
    const upper = new THREE.Bone(), lower = new THREE.Bone(), hand = new THREE.Bone();
    upper.add(lower); lower.add(hand);
    lower.position.x = sign * 0.3; hand.position.x = sign * 0.25;
    const g = gesture('brace', 0.6, side);
    upper.rotation.set(...g.bones[name + 'UpperArm']); lower.rotation.set(...g.bones[name + 'LowerArm']);
    const wrist = hand.getWorldPosition(new THREE.Vector3());
    assert.ok(wrist.y < -0.05 && wrist.y > -0.1, 'wrist stays below shoulder height');
    assert.ok(Math.abs(wrist.x) < 0.03 && wrist.z > 0.3, 'forearm folds across the chest and stays forward');
  }
});
