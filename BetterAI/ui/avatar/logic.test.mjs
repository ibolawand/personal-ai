import { armEntry, armRelease, typingEyeStep, typingKeyCount } from './logic.mjs';
// The avatar's decisions that need no 3D: poses, blinking, the mouth, where the orbiting props sit.
import test from 'node:test';
import assert from 'node:assert/strict';
import { STATES, BONES, GESTURES, thoughtStep, detailFits, TAP, tapMotion, SETTLE, settles, settleBreath, CATCH, inReach, reachPoint, catchStep, PHRASE, phrasePlan, phraseGesture, TYPING, typingAttention, CUT_S, cutShort, mayStartle, STARTLE_EVERY, FIDGETS, WALK, avatarState, poseFor, idleMotion, gesture, walkCycle, stroll, strollLength,
  talkMotion, visemes, saccade, chooseIdle, IDLE, SEATED_FIDGETS, sitting, sitPose, LEG, spring, gazeWander, withinLimits, ease, nextBlink, blinkWeight, BLINK, weightShift, mouthWeight, ringPosition, fingerCurl,
  TRIP, planTrip, trip, tripLength, cutLeg, LEDGE_Y, perchPose, dangle, jump, jumpLength, planPerch, CORNER_CHANCE,
  PERCHED_FIDGETS, HANDS, crossFits, tiredness, TIRED, DOZE_EVERY, CARRY, carryInput, carrySwing, carryPose, setDown, LAND_S, PEEK, planHide, peekOut, headPastEdge, lookBlink, edgeSit, edgeSitLength, bobMotion, grooveStep, afterMusic, GROOVE, beatClock, beatsAt } from './logic.mjs';

test('the microphone decides between listening and idle', () => {
  assert.equal(avatarState('listening', true), 'listening');
  assert.equal(avatarState('listening', false), 'idle');
  assert.equal(avatarState('thinking', false), 'thinking');
  assert.equal(avatarState('speaking', true), 'speaking');
  for (const s of ['sleeping', 'booting', 'error', 'alert', 'whatever']) assert.equal(avatarState(s, true), 'idle');
});
test('every state has a pose for her whole body, within what a body can do', () => {
  for (const s of STATES) {
    const p = poseFor(s);
    assert.deepEqual(Object.keys(p.bones), BONES);
    for (const [name, angles] of Object.entries(p.bones)) {
      assert.equal(angles.length, 4);                  // x, y, z and a twist
      const limit = name.includes('LowerArm') ? 2.5 : name.includes('Arm') ? 1.6 : 0.6;    // (an elbow folds: thinking, her finger is on her chin)
      for (const a of angles) assert.ok(Math.abs(a) <= limit, `${s} ${name} ${a}`);
    }
    for (const w of Object.values(p.expressions)) assert.ok(w >= 0 && w <= 1);
  }
  assert.deepEqual(poseFor('nonsense'), poseFor('idle'));
});
test('standing idle her arms are down at her sides and everything else is straight', () => {
  const { bones, expressions } = poseFor('idle');
  assert.ok(bones.leftUpperArm[2] < -1 && bones.rightUpperArm[2] > 1);            // down from the T-pose, mirrored
  assert.ok(bones.leftLowerArm[1] < 0 && bones.rightLowerArm[1] > 0);              // elbows a little bent, mirrored
  for (const name of ['hips', 'spine', 'chest', 'neck', 'head', 'leftUpperLeg', 'rightLowerLeg']) {
    assert.deepEqual(bones[name], [0, 0, 0, 0]);
  }
  assert.deepEqual(expressions, {});
});
test('poses point the right way', () => {
  const { bones: listening } = poseFor('listening'), { bones: thinking } = poseFor('thinking');
  assert.ok(listening.spine[0] > 0 && listening.head[2] !== 0);                    // leans in, head tilted
  assert.ok(thinking.head[0] < 0 && thinking.head[1] !== 0);                       // looks up and aside
  assert.ok(thinking.hips[2] !== 0 && thinking.rightLowerArm[1] > 1);              // weight on one leg, elbow bent
  assert.ok(poseFor('speaking').expressions.relaxed > 0);
});
test('a pose handed out can be changed without changing the next one', () => {
  poseFor('thinking').bones.head[0] = 9;
  assert.ok(poseFor('thinking').bones.head[0] < 0);
});
test('idle she shifts her weight with her feet staying put, and never moves far', () => {
  for (let t = 0; t < 30; t += 0.37) {
    const m = idleMotion(t);
    assert.ok(Math.abs(m.hips[2] + m.leftUpperLeg[2]) < 1e-12 && Math.abs(m.hips[2] + m.rightUpperLeg[2]) < 1e-12);
    for (const [name, angles] of Object.entries(m)) {
      assert.ok(BONES.includes(name));
      for (const a of angles) assert.ok(Math.abs(a) <= (name.includes('LowerLeg') ? 0.17 : 0.1), `${name} ${a}`);
    }
  }
  assert.notDeepEqual(idleMotion(0.5), idleMotion(2));                              // she does move
  // follow-through: her hips change direction first, her chest and head a moment later
  const turns = part => { for (let t = 0.02; t < 7; t += 0.02) { const [a, b, c] = [t - 0.02, t, t + 0.02].map(x => part(idleMotion(x))); if (b > a && b > c) return t; } };
  const [hips, chest, head] = [m => m.hips[2], m => -m.chest[2], m => m.head[2]].map(turns);
  assert.ok(hips < chest && chest < head, `${hips} ${chest} ${head}`);
  const shoulders = idleMotion(1.75);
  assert.ok(shoulders.hips[2] * shoulders.leftShoulder[2] < 0);                     // shoulders tip against her hips
});
test('the wave bends the elbow, lifts and turns the arm, swings, and comes down with the elbow still bent', () => {
  assert.equal(gesture('wave', -0.1), null);
  assert.equal(gesture('wave', GESTURES.wave), null);
  assert.equal(gesture('nonsense', 0.1), null);
  assert.equal(gesture('wave', 0).weight, 0);                                       // starts from her pose
  const arm = t => gesture('wave', t).bones.rightUpperArm, elbow = t => gesture('wave', t).bones.rightLowerArm[1];
  assert.ok(arm(0.05)[2] > 1.3);                                                    // winds up: dips away before it rises
  const heights = Array.from({ length: 28 }, (_, i) => arm(i * 0.1)[2]);
  assert.ok(arm(0.2)[2] > 0.9);                                                     // an unhurried lift: still low after 0.2 s
  assert.ok(Math.min(...heights) < 0.48 && Math.min(...heights) > 0.35);           // goes a little past its place, not far
  // up beside her, turned, the elbow below her shoulder and swung forward (a friendly "hi", not arm-out: her hand
  // stays beside her face, inside her box)
  assert.ok(Math.abs(arm(1.1)[2] - 0.5) < 0.02 && Math.abs(arm(1.1)[3] + Math.PI / 2) < 0.01);
  assert.ok(arm(1.1)[1] > 0.5 && arm(1.1)[0] < -0.2);
  assert.ok(Math.max(...Array.from({ length: 28 }, (_, i) => elbow(i * 0.1))) <= 2.5, 'the elbow never folds past its limit');
  assert.ok(Math.abs(gesture('wave', 1.1).weight - 1) < 1e-9);
  const swings = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5].map(elbow);
  assert.ok(Math.min(...swings) > 0.9 && Math.max(...swings) - Math.min(...swings) > 0.4);       // bent, and swinging
  for (let t = 0.3; t < GESTURES.wave - 0.25; t += 0.05) {
    if (arm(t)[2] < 0.9) assert.ok(elbow(t) > 0.8, `arm out with a straight elbow at ${t}`);     // never straight out sideways
    // and while it is raised it stays turned: untwisted, a raised arm's bent forearm points at the viewer
    if (t > 2 && arm(t)[2] < 0.6) assert.ok(arm(t)[3] < -1.2, `raised arm untwisted at ${t}`);
  }
  const end = gesture('wave', GESTURES.wave - 0.001);
  assert.ok(end.weight < 0.01 && Math.abs(end.bones.rightUpperArm[2] - 1.3) < 0.01 && end.lift === 0);   // back at her side
});
test('the hop bends her knees, leaves the ground, sinks on landing and settles', () => {
  assert.equal(gesture('hop', 0).lift, 0);
  assert.ok(gesture('hop', 0.12).bones.leftLowerLeg[0] > 0.5 && gesture('hop', 0.12).lift < 0);    // crouched: her body sinks
  const lifts = Array.from({ length: 75 }, (_, i) => gesture('hop', i * 0.01).lift);
  assert.ok(Math.max(...lifts) > 0.1 && Math.min(...lifts) > -0.04);   // never sinks further than her knees let her
  assert.ok(Math.abs(gesture('hop', 0.45).lift) < 0.005);                          // touching down
  assert.ok(gesture('hop', 0.5).bones.leftLowerLeg[0] > 0.3);                       // knees give on landing
  assert.ok(gesture('hop', 0.3).bones.leftLowerLeg[0] < 0.05);                      // legs straight in the air
  assert.ok(gesture('hop', 0.16).bones.spine[0] > gesture('hop', 0.16).bones.chest[0]);   // her chest follows her spine late
  assert.ok(gesture('hop', GESTURES.hop - 0.001).weight < 0.05);
  assert.equal(gesture('hop', GESTURES.hop), null);
});
test('ease arrives in about its time and never overshoots', () => {
  let v = 0; for (let i = 0; i < 18; i++) v = ease(v, 1, 1 / 60);      // 0.3 s
  assert.ok(v > 0.95 && v <= 1);
  assert.equal(ease(1, 1, 0.016), 1);
});
test('blinks come every 2 to 6 seconds, now and then two in a row, and shut faster than they open', () => {
  assert.equal(nextBlink(10, 0), 12); assert.ok(Math.abs(nextBlink(10, 0.88) - 16) < 1e-9);
  assert.ok(nextBlink(10, 0.95) < 10.2);                                           // a double blink
  assert.equal(blinkWeight(4.9, 5), 0); assert.equal(blinkWeight(5 + BLINK.close, 5), 1);
  assert.ok(blinkWeight(5.03, 5) > 0 && blinkWeight(5.03, 5) < 1); assert.equal(blinkWeight(5 + BLINK.length, 5), 0);
  assert.ok(BLINK.close < BLINK.open && Math.abs(BLINK.close + BLINK.open - BLINK.length) < 1e-9);
  assert.ok(blinkWeight(5 + BLINK.close / 2, 5) >= 0.5);                           // half shut halfway through closing
  for (let x = 0.001, last = 0; x < BLINK.close; x += 0.005) { const w = blinkWeight(5 + x, 5); assert.ok(w >= last); last = w; }
});
test('she stands on one leg at a time: holds it, shifts with a little overshoot, and the other knee is loose', () => {
  let held = 0, most = 0, sides = new Set();
  for (let t = 0; t < 300; t += 0.05) {
    const w = weightShift(t);
    assert.ok(Math.abs(w) <= 1.1, `${w}`);
    assert.ok(Math.abs(weightShift(t + 0.05) - w) < 0.25);                         // no jumps
    if (Math.abs(weightShift(t + 0.05) - w) < 1e-9) held++;
    most = Math.max(most, Math.abs(w));
    if (Math.abs(w) > 0.5) sides.add(Math.sign(w));
  }
  assert.ok(held > 0.6 * 6000, `${held}`);                                         // mostly she just stands there
  assert.ok(most > 1 && sides.size === 2);                                         // past the mark, and onto both legs
  for (let t = 0; t < 120; t += 0.3) {
    const m = idleMotion(t), w = weightShift(t - 0.15);
    assert.ok(m.leftLowerLeg[0] > 0.03 && m.rightLowerLeg[0] > 0.03);              // knees never locked
    if (w > 0.5) assert.ok(m.rightLowerLeg[0] > m.leftLowerLeg[0] + 0.03);
    if (w < -0.5) assert.ok(m.leftLowerLeg[0] > m.rightLowerLeg[0] + 0.03);
  }
  // her arms don't swing as a pair: each has a rhythm of its own
  const pairs = Array.from({ length: 200 }, (_, i) => idleMotion(i * 0.31)).map(m => m.leftUpperArm[0] - m.rightUpperArm[0] * -1);
  assert.ok(Math.max(...pairs.map(Math.abs)) > 0.01);
});
test('the new moves: a yawn, a look at her wrist, shaking out her hands, a stretch to the side', () => {
  for (const name of ['yawn', 'checkWrist', 'shakeOut', 'sideStretch']) assert.ok(FIDGETS.includes(name) && IDLE[name].weight > 0, name);
  const yawn = gesture('yawn', 1.6);
  assert.ok(yawn.mouth > 0.7 && yawn.eyes > 0.9 && yawn.bones.head[0] < -0.05);     // mouth wide, eyes shut, head back
  assert.ok(gesture('yawn', 0.3).mouth === 0 && gesture('yawn', 3.2).mouth === 0); // not before her hand is up, nor after
  assert.ok(gesture('yawn', 1.6, -1).bones.leftLowerArm[1] < -2);                  // either hand
  const wrist = gesture('checkWrist', 1.4);
  assert.ok(wrist.look[1] < -0.5 && wrist.bones.head[0] > 0.2);                    // she looks down at it
  assert.ok(gesture('checkWrist', 2.6).look[1] > -0.1);                            // and up again
  const early = Math.abs(gesture('shakeOut', 1.0).bones.leftHand[0] - gesture('shakeOut', 1.1).bones.leftHand[0]);
  const late = Math.abs(gesture('shakeOut', 2.2).bones.leftHand[0] - gesture('shakeOut', 2.3).bones.leftHand[0]);
  assert.ok(early > 2 * late);                                                     // the shake dies away
  const a = gesture('sideStretch', 1.9, 1).bones, b = gesture('sideStretch', 1.9, -1).bones;
  assert.ok(a.rightUpperArm[0] < -2.4 && b.leftUpperArm[0] < -2.4);                // either arm overhead
  assert.ok(a.spine[2] * b.spine[2] < 0 && a.hips[2] * a.spine[2] < 0);            // leaning away, hip out against it
  assert.ok(Math.abs(a.hips[2] + a.leftUpperLeg[2]) < 1e-12);                      // feet stay put
  // the quiet fidgets wind up a touch the other way, go a little too far, and settle
  const w = t => gesture('lean', t).weight;
  assert.ok(w(0.05) < 0 && w(0.05) > -0.08);
  assert.ok(Math.max(...Array.from({ length: 30 }, (_, i) => w(i * 0.05))) > 1.03);
  assert.ok(Math.abs(w(1.8) - 1) < 1e-9);
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

test('walking, her legs swing against each other and her arms against her legs', () => {
  for (let phase = 0; phase < 2 * Math.PI; phase += 0.3) {
    const { bones, lift } = walkCycle(phase);
    assert.ok(Math.abs(bones.leftUpperLeg[0] + bones.rightUpperLeg[0]) < 1e-12);
    assert.ok(bones.leftUpperLeg[0] * bones.leftUpperArm[0] <= 0);                 // left leg forward, left arm back
    assert.ok(bones.leftLowerLeg[0] >= 0 && bones.rightLowerLeg[0] >= 0);          // knees only bend one way
    assert.ok(bones.leftLowerArm[1] <= 0 && bones.rightLowerArm[1] >= 0);          // so do elbows
    assert.ok(lift >= 0 && lift < 0.02);
    for (const name of Object.keys(bones)) assert.ok(BONES.includes(name), name);
  }
  const half = walkCycle(Math.PI / 2).bones, other = walkCycle(3 * Math.PI / 2).bones;
  assert.ok(half.leftUpperLeg[0] < -0.15 && other.leftUpperLeg[0] > 0.15);          // a real stride, both ways
  // her feet don't skate: a step carries a foot as far as her body moves in that step (within 15%)
  const footTravel = 2 * WALK.leg * Math.sin(Math.abs(half.leftUpperLeg[0]));
  const perStep = WALK.speed / WALK.stepsPerS;
  assert.ok(Math.abs(footTravel / perStep - 1) < 0.15, `foot ${footTravel.toFixed(3)} vs body ${perStep.toFixed(3)}`);
});
test('a stroll goes out to one side, comes back and ends where it began, facing front', () => {
  const reach = 0.2, total = strollLength(reach);
  assert.ok(total > 2 && total < 5);
  assert.equal(stroll(-0.1, reach), null);
  assert.equal(stroll(total, reach), null);
  assert.deepEqual([stroll(0, reach).x, stroll(0, reach).yaw, stroll(0, reach).amount], [0, 0, 0]);
  let far = 0, before = stroll(0, reach), facedOut = false, facedBack = false;
  for (let t = 0.01; t < total; t += 0.01) {
    const now = stroll(t, reach);
    assert.ok(now.x >= -1e-9 && now.x <= reach + 1e-9);                             // never outside her room
    assert.ok(Math.abs(now.x - before.x) < 0.01 && Math.abs(now.yaw - before.yaw) < 0.2);   // no jumps
    assert.ok(now.amount >= 0 && now.amount <= 1);
    if (now.amount > 0.9) {                                                         // striding: she faces the way she goes
      if (now.x > before.x) { assert.ok(now.yaw > 1); facedOut = true; }
      if (now.x < before.x) { assert.ok(now.yaw < -1); facedBack = true; }
    }
    far = Math.max(far, now.x);
    before = now;
  }
  assert.ok(Math.abs(far - reach) < 0.01 && facedOut && facedBack);
  const end = stroll(total - 0.001, reach);
  assert.ok(Math.abs(end.x) < 1e-6 && Math.abs(end.yaw) < 0.01 && end.amount === 0);
});
test('a stroll eases into and out of each leg, and her steps follow how far she has gone', () => {
  const reach = 0.25, total = strollLength(reach);
  const speeds = [], ratios = [];
  for (let t = 0.01; t < total; t += 0.01) {
    const [a, b] = [stroll(t - 0.01, reach), stroll(t, reach)];
    if (!a || !b) continue;
    const dx = Math.abs(b.x - a.x), dp = b.phase - a.phase;
    speeds.push(dx / 0.01);
    if (dx > 1e-4) ratios.push(dp / dx);
    if (b.amount < 0.05) assert.ok(dx / 0.01 < 0.08, `sliding at ${t.toFixed(2)} while not striding`);
  }
  const accel = speeds.slice(1).map((v, i) => Math.abs(v - speeds[i]) / 0.01);
  assert.ok(Math.max(...accel) < 4, `jerky: ${Math.max(...accel).toFixed(2)}`);       // speeds up and slows down smoothly
  const want = Math.PI * WALK.stepsPerS / WALK.speed;                                 // phase per unit she moves
  for (const r of ratios) assert.ok(Math.abs(r / want - 1) < 0.02, `${r} vs ${want}`);
});
test('a stroll to the other side is its mirror, and with no room she stays put', () => {
  const [right, left] = [stroll(1.2, 0.2, 1), stroll(1.2, 0.2, -1)];
  assert.ok(right.x > 0 && Math.abs(left.x + right.x) < 1e-12 && Math.abs(left.yaw + right.yaw) < 1e-12);
  assert.equal(strollLength(0), 0);
  assert.equal(stroll(0.5, 0), null);
  assert.equal(stroll(0.5, 0.01), null);
});
test('her hands move with her voice and are still in silence', () => {
  for (const [name, angles] of Object.entries(talkMotion(3.3, 0))) for (const a of angles) assert.equal(Math.abs(a), 0, name);
  const loud = [0, 0.3, 0.6, 0.9, 1.2].map(t => talkMotion(t, 1));
  const forearm = loud.map(m => m.rightLowerArm[1]);
  assert.ok(Math.max(...forearm) - Math.min(...forearm) > 0.1);                     // they move
  for (const m of loud) {
    assert.ok(m.leftLowerArm[1] <= 0 && m.rightLowerArm[1] >= 0);                   // elbows bend their own way
    for (const [name, angles] of Object.entries(m)) { assert.ok(BONES.includes(name)); for (const a of angles) assert.ok(Math.abs(a) <= 0.35); }
  }
  assert.deepEqual(talkMotion(1, 9), talkMotion(1, 1));                             // a level above 1 counts as 1
});
test('talking, her hands stay down by her sides: small beats, no pumping back and forth in front of her', () => {
  const pose = poseFor('speaking').bones;
  assert.ok(Math.abs(pose.rightLowerArm[1]) <= 0.45 && Math.abs(pose.leftLowerArm[1]) <= 0.45);   // elbows only loosely bent
  assert.ok(Math.abs(pose.rightUpperArm[0]) <= 0.05);                                // upper arms not brought forward
  const range = (bone, i) => {
    const v = Array.from({ length: 200 }, (_, k) => talkMotion(k * 0.05, 1)[bone][i]);
    return Math.max(...v) - Math.min(...v);
  };
  assert.ok(range('rightLowerArm', 1) < 0.2 && range('leftLowerArm', 1) < 0.2);     // forearms barely swing
  assert.ok(range('rightUpperArm', 0) < 0.08 && range('rightHand', 0) < 0.15);      // nor do shoulders or wrists
});
test('every fidget eases in from her pose and out again, within what a body can do', () => {
  for (const name of FIDGETS) {
    const length = GESTURES[name];
    // the umbrella rests on her shoulder a while, and crossed ankles are a rest of their own
    assert.ok(length >= 2 && length <= (name === 'umbrella' ? 16 : name === 'crossAnkles' ? 7.5 : name === 'ankleEase' ? 5.2 : 5), name);
    assert.ok(gesture(name, 0).weight === 0 && gesture(name, length - 0.001).weight < 0.01, name);
    assert.ok(gesture(name, length / 2).weight > 0.9 && gesture(name, length / 2).weight < 1.15, name);
    assert.equal(gesture(name, length), null);
    for (let t = 0; t < length; t += 0.1) {
      const g = gesture(name, t);
      assert.ok(g.lift >= 0 && g.lift < 0.03);
      for (const [bone, angles] of Object.entries(g.bones)) {
        assert.ok(BONES.includes(bone), `${name} ${bone}`);
        const most = /tretch/.test(name) && bone.includes('UpperArm') ? 3 : bone.includes('LowerArm') ? 2.5
          : bone.includes('Arm') ? 2 : bone.includes('Hand') ? 0.8 : 0.6;        // (a wrist bends further than a spine)
        for (const a of angles) assert.ok(Math.abs(a) <= most, `${name} ${bone} ${a}`);
      }
    }
  }
  // the stretch raises her arms up in front of her (never out to the sides, where they pass through a T-pose)
  const up = gesture('stretch', 1.4).bones;
  assert.ok(up.leftUpperArm[0] < -2.4 && up.rightUpperArm[0] < -2.4);              // swung forward and up overhead
  assert.ok(up.leftUpperArm[2] < -1 && up.rightUpperArm[2] > 1);                   // from hanging, not from out sideways
  const looks = [0.8, 2.4].map(t => gesture('lookAround', t).bones.head[1]);
  assert.ok(looks[0] > 0.3 && looks[1] < -0.3);                                     // one side, then the other
});
test('idle she picks from many things, never the same as just before, and only what fits', () => {
  const pick = (ctx, n = 400) => Array.from({ length: n }, (_, i) => chooseIdle(ctx, (i + 0.5) / n, ((i * 7919) % n) / n));
  const name = act => act.stroll ? 'stroll' : act.sit ? 'sit' : act.stand ? 'standUp' : act.gesture;
  const standing = new Set(pick({ recent: [], idleFor: 10 }).map(name));
  assert.ok(standing.size >= 10, [...standing].join(' '));                          // plenty of variety
  assert.ok(!standing.has('sit') && !standing.has('standUp'));                      // not sitting after only 10 s
  for (const n of standing) assert.ok(n === 'stroll' || FIDGETS.includes(n), n);
  assert.ok(new Set(pick({ recent: [], idleFor: 90 }).map(name)).has('sit'));       // bored: she may sit down
  const after = pick({ recent: ['lean', 'stroll'], idleFor: 10 }).map(name);
  assert.ok(!after.includes('lean') && !after.includes('stroll'));                  // never repeats what she just did
  const seated = new Set(pick({ recent: [], idleFor: 90, seated: true, seatedFor: 5 }).map(name));
  for (const n of seated) assert.ok(SEATED_FIDGETS.includes(n), n);                 // seated: only what fits sitting
  assert.ok(!seated.has('standUp') && seated.size >= 4);                            // and stays down a while
  assert.ok(new Set(pick({ recent: [], idleFor: 200, seated: true, seatedFor: 60 }).map(name)).has('standUp'));
  for (const act of pick({ recent: [], idleFor: 10 })) {
    if (act.stroll) assert.ok((act.stroll === 1 || act.stroll === -1) && typeof act.peek === 'boolean');
    if (act.gesture) assert.ok(act.side === 1 || act.side === -1);
  }
  for (const [n, spec] of Object.entries(IDLE)) assert.ok(spec.weight >= 0, n);
});
test('new fidgets: faces and gazes come with them', () => {
  for (const name of ['shoulderRoll', 'tugJacket', 'think', 'smile', 'sigh', 'curious']) {
    assert.ok(FIDGETS.includes(name), name);
  }
  assert.ok(gesture('smile', GESTURES.smile / 2).face.happy > 0.3);                 // a small smile
  const think = gesture('think', GESTURES.think - 0.6);
  assert.ok(think.face.happy > 0.2);                                               // "got it": ends with a smile
  assert.ok(gesture('think', 1.5).bones.rightLowerArm[1] > 1.8);                    // hand up at her chin
  assert.ok(gesture('sigh', GESTURES.sigh * 0.7).face.relaxed > 0.3);
  const left = gesture('curious', 1.5, -1).look, right = gesture('curious', 1.5, 1).look;
  assert.ok(left[0] < -0.5 && right[0] > 0.5);                                      // looks toward a corner, either side
});
test('sitting down, her feet stay where they are: hips drop and move back exactly as her legs fold', () => {
  const ankle = w => {                                                              // ankle height and depth for a fold w
    const p = sitPose(w).bones, thigh = p.leftUpperLeg[0], knee = thigh + p.leftLowerLeg[0];
    const { lift, back } = sitting(w === 0 ? 0 : 99, null, w);
    return [LEG.hip + lift - LEG.thigh * Math.cos(thigh) - LEG.shin * Math.cos(knee),
            back - LEG.thigh * Math.sin(thigh) - LEG.shin * Math.sin(knee)];
  };
  const [y0, z0] = ankle(0);
  for (const w of [0.25, 0.5, 0.75, 1]) {
    const [y, z] = ankle(w);
    assert.ok(Math.abs(y - y0) < 0.005 && Math.abs(z - z0) < 0.005, `${w}: ${y} ${z}`);
  }
  assert.ok(sitting(99, null, 1).lift < -0.25);                                     // really down on the floor
});
test('sitting goes down smoothly, stays down, and stands up leaning forward over her feet', () => {
  assert.equal(sitting(0, null).w, 0);
  let before = 0;
  for (let t = 0.05; t < 2.5; t += 0.05) {
    const w = sitting(t, null).w;
    assert.ok(w >= before - 1e-9 && w - before < 0.15, `${t}`);                     // steady, no jumps
    before = w;
  }
  assert.ok(Math.abs(sitting(30, null).w - 1) < 1e-9);
  const rising = Array.from({ length: 40 }, (_, i) => sitting(30 + i * 0.05, 30)).filter(Boolean);
  assert.ok(Math.max(...rising.map(s => s.lean)) > 0.2);                            // weight forward to get up
  assert.equal(sitting(40, 30), null);                                              // stood up: over
});
test('a stroll can pause at the edge, look out and glance back before turning round', () => {
  const reach = 0.25, plain = strollLength(reach), peeking = strollLength(reach, true);
  assert.ok(peeking > plain + 1);
  const seen = { peek: 0, glance: 0 };
  let before = stroll(0, reach, 1, true);
  for (let t = 0.02; t < peeking; t += 0.02) {
    const now = stroll(t, reach, 1, true);
    seen.peek = Math.max(seen.peek, now.peek); seen.glance = Math.max(seen.glance, now.glance);
    if (now.peek > 0.1) assert.ok(Math.abs(now.x - reach) < 1e-6 && now.amount === 0);   // standing at the edge
    assert.ok(Math.abs(now.yaw - before.yaw) < 0.1);
    before = now;
  }
  assert.ok(seen.peek > 0.95 && seen.glance > 0.9);
  assert.ok(stroll(0.5, reach, 1, false).peek === 0);
});
test('walking she knows how fast she goes and where she will face next', () => {
  const reach = 0.25, middle = 0.45 + (reach / WALK.speed + 0.4) / 2;          // the middle of the walk out
  const mid = stroll(middle, reach, 1);
  assert.ok(Math.abs(mid.speed - 1) < 0.05 && Math.abs(mid.accel) < 0.1);          // cruising
  const total = strollLength(reach);
  let braking = false;
  for (let t = 0.5; t < total; t += 0.02) if (stroll(t, reach, 1).accel < -1) braking = true;
  assert.ok(braking);                                                               // slows down before stopping
  assert.ok(stroll(0.1, reach, 1).ahead > 0.5);                                     // turning: her head leads the way
  assert.ok(Math.abs(stroll(1.2, reach, 1).ahead) < 0.01);
});
test('a spring follows its target, overshoots a little when loose and settles', () => {
  let [x, v] = [0, 0], most = 0;
  for (let i = 0; i < 120; i++) { [x, v] = spring(x, v, 1, 1 / 30, 2, 0.4); most = Math.max(most, x); }
  assert.ok(most > 1.05 && most < 1.4 && Math.abs(x - 1) < 0.01);
  [x, v] = [0, 0]; most = 0;
  for (let i = 0; i < 120; i++) { [x, v] = spring(x, v, 1, 1 / 30, 2, 1); most = Math.max(most, x); }
  assert.ok(most <= 1 + 1e-6 && Math.abs(x - 1) < 0.01);                            // critically damped: no overshoot
  assert.deepEqual(spring(0.3, 0, 0.3, 0.1, 2, 0.5), [0.3, 0]);
});
test('left alone, her gaze wanders to corners and drifts, holding each place a while', () => {
  const places = new Set();
  let held = 0;
  for (let t = 0; t < 60; t += 0.1) {
    const [x, y] = gazeWander(t), [nx, ny] = gazeWander(t + 0.1);
    assert.ok(Math.abs(x) <= 1 && Math.abs(y) <= 1);
    if (x === nx && y === ny) held++;
    places.add(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  assert.ok(places.size >= 8 && held > 500);                                        // many places, each held
  const corners = [...places].map(p => p.split(',').map(Number)).filter(([x, y]) => Math.abs(x) > 0.6 && Math.abs(y) > 0.4);
  assert.ok(corners.length >= 2);
});

test('her mouth takes turns through the vowel shapes and is shut in silence', () => {
  assert.deepEqual(visemes(1.3, 0), { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
  const leaders = new Set();
  for (let t = 0; t < 4; t += 0.05) {
    const v = visemes(t, 0.8);
    assert.deepEqual(Object.keys(v), ['aa', 'ih', 'ou', 'ee', 'oh']);
    for (const w of Object.values(v)) assert.ok(w >= 0 && w <= 0.8 + 1e-9);
    assert.ok(Math.abs(Math.max(...Object.values(v)) - 0.8) < 1e-9);                // one shape leads, as open as her mouth is
    leaders.add(Object.entries(v).sort((a, b) => b[1] - a[1])[0][0]);
  }
  assert.ok(leaders.size >= 4, [...leaders].join(' '));
  assert.deepEqual(visemes(1, 5), visemes(1, 1));
});
test('her eyes make small jumps that hold for a moment', () => {
  const seen = new Set();
  let held = 0;
  for (let t = 0; t < 12; t += 0.05) {
    const [x, y] = saccade(t), [nx, ny] = saccade(t + 0.05);
    assert.ok(Math.abs(x) <= 0.06 && Math.abs(y) <= 0.04);
    if (x === nx && y === ny) held++;
    seen.add(`${x},${y}`);
  }
  assert.ok(seen.size >= 8 && held > 150);                                          // many different spots, mostly at rest
});

test('tucking her hair: her head leads, she glances down, the elbow drops first, and her hand ends relaxed', () => {
  const L = GESTURES.tuckHair, at = t => gesture('tuckHair', t, 1);
  // anticipation: her head is already tipping toward the hand while the arm's own weight has barely begun
  assert.ok(at(0.25).weights.head > 0.9 && at(0.25).weight < 0.2, 'head before arm');
  for (let t = 0; t < L; t += 0.05) {
    const g = at(t);
    for (const w of Object.values(g.weights)) assert.ok(w >= 0 && w <= 1, `lead weight at ${t}`);
  }
  assert.ok(at(0.5).look[1] < 0, 'a glance down while her hand comes up');
  assert.ok(at(1.0).bones.head[2] > 0.08 && at(1.4).bones.head[2] > at(0.6).bones.head[2], 'her head yields further into the sweep');
  // the sweep takes her fingertips from her temple to behind her ear: more twist and the wrist bent back
  assert.ok(at(1.5).bones.rightUpperArm[3] < at(0.85).bones.rightUpperArm[3] && at(1.5).bones.rightHand[0] > at(0.85).bones.rightHand[0]);
  // on the way down the elbow goes down by her side (upper arm lowered) while the gesture still holds the arm
  assert.ok(at(2.2).bones.rightUpperArm[2] > 0.7 && at(2.2).weight > 0.4, 'elbow first');
  assert.ok(at(2.2).weights.rightLowerArm > at(2.7).weights.rightLowerArm, 'the forearm unfolds after it');
  // fingers relax last, and are fully back to relaxed at the end
  const end = at(L - 0.01).hands.right;
  assert.deepEqual(end.curl.map(c => +c.toFixed(3)), HANDS.relaxed.curl);
  assert.ok(at(L - 0.01).weights.head < 0.01);
  // the other side mirrors it: left arm, head tipped the other way, eyes to the other side
  const m = gesture('tuckHair', 1.0, -1);
  assert.ok(m.bones.leftUpperArm && !m.bones.rightUpperArm && m.bones.head[2] < 0 && Math.sign(m.look[0]) === -Math.sign(at(1.0).look[0]));
  assert.ok(m.hands.left && !m.hands.right);
  // she does it sitting on a window too (her arm only), but not on the floor hugging her knees
  assert.ok(PERCHED_FIDGETS.includes('tuckHair') && !SEATED_FIDGETS.includes('tuckHair'));
});

test('carried: her speed and push are read smoothly from where her window is, and a still drag reads as still', () => {
  let s = carryInput(null, 0, 0, 0);
  assert.deepEqual([s.vx, s.ax], [0, 0]);
  for (let i = 1; i <= 30; i++) s = carryInput(s, i * 0.02, 0, i / 60);       // 1.2 units a second to the right
  assert.ok(Math.abs(s.vx - 1.2) < 0.05 && Math.abs(s.ax) < 0.5, `steady speed ${s.vx}, no push ${s.ax}`);
  for (let i = 31; i <= 90; i++) s = carryInput(s, 0.6, 0, i / 60);           // held still
  assert.ok(Math.abs(s.vx) < 0.01 && Math.abs(s.ax) < 0.05);
  // a wild reading (a jump across the screen in one frame) is capped, not a jolt to the moon
  const j = carryInput({ x: 0, y: 0, t: 0, vx: 0, vy: 0, ax: 0, ay: 0 }, 50, 0, 1 / 60);
  assert.ok(j.vx <= CARRY.fast);
  assert.deepEqual(carryInput(s, 1, 1, s.t), carryInput(null, 1, 1, s.t), 'no time passed: starts again, never divides by 0');
});

test('carried: her feet trail a push, she swings through when it turns, and settles once you stop', () => {
  let w = { a: 0, v: 0 }, most = 0;
  // where a hanging foot ends up sideways (x: the viewer's right) when its leg is turned by `a` about z, the way
  // three.js turns a bone: a leg pointing down, (0, -1), turned by a goes to (sin a, -cos a)
  const footX = a => Math.sin(carryPose(1, a).leftUpperLeg[2]);
  for (let i = 0; i < 20; i++) w = carrySwing(w, 30, 1 / 60);                 // pushed to the viewer's right
  assert.ok(footX(w.a) < -0.1, 'her feet swing to the viewer\'s left, trailing the push');
  for (let i = 0; i < 20; i++) { w = carrySwing(w, -30, 1 / 60); most = Math.max(most, footX(w.a)); }
  assert.ok(most > 0.1, 'and through to the other side when the push turns');
  let crossings = 0, last = w.a;
  // (a swing counts when it goes visibly past the middle: more than about half a degree)
  for (let i = 0; i < 240; i++) { w = carrySwing(w, 0, 1 / 60); if (Math.abs(w.a) > 0.01 && Math.sign(w.a) !== Math.sign(last)) crossings++; if (Math.abs(w.a) > 0.01) last = w.a; }
  assert.ok(crossings >= 1 && crossings <= 2, `swings past once or twice and settles (${crossings})`);
  assert.ok(Math.abs(w.a) < 0.02, 'settled after 4 s');
  for (let i = 0; i < 600; i++) w = carrySwing(w, 1e6, 1 / 60);
  assert.ok(Math.abs(w.a) <= 1.5 * CARRY.max, 'a hard throw never flips her over');
  // the same at 30 fps as at 120 fps: frame-rate independent
  let a = { a: 0, v: 0 }, b = { a: 0, v: 0 };
  for (let i = 0; i < 30; i++) a = carrySwing(a, 20, 1 / 30);
  for (let i = 0; i < 120; i++) b = carrySwing(b, 20, 1 / 120);
  assert.ok(Math.abs(a.a - b.a) < 0.01);
});

test('carried: legs hang loose and trail, the upper body leans against them, arms out for balance; put down, knees give', () => {
  const p = carryPose(1, 0.2);
  assert.ok(p.leftLowerLeg[0] > 0.1 && p.leftFoot[0] > 0.3, 'knees loose, toes down');
  assert.ok(p.leftUpperLeg[2] > 0 && p.spine[2] < 0 && Math.abs(p.head[2]) < Math.abs(p.spine[2]), 'legs swing, back leans against them, head nearly level');
  assert.ok(p.leftUpperArm[2] > 0 && p.rightUpperArm[2] < 0, 'arms lifted out a little');
  for (const v of Object.values(carryPose(0, 0)).flat()) assert.equal(Math.abs(v), 0, 'not held: nothing');
  for (const [bone, v] of Object.entries(carryPose(1, 1.5 * CARRY.max))) {
    const four = [0, 1, 2, 3].map(i => v[i] || 0);
    assert.deepEqual(withinLimits(bone, four), four, `${bone} within what a joint can do`);
  }
  assert.equal(setDown(-0.1), 0);
  assert.ok(setDown(0.12) > 0.3, 'knees give quickly');
  let prev = 0;
  for (let t = 0; t < LAND_S + 0.05; t += 1 / 120) {
    const c = setDown(t);
    assert.ok(c >= 0 && c <= 0.36 && Math.abs(c - prev) < 0.04, `smooth at ${t.toFixed(3)}`);
    prev = c;
  }
  assert.equal(setDown(LAND_S), 0);
});

test('tired late at night: none by day, most from 1 to 5, gone by 8, and smooth round the clock', () => {
  for (const h of [9, 12, 15, 18, 21.9, 8.0]) assert.ok(tiredness(h) < 0.01, `awake at ${h}`);
  for (const h of [1, 2.5, 4.9]) assert.ok(tiredness(h) > 0.99, `tired at ${h}`);
  assert.ok(tiredness(23) > 0.1 && tiredness(23) < 0.9 && tiredness(6.5) > 0.1 && tiredness(6.5) < 0.9, 'on the way');
  assert.equal(tiredness(24 + 2), tiredness(2));
  for (let h = 0; h < 24; h += 1 / 60) assert.ok(Math.abs(tiredness(h + 1 / 60) - tiredness(h)) < 0.02, `no jump at ${h}`);
  // tired blinks are slower: the same blink lasts longer and is still shut where a rested one is already open
  assert.ok(blinkWeight(0.15, 0, 1 + TIRED.blinkSlow) > blinkWeight(0.15, 0, 1));
  assert.equal(blinkWeight(BLINK.length * 1.5, 0, 1.8) > 0, true);
  assert.equal(blinkWeight(0.1, 0), blinkWeight(0.1, 0, 1), 'rested blinks unchanged');
});

test('tired, she yawns more and now and then nods off: never by day, never twice in ten minutes', () => {
  const pick = (opts, n = 400) => {
    const c = {};
    for (let i = 0; i < n; i++) { const a = chooseIdle(opts, (i + 0.5) / n, 0.3); const k = a.gesture || Object.keys(a)[0]; c[k] = (c[k] || 0) + 1; }
    return c;
  };
  const day = pick({ idleFor: 60 }), night = pick({ idleFor: 60, tired: 1 });
  assert.ok(!day.doze && night.doze > 0, 'dozes only when tired');
  assert.ok((night.yawn || 0) > 2 * (day.yawn || 0), `more yawns (${night.yawn} vs ${day.yawn})`);
  assert.ok(!pick({ idleFor: 60, tired: 1, sinceDoze: DOZE_EVERY - 1 }).doze, 'not again so soon');
  assert.ok(!pick({ idleFor: 10, tired: 1 }).doze, 'only after a while with nothing going on');
  assert.ok(pick({ idleFor: 60, tired: 1, perched: true, perchedFor: 30 }).doze > 0, 'on a window too');
  assert.ok(pick({ idleFor: 60, tired: 1, seated: true, seatedFor: 5 }).doze > 0, 'and sitting on the floor');
});

test('nodding off: lids close as her head sinks, then she starts awake chest first, head last, a touch past upright', () => {
  const g = t => ({ ...gesture('doze', t), bones: gesture('doze', t).adds });     // (added on top of her pose)
  assert.deepEqual(gesture('doze', 1).bones, {}, 'nothing replaced: sitting, perched or standing keep their pose');
  assert.ok(gesture('doze', 1).ownBlinks, 'her own blinks wait: the wake-up blinks are its own');
  assert.ok(g(2.6).eyes > 0.95 && g(2.6).bones.head[0] > 0.3, 'asleep: eyes shut, head down');
  assert.ok(g(1.0).bones.head[0] < g(2.0).bones.head[0], 'sinking');
  // it catches itself a little halfway
  assert.ok(g(1.55).bones.head[0] - g(1.3).bones.head[0] < g(2.3).bones.head[0] - g(2.05).bones.head[0]);
  // waking: the chest is already coming up while the head is still down
  const w = 2.7 + 0.08;
  assert.ok(g(w).bones.chest[0] / 0.08 < g(w).bones.head[0] / 0.36, 'chest leads, head follows');
  let past = 0;
  for (let t = 2.7; t < 3.4; t += 0.01) past = Math.min(past, g(t).bones.head[0]);
  assert.ok(past < 0 && past > -0.05, `a touch past upright (${past})`);
  assert.ok(g(2.9).eyes < 0.1, 'eyes open at once');
  assert.ok(g(3.05).eyes > 0.5 && g(3.3).eyes > 0.5 && g(3.17).eyes < 0.3, 'two quick blinks');
  assert.ok(g(4.0).face.happy > 0.2, 'a sheepish smile');
  assert.ok(g(3.0).alert > 0.9 && g(1.0).alert === 0 && g(GESTURES.doze - 0.01).alert < 0.1, 'wide awake for a moment, then heavy lids again');
  // no bone jumps between frames, the wake-up included
  for (let t = 0; t < GESTURES.doze - 0.01; t += 1 / 60)
    for (const b of ['chest', 'neck', 'head']) assert.ok(Math.abs(g(t + 1 / 60).bones[b][0] - g(t).bones[b][0]) < 0.08, `${b} at ${t}`);
});

test('an almost-sneeze: two breaths in with a hand to her nose, a frozen beat, nothing, relief; rare', () => {
  const g = t => gesture('almostSneeze', t, 1);
  // head and chest lead (their own weight) before the arm has got going
  assert.ok(g(0.3).weights.head > 0.9 && g(0.3).weight < 0.3);
  // her chin lifts and her eyes squint as the breath comes, with a second, smaller breath on top
  const chin = t => -g(t).bones.head[0];
  assert.ok(chin(0.9) > 0.05 && chin(1.35) > chin(0.95), 'second breath in');
  assert.ok(g(1.4).eyes > 0.5 && g(1.4).mouth > 0.1);
  // the frozen beat trembles a little; then it is let go: the chest and head sag forward with relief
  assert.ok(g(2.2).bones.head[0] > 0 && g(2.2).face.relaxed > 0.3, 'relief');
  // the elbow drops before the forearm unfolds, and the fingers open last
  assert.ok(g(2.3).weights.rightUpperArm < g(2.3).weights.rightLowerArm && g(2.3).bones.rightLowerArm[1] > 1.9, 'elbow first');
  assert.ok(g(3.0).hands.right.curl[0] < HANDS.relaxed.curl[0] && g(3.55).weight < 0.05, 'fingers open last');
  // rare: at most every 10 minutes, whatever else she has done since
  const picks = since => { let n = 0; for (let i = 0; i < 400; i++) n += chooseIdle({ idleFor: 60, since }, (i + 0.5) / 400, 0.3).gesture === 'almostSneeze'; return n; };
  assert.ok(picks({}) > 0 && picks({ almostSneeze: 599 }) === 0 && picks({ almostSneeze: 601 }) > 0);
  // the other side is the same with the left hand; nothing jumps between frames
  const m = gesture('almostSneeze', 1.2, -1);
  assert.ok(m.bones.leftUpperArm && !m.bones.rightUpperArm && m.hands.left && !m.hands.right);
  for (let t = 0; t < GESTURES.almostSneeze - 1 / 60; t += 1 / 60) {
    const [a, c] = [g(t), g(t + 1 / 60)];
    for (const [bone, v] of Object.entries(a.bones)) v.forEach((x, i) => assert.ok(Math.abs(c.bones[bone][i] - x) < 0.08, `${bone} at ${t}`));
    assert.ok(Math.abs(c.weight - a.weight) < 0.08 && Math.abs(c.eyes - a.eyes) < 0.08);
  }
});

test('crossing her ankles on a window: only on an ordinary edge, the swing quiets first, a lift to clear, then back', () => {
  const g = t => gesture('crossAnkles', t, 1), L = GESTURES.crossAnkles;
  // only sitting on a window's edge: not standing, not at a corner or on the panel (canCross says which)
  const picks = o => { let n = 0; for (let i = 0; i < 300; i++) n += chooseIdle(o, (i + 0.5) / 300, 0.3).gesture === 'crossAnkles'; return n; };
  assert.equal(picks({ idleFor: 60 }), 0);
  assert.equal(picks({ idleFor: 60, perched: true, perchedFor: 20 }), 0);
  assert.ok(picks({ idleFor: 60, perched: true, perchedFor: 20, canCross: true }) > 0);
  // where she may cross (or keep crossed) her ankles: the page fades a crossing out the moment this turns false
  assert.ok(crossFits({ perched: { since: 0 } }));
  assert.ok(!crossFits({}), 'standing');
  assert.ok(!crossFits({ perched: { since: 0 }, jumping: true }), 'hopping down');
  assert.ok(!crossFits({ perched: { since: 0, corner: 1 } }), 'at a corner her legs swing');
  assert.ok(!crossFits({ perched: { since: 0, low: 1 } }), 'on the panel her legs hang behind it');
  assert.ok(!crossFits({ perched: { since: 0 }, carried: true }), 'picked up');
  // added on top of her sitting pose, never replacing it
  assert.deepEqual(g(3).bones, {});
  // her swing has quieted before the legs move, and comes back only once they're apart again
  assert.ok(g(0.3).calm > 0.5 && g(0.3).adds.leftUpperLeg[1] < 0.01);
  assert.ok(g(L - 0.45).adds.leftUpperLeg[1] < 0.02 && g(L - 0.45).calm > 0.9 && g(L - 0.05).calm < 0.1);
  // crossed: the thigh turned in about its length (the foot comes across), the knee a little straighter (in front)
  assert.ok(g(3).adds.leftUpperLeg[1] > 0.24 && g(3).adds.leftLowerLeg[0] < -0.14);
  // the knee lifts to clear the other foot on the way over and on the way back, not while resting
  const lift = t => -g(t).adds.leftUpperLeg[0] - 0.05 * g(t).adds.leftUpperLeg[1] / 0.25;
  assert.ok(lift(0.65) > 0.06 && lift(L - 0.8) > 0.06 && lift(3) < 0.01);
  // toes follow the shin a moment later, and wiggle once while she rests
  assert.ok(g(0.7).adds.leftFoot[0] < 0.1 * g(0.7).adds.leftUpperLeg[1] / 0.25 + 1e-9);
  assert.ok(g(3.9).adds.leftFoot[0] > g(3.0).adds.leftFoot[0] + 0.1);
  // the other side crosses the right leg over; nothing jumps between frames
  assert.ok(gesture('crossAnkles', 3, -1).adds.rightUpperLeg[1] < -0.24);
  for (let t = 0; t < L - 1 / 60; t += 1 / 60)
    for (const [b, v] of Object.entries(g(t).adds)) v.forEach((x, i) => assert.ok(Math.abs(g(t + 1 / 60).adds[b][i] - x) < 0.05, `${b} at ${t}`));
});

test('elbows and knees only bend their own way, whatever adds up', () => {
  assert.deepEqual(withinLimits('leftLowerArm', [0.1, 0.4, 0, 0]), [0.1, 0, 0, 0]);        // would bend backward: straight
  assert.deepEqual(withinLimits('rightLowerArm', [0, -0.4, 0.2]), [0, 0, 0.2, 0]);
  assert.deepEqual(withinLimits('rightLowerArm', [0, 9, 0, 0]), [0, 2.5, 0, 0]);           // not past folded
  assert.deepEqual(withinLimits('leftLowerArm', [0, -1.5, 0, 0]), [0, -1.5, 0, 0]);
  assert.deepEqual(withinLimits('leftLowerLeg', [-0.3, 0, 0, 0]), [0, 0, 0, 0]);
  assert.deepEqual(withinLimits('head', [1, 2, 3, 4]), [1, 2, 3, 4]);
  // nothing she does on her own asks for more than a joint can do
  for (let t = 0; t < 12; t += 0.07) {
    const pieces = [idleMotion(t), talkMotion(t, 1), walkCycle(t * 5).bones];
    for (const state of STATES) {
      const pose = poseFor(state).bones;
      for (const name of ['leftLowerArm', 'rightLowerArm', 'leftLowerLeg', 'rightLowerLeg']) {
        // (thinking, her elbow is folded all the way to bring her finger to her chin: the limit holds it there)
        if (state === 'thinking' && name === 'rightLowerArm') continue;
        const sum = [0, 1, 2, 3].map(i => pose[name][i] + pieces.reduce((n, p) => n + (p[name]?.[i] || 0), 0));
        assert.deepEqual(withinLimits(name, sum), sum, `${state} ${name} at ${t}`);
      }
    }
  }
  for (const [name, length] of Object.entries(GESTURES)) {
    for (let t = 0; t < length; t += 0.05) {
      for (const [bone, angles] of Object.entries(gesture(name, t).bones)) {
        const four = [0, 1, 2, 3].map(i => angles[i] || 0);
        assert.deepEqual(withinLimits(bone, four), four, `${name} ${bone} at ${t}`);
      }
    }
  }
});
test('called back while still sitting down, she stands up from where she got to, without a jump', () => {
  const half = sitting(0.9, null).w;
  assert.ok(Math.abs(sitting(0.9, 0.9).w - half) < 1e-9);
  assert.ok(sitting(0.95, 0.9).w <= half);
});
test('she turns side-on before she folds her legs, and only turns back once she is up', () => {
  for (let t = 0; t < 2.5; t += 0.05) {
    const s = sitting(t, null);
    if (s.w > 0.05) assert.ok(s.turn > 0.95, `folding at ${t.toFixed(2)} while still facing front`);
  }
  for (let t = 30; t < 32; t += 0.05) {
    const s = sitting(t, 30);
    if (s && s.turn < 0.95) assert.ok(s.w < 0.05, `turning back at ${t.toFixed(2)} while still folded`);
  }
  assert.ok(sitting(30, null).turn === 1);
});

test('a trip goes where the room is: never past the edge, and none when there is no room either way', () => {
  assert.equal(planTrip({ left: 0.2, right: 0.1 }, 0.5, 0.5), null);
  assert.equal(planTrip(null, 0.5, 0.5), null);
  for (let i = 0; i < 200; i++) {
    const [r1, r2] = [(i * 0.618) % 1, (i * 0.377) % 1];
    const room = { left: 3 * ((i * 0.29) % 1), right: 0.4 + (i % 7) * 0.5 };
    const plan = planTrip(room, r1, r2);
    const reach = plan.side < 0 ? room.left : room.right;
    assert.ok(reach >= TRIP.min, 'only toward a side with room');
    const end = trip(tripLength(plan.leg, plan.peek) - 1e-6, plan.leg, plan.side, plan.peek);
    assert.ok(Math.abs(end.x) <= reach + 1e-9 && Math.abs(end.x) >= TRIP.min - 1e-9, `went ${end.x} with ${reach} of room`);
    if (plan.peek) assert.ok(Math.abs(Math.abs(end.x) - reach) < 1e-9, 'a peek happens at the edge itself');
  }
  // only one side has room: she goes that way
  assert.equal(planTrip({ left: 0, right: 2 }, 0.01, 0.5).side, 1);
  assert.equal(planTrip({ left: 2, right: 0.1 }, 0.99, 0.5).side, -1);
  // the side with more room is the likelier one, so she drifts back toward the middle
  let right = 0;
  for (let i = 0; i < 100; i++) right += planTrip({ left: 0.5, right: 3 }, (i + 0.5) / 100, 0.5).side > 0;
  assert.ok(right > 75, `${right} of 100 went to the roomier side`);
});

test('a trip turns, walks without skating, stays where it ends and faces front again', () => {
  const leg = planTrip({ left: 0, right: 2 }, 0.5, 0.9).leg, total = tripLength(leg);
  let last = trip(0, leg, 1);
  assert.equal(last.x, 0);
  assert.equal(last.yaw, 0);
  for (let t = 0.01; t < total; t += 0.01) {
    const now = trip(t, leg, 1);
    assert.ok(Math.abs(now.x - last.x) <= WALK.speed * 0.01 + 1e-9, 'never faster than walking');
    assert.ok(Math.abs(now.yaw - last.yaw) < 0.06, 'her body turns smoothly');
    // walking, her steps follow the distance (turning, she takes a step of her own on the spot)
    if (now.speed > 0 && last.speed > 0) assert.ok(Math.abs(now.phase - last.phase - Math.PI * WALK.stepsPerS * (now.x - last.x) / WALK.speed) < 1e-9,
                                 'steps follow the distance');
    last = now;
  }
  assert.ok(Math.abs(last.yaw) < 1e-3, 'facing front at the end');
  assert.equal(trip(total, leg, 1), null);
  const left = trip(total / 2, leg, -1), right = trip(total / 2, leg, 1);
  assert.equal(left.x, -right.x);
  assert.equal(left.yaw, -right.yaw);
});

test('cutting a trip short slows her down from where she is, without a jump', () => {
  const leg = 6;
  for (const u of [0.2, 0.6, 1.5, 4, 6.2, 6.6]) {
    const cut = cutLeg(leg, u);
    assert.ok(cut <= leg);
    const [a, b] = [trip(u, leg, 1), trip(u, cut, 1)];
    assert.ok(Math.abs(a.x - b.x) < 1e-9, `no jump in where she is (cut at ${u})`);
    assert.ok(Math.abs(a.speed - b.speed) < 1e-9, `no jump in her speed (cut at ${u})`);
    assert.ok(tripLength(cut) - u <= 2 * 0.4 + 2 * 0.45, 'she is stopped and facing front within two seconds');
  }
  assert.equal(cutLeg(leg, 6.3), leg, 'already slowing down: unchanged');
});

test('a jump up onto a window: crouch, one smooth arc, land sitting on the edge with a small bounce', () => {
  for (const dy of [0.4, 1.2, 2.5]) {
    const n = jumpLength(dy);
    let last = jump(0, dy);
    assert.deepEqual([last.y, last.ledge, last.crouch], [0, 0, 0]);
    for (let t = 0.005; t < n; t += 0.005) {
      const j = jump(t, dy);
      assert.ok(Math.abs(j.y - last.y) < 0.06 * Math.max(1, dy), `no jump in her height at ${t}`);
      assert.ok(Math.abs(j.ledge - last.ledge) < 0.1 && Math.abs(j.crouch - last.crouch) < 0.1, 'her pose flows');
      assert.ok(j.y <= dy + 0.3, 'over the edge only a little before coming down onto it');
      last = j;
    }
    assert.ok(Math.abs(last.y - dy) < 0.002 && last.ledge === 1, 'sitting on the edge at the end');
    assert.equal(jump(n, dy), null);
  }
});

test('hopping down: a push off the edge, a fall that speeds up, a crouch to land and up again', () => {
  const dy = -1.5, n = jumpLength(dy);
  assert.equal(jump(0, dy).ledge, 1);
  const ys = [];
  for (let t = 0; t < n; t += 0.02) ys.push(jump(t, dy).y);
  const drops = ys.slice(1).map((y, i) => ys[i] - y).filter(d => d > 1e-6);
  assert.ok(drops.at(-1) > drops[0], 'falling faster near the floor');
  const end = jump(n - 1e-6, dy);
  assert.ok(Math.abs(end.y - dy) < 1e-9 && end.ledge === 0 && end.crouch < 0.01, 'standing on the floor at the end');
});

test('on the edge her thighs are level, so the window edge is under them; crouching keeps her feet down', () => {
  const p = perchPose(1, 0);
  assert.ok(Math.abs(p.bones.leftUpperLeg[0] + Math.PI / 2) < 0.1 && Math.abs(p.bones.rightUpperLeg[0] + Math.PI / 2) < 0.1);
  assert.ok(p.bones.leftLowerLeg[0] > 1.2, 'shins hanging down');
  assert.ok(Math.abs(p.lift) < 1e-12);
  const c = perchPose(0, 1), thigh = c.bones.leftUpperLeg[0], knee = thigh + c.bones.leftLowerLeg[0];
  const drop = LEG.thigh * (1 - Math.cos(thigh)) + LEG.shin * (1 - Math.cos(knee));
  assert.ok(Math.abs(c.lift + drop) < 1e-9, 'body drops exactly as far as her knees bend');
  assert.ok(LEDGE_Y < LEG.hip && LEDGE_Y > LEG.hip - 0.08);
  const d = dangle(10);
  assert.ok(Math.abs(d.leftLowerLeg[0]) <= 0.28 && Math.abs(d.rightLowerLeg[0]) <= 0.28);
});

test('which seat: the spot on a free stretch nearest to her, clear of its ends; none without one', () => {
  assert.equal(planPerch([], 0.5), null);
  assert.equal(planPerch([{ x: 0, half: 40, y: -300 }], 0.5), null);        // too short a stretch
  assert.deepEqual(planPerch([{ x: 0, half: 200, y: -300 }], 0.5), { dx: 0, y: -300 });    // right above her
  assert.deepEqual(planPerch([{ x: 500, half: 200, y: -300 }], 0.5), { dx: 360, y: -300 }); // its near end
  assert.deepEqual(planPerch([{ x: -500, half: 200, y: -300 }], 0.5), { dx: -360, y: -300 });
  let near = 0;
  for (let i = 0; i < 100; i++) near += planPerch([{ x: 100, half: 200, y: -200 }, { x: 1400, half: 200, y: -200 }], (i + 0.5) / 100).dx < 500;
  assert.ok(near > 60, `the nearer window is the likelier one (${near} of 100)`);
});

test('on a window\'s top corner she sits just in from it, when the stretch ends at a real corner', () => {
  const seat = { x: 500, half: 200, y: -300, corners: [-1, 1] };
  assert.deepEqual(planPerch([seat], 0.5, 60, 0), { dx: 360, y: -300, corner: -1 }, 'the nearer corner');
  assert.deepEqual(planPerch([{ ...seat, x: -500 }], 0.5, 60, 0), { dx: -360, y: -300, corner: 1 });
  assert.deepEqual(planPerch([{ ...seat, corners: [1] }], 0.5, 60, 0), { dx: 640, y: -300, corner: 1 }, 'the only real corner');
  assert.deepEqual(planPerch([seat], 0.5, 60, CORNER_CHANCE + 0.01), { dx: 360, y: -300 }, 'not every time');
  assert.deepEqual(planPerch([{ ...seat, corners: [] }], 0.5, 60, 0), { dx: 360, y: -300 }, 'covered ends are no corners');
  assert.deepEqual(planPerch([{ x: 0, half: 5000, y: 240, low: 1, corners: [-1] }], 0.5, 60, 0), { dx: 0, y: 240 }, 'not on the panel');
});

test('on a corner her legs swing steadily, one forward as the other goes back; never a stiff stop', () => {
  let peak = 0, still = 0, against = 0, n = 0;
  for (let t = 0; t < 120; t += 0.05) {
    const d = dangle(t, 1), l = d.leftLowerLeg[0], r = d.rightLowerLeg[0];
    peak = Math.max(peak, Math.abs(l));
    if (Math.abs(l) + Math.abs(r) > 0.1) { n++; against += l * r < 0; }
    assert.ok(Math.abs(d.spine[0]) < 0.03 && Math.abs(d.head[0]) < 0.03, 'her body only rocks a hair');
    assert.ok(d.leftUpperLeg[0] <= 0 && d.leftUpperLeg[0] > -0.1, 'thighs lift a little, forward only');
  }
  assert.ok(peak > 0.3 && peak <= 0.42, `a real swing, not a kick through the window (${peak})`);
  assert.ok(peak > 0.28, 'bigger than the idle dangle');
  assert.ok(against / n > 0.95, 'legs alternate');
  for (let s = 0; s < 120; s++) {                  // every second of it has a visible swing in it
    let most = 0;
    for (let t = s; t < s + 1; t += 0.02) most = Math.max(most, Math.abs(dangle(t, 1).leftLowerLeg[0]));
    if (most < 0.1) still++;
  }
  assert.equal(still, 0, `she keeps swinging (${still} seconds without)`);
  // smooth: no jump between frames at 60 fps
  for (let t = 0; t < 30; t += 1 / 60) assert.ok(Math.abs(dangle(t + 1 / 60, 1).leftLowerLeg[0] - dangle(t, 1).leftLowerLeg[0]) < 0.06);
});

test('on a window she does seated things and in time hops down; she only goes up when there is a window', () => {
  const picks = new Set();
  for (let i = 0; i < 300; i++) {
    const act = chooseIdle({ perched: true, perchedFor: 150, idleFor: 120 }, (i + 0.5) / 300, 0.3);
    picks.add(act.gesture || Object.keys(act)[0]);
  }
  for (const p of picks) assert.ok(PERCHED_FIDGETS.includes(p), `${p} on a window`);
  assert.ok(picks.has('hopDown'));
  const early = new Set();
  for (let i = 0; i < 300; i++) {
    const act = chooseIdle({ perched: true, perchedFor: 5 }, (i + 0.5) / 300, 0.3);
    early.add(act.gesture || Object.keys(act)[0]);
  }
  assert.ok(!early.has('hopDown'), 'not straight away');
  for (let i = 0; i < 300; i++) {                     // nor within the first minute and a half
    const act = chooseIdle({ perched: true, perchedFor: 85 }, (i + 0.5) / 300, 0.3);
    assert.ok(!act.hopDown, 'stays up a while');
  }
  const without = new Set(), withWin = new Set();
  for (let i = 0; i < 300; i++) {
    const r = (i + 0.5) / 300;
    without.add(Object.keys(chooseIdle({ idleFor: 60 }, r, 0.3))[0]);
    withWin.add(Object.keys(chooseIdle({ idleFor: 60, canPerch: true }, r, 0.3))[0]);
  }
  assert.ok(!without.has('perch') && withWin.has('perch'));
});

test('planHide picks the nearer edge and stops just behind it', () => {
  assert.equal(planHide([], 0.5), null);
  const edges = [{ id: 1, x: -0.8, out: -1 }, { id: 1, x: 2.5, out: 1 }];
  const plan = planHide(edges, 0.2);
  assert.equal(plan.id, 1);
  assert.equal(plan.out, -1);
  assert.ok(Math.abs(plan.dx - (-0.8 + PEEK.inset)) < 1e-9, 'her middle stops inset behind the edge');
  let near = 0;
  for (let i = 0; i < 100; i++) near += planHide(edges, (i + 0.5) / 100).out === -1;
  assert.ok(near > 55, `the nearer edge is the likelier one (${near})`);
});

test('the lean-out brings her head past the edge and back', () => {
  assert.ok(headPastEdge(1) > PEEK.inset + 0.04, 'at full lean her head is past the edge');
  const lean = (t, out) => { const b = peekOut(t, out).bones;
    return ['spine', 'chest', 'neck', 'head'].reduce((a, n) => a + (b[n]?.[2] || 0), 0); };
  assert.ok(Math.abs(lean(0, 1)) < 0.02);
  assert.ok(Math.abs(lean(1.5, 1)) >= 0.5, 'leaning well out');
  assert.equal(Math.sign(lean(1.5, 1)), -Math.sign(lean(1.5, -1)), 'toward the side she peeks out of');
  assert.ok(Math.abs(lean(PEEK.length - 0.01, 1)) < 0.05, 'back in at the end');
  assert.equal(peekOut(PEEK.length, 1), null);
  assert.deepEqual(peekOut(1.5, 1).look, [0, 0], 'looking at you');
});

test('the lean-out is smooth', () => {
  let last = peekOut(0, 1);
  for (let t = 0.01; t < PEEK.length; t += 0.01) {
    const now = peekOut(t, 1);
    for (const [name, a] of Object.entries(now.bones))
      a.forEach((v, i) => assert.ok(Math.abs(v - (last.bones[name]?.[i] || 0)) < 0.05, `${name} at ${t}`));
    last = now;
  }
});

test('hiding is only chosen standing, with somewhere to hide', () => {
  const picks = opts => { const seen = new Set();
    for (let i = 0; i < 300; i++) { const a = chooseIdle(opts, (i + 0.5) / 300, 0.3); seen.add(a.gesture || Object.keys(a)[0]); }
    return seen; };
  assert.ok(!picks({ idleFor: 60 }).has('hide'), 'not without a window to hide behind');
  assert.ok(picks({ idleFor: 60, canHide: true }).has('hide'));
  assert.ok(!picks({ idleFor: 60, canHide: true, seated: true }).has('hide'));
  assert.ok(!picks({ idleFor: 60, canHide: true, perched: true }).has('hide'));
});

test('she walks at a relaxed human pace: about half her height a second, near two steps a second', () => {
  const height = 0.95;
  assert.ok(WALK.speed / height > 0.4 && WALK.speed / height < 0.7, `${WALK.speed / height} heights a second`);
  assert.ok(WALK.stepsPerS >= 1.7 && WALK.stepsPerS <= 2.0);
});

test('a trip is a few seconds of walking, not the whole screen', () => {
  for (let i = 0; i < 100; i++) {
    const plan = planTrip({ left: 6, right: 6 }, (i + 0.5) / 100, ((i * 0.37) % 1));
    const end = trip(tripLength(plan.leg, plan.peek) - 1e-6, plan.leg, plan.side, plan.peek);
    assert.ok(Math.abs(end.x) <= TRIP.max + 1e-9, `went ${end.x}`);
  }
});

test('turning, she steps round instead of pivoting on planted feet', () => {
  const leg = 3, turn = trip(0.2, leg, 1), start = trip(0, leg, 1);
  assert.ok(turn.amount > 0.2, 'her legs step while she turns');
  assert.ok(turn.phase > start.phase, 'the step moves on');
  const end = trip(tripLength(leg) - 0.2, leg, 1);
  assert.ok(end.amount > 0.2, 'and when she turns back to you');
  assert.ok(trip(tripLength(leg) - 1e-6, leg, 1).amount < 0.05, 'feet together at the very end');
});

test('a big jump of her gaze comes with a blink (not a small drift, and not twice in a row)', () => {
  assert.equal(lookBlink([0, 0], [0.9, 0.2], 5), true);
  assert.equal(lookBlink([0, 0], [0.2, 0.1], 5), false, 'small drift: no blink');
  assert.equal(lookBlink([0, 0], [0.9, 0.2], 0.4), false, 'just blinked');
});

test('a seat below her feet (the panel): she sits down where she is, no jump', () => {
  assert.deepEqual(planPerch([{ x: 0, half: 5000, y: 240, low: 1 }], 0.5), { dx: 0, y: 240 });
  assert.equal(planPerch([{ x: 0, half: 5000, y: 240 }], 0.5), null, 'a window below her is not a seat');
});

test('sitting down onto a low edge: knees bend, she lowers herself over it and settles; and back up', () => {
  const dy = -0.57, n = edgeSitLength(dy);
  let last = edgeSit(0, dy);
  assert.deepEqual([last.y, last.ledge], [0, 0]);
  for (let t = 0.01; t < n; t += 0.01) {
    const now = edgeSit(t, dy);
    assert.ok(Math.abs(now.y - last.y) < 0.03 && Math.abs(now.ledge - last.ledge) < 0.06, `smooth at ${t}`);
    assert.ok(now.y <= 1e-9 && now.y >= dy - 0.02, 'only down, never below the edge');
    last = now;
  }
  assert.ok(Math.abs(last.y - dy) < 1e-6 && last.ledge === 1, 'sitting on the edge at the end');
  assert.equal(edgeSit(n, dy), null);
  const up = 0.57, m = edgeSitLength(up);
  assert.equal(edgeSit(0, up).ledge, 1);
  assert.ok(edgeSit(0.25, up).lean > 0.1, 'leans forward to push up');
  const end = edgeSit(m - 1e-6, up);
  assert.ok(Math.abs(end.y - up) < 1e-6 && end.ledge < 0.01 && end.crouch < 0.01, 'standing at the end');
});

// ── companion reactions (Engines/Companion.py asks for a gesture; it has to fit what she's doing) ──
import { reactionFor, SEATED_FIDGETS as SEATED, PERCHED_FIDGETS as PERCHED } from './logic.mjs';

test('a reaction plays as asked while she stands free', () => {
  assert.equal(reactionFor('think'), 'think');
  assert.equal(reactionFor('lean'), 'lean');
  assert.equal(reactionFor('nonsense'), null);
});

test('no reaction while she walks, jumps, hides or is busy with another gesture', () => {
  for (const busy of ['walking', 'jumping', 'hiding', 'gesturing']) assert.equal(reactionFor('think', { [busy]: true }), null);
});

test('sitting or perched she reacts with something that works sitting down', () => {
  for (const name of ['think', 'lean', 'rock', 'stretch', 'curious', 'smile', 'lookAround']) {
    const seated = reactionFor(name, { seated: true });
    const perched = reactionFor(name, { perched: true });
    assert.ok(SEATED.includes(seated) && seated !== 'standUp', `${name} seated -> ${seated}`);
    assert.ok(PERCHED.includes(perched) && perched !== 'hopDown', `${name} perched -> ${perched}`);
  }
});

// ── the test card (Engines/Companion.py sends the next test; she holds it up now and then) ──
import { cardText } from './logic.mjs';

test('the card is up in the middle of the gesture and away at both ends', () => {
  assert.equal(gesture('showCard', 0).card, 0);
  assert.equal(gesture('showCard', 2).card, 1);
  assert.ok(gesture('showCard', 4.45).card < 0.05);
  assert.deepEqual(gesture('showCard', 2).look, [0, 0.05]);
  assert.ok(gesture('showCard', 2).face.happy > 0.3);
  assert.equal(gesture('showCard', 4.7), null);
  assert.ok(FIDGETS.includes('showCard'));
});

test('the card is offered only when there is a test to show, and never sitting', () => {
  const others = Object.keys(IDLE).filter(n => n !== 'showCard');
  const pick = canCard => chooseIdle({ idleFor: 60, canCard, recent: others }, 0.0, 0.3);
  assert.equal(pick(true).gesture, 'showCard');
  assert.notEqual(pick(false).gesture, 'showCard');
  for (const r of [0, 0.3, 0.6, 0.99]) {
    assert.notEqual(chooseIdle({ idleFor: 60, canCard: true, seated: true }, r, 0.3).gesture, 'showCard');
    assert.notEqual(chooseIdle({ idleFor: 60, canCard: true, perched: true }, r, 0.3).gesture, 'showCard');
  }
});

test('card text fits', () => {
  assert.deepEqual(cardText({ subject: 'Maths', when: 'Thursday' }), { big: 'Maths', small: 'Thursday' });
  assert.equal(cardText({ subject: 'Softwareentwicklung und Projektmanagement', when: 'tomorrow' }).big.length, 18);
  assert.deepEqual(cardText({ subject: 'Deutsch' }), { big: 'Deutsch', small: '' });
  assert.equal(cardText(null), null);
  assert.equal(cardText({ subject: '  ' }), null);
});

// ── the umbrella (rain coming: Engines/Companion.py sends it; she pulls one out now and then) ──

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

test('holding the umbrella she only looks up at it as it opens; otherwise her gaze is her own', () => {
  assert.ok(gesture('umbrella', 2.6).look[1] > 0.3);
  for (const s of [1, 5, 8, 13]) assert.equal(gesture('umbrella', s).look, undefined, `at ${s} s`);
});

// ── bob to music ──

test('she nods down on the beat and is back up between beats', () => {
  const on = bobMotion(0.05, 1, 120), between = bobMotion(0.5, 1, 120);
  assert.ok(on.head[0] > 0.05 && Math.abs(between.head[0]) < 0.01);
  assert.ok(on.lift <= between.lift);                        // down with the nod, up on the off-beat
  const none = bobMotion(0.05, 0, 120);
  assert.ok(Object.entries(none).every(([k, v]) => k === 'lift' ? v === 0 : v.every(x => x === 0)));
});

test('a fast song gets a nod every other beat, never frantic', () => {
  const nods = bpm => { let n = 0, was = false;
    for (let b = 0.5; b < 8.5; b += 0.02) { const down = bobMotion(b, 1, bpm).head[0] > 0.05; if (down && !was) n++; was = down; }
    return n; };
  assert.equal(nods(120), 8);
  assert.equal(nods(170), 4);
});

test('her beat clock follows small corrections gently and jumps to a new song', () => {
  let c = beatClock(null, 120, 0.2, 10);                      // a beat at 10.2 s
  assert.ok(Math.abs(beatsAt(c, 10.2) % 1) < 1e-6);
  c = beatClock(c, 120, 0.25, 10.5);                          // the next report says 10.75 instead of 10.7
  const off = beatsAt(c, 10.75) % 1;
  assert.ok(off > 0.01 && off < 0.09);                        // old clock: 0.1 beat past; moved partway
  c = beatClock(c, 90, 0.1, 11);                              // another song
  assert.equal(c.bpm, 90);
  assert.ok(Math.abs(beatsAt(c, 11.1) % 1) < 1e-6);
});

// ── polish: the quiet fidgets have to read at her size on the screen (about 450 px tall) ──

test('every quiet fidget moves her upper body enough to see', () => {
  const body = ['hips', 'spine', 'chest', 'neck', 'head'];
  for (const name of ['lean', 'rock', 'smile', 'sigh', 'curious', 'lookAround']) {
    let most = 0;
    for (let t = 0; t < GESTURES[name]; t += 0.05) {
      const b = gesture(name, t, 1).bones;
      most = Math.max(most, body.reduce((s, k) => s + Math.abs(b[k]?.[0] || 0) + Math.abs(b[k]?.[1] || 0) + Math.abs(b[k]?.[2] || 0), 0));
    }
    assert.ok(most >= 0.45, `${name} moves her only ${most.toFixed(2)} rad`);
  }
});

test('she leans onto either leg', () => {
  const a = gesture('lean', 1.8, 1).bones, b = gesture('lean', 1.8, -1).bones;
  assert.equal(Math.sign(a.hips[2]), -Math.sign(b.hips[2]));
  assert.ok(a.rightLowerLeg && b.leftLowerLeg);              // the loose knee is the other one
});

test('crouching for the hop lowers her body over her feet instead of lifting her feet off the floor', () => {
  const crouched = gesture('hop', 0.14), landed = gesture('hop', 0.5);
  const drop = WALK.leg * (1 - Math.cos(0.4 * 0.98));
  assert.ok(crouched.lift < -0.8 * drop && crouched.lift > -1.2 * drop);
  assert.ok(landed.lift < 0);                                  // sinks a little on landing
  assert.ok(gesture('hop', 0.27).lift > 0.1);                  // still well up in the air
});

test('her breath, her stance and her fingers are never mechanical', () => {
  // breathing: the time between two breaths in is not always the same
  const peaks = [];
  for (let t = 0.02; t < 80; t += 0.02) {
    const [a, b, c] = [t - 0.02, t, t + 0.02].map(x => idleMotion(x).chest[0]);
    if (b > a && b >= c) peaks.push(t);
  }
  const gaps = peaks.slice(1).map((p, i) => p - peaks[i]).filter(g => g > 2);
  assert.ok(gaps.length > 8 && Math.max(...gaps) - Math.min(...gaps) > 0.25, `${gaps.map(g => g.toFixed(2))}`);
  // on one leg her pelvis turns, her chest turns back against it and her thighs keep her feet pointing the same way
  let turned = 0;
  for (let t = 0; t < 120; t += 0.3) {
    const m = idleMotion(t);
    assert.ok(Math.abs(m.hips[1] + m.leftUpperLeg[1]) < 1e-12 && Math.abs(m.hips[1] + m.rightUpperLeg[1]) < 1e-12);
    if (Math.abs(m.hips[1]) > 0.015) { turned++; assert.ok(m.hips[1] * m.chest[1] < 0); }
  }
  assert.ok(turned > 50, `${turned}`);
  // fingers: curled more toward the little finger, always a little curled, moving, and the two hands not as a pair
  for (let t = 0; t < 60; t += 0.4) {
    const { left, right } = fingerCurl(t);
    for (const hand of [left, right]) {
      assert.equal(hand.length, 4);
      assert.ok(hand.every(c => c > 0.5 && c < 1.7) && hand[3] > hand[0]);
    }
  }
  assert.notDeepEqual(fingerCurl(1).left, fingerCurl(3).left);
  assert.notDeepEqual(fingerCurl(1).left, fingerCurl(1).right);
  // looking around, her head turns first and her hips last
  const back = part => { for (let t = 0.5; t < 3; t += 0.02) if (gesture('lookAround', t).bones[part][1] < 0) return t; };
  assert.ok(back('head') < back('chest') && back('chest') < back('hips'), `${back('head')} ${back('chest')} ${back('hips')}`);
});

test('the piano fits her body: bench under her hips, keys below her elbows and past her knees', async () => {
  const { pianoLayout } = await import('./logic.mjs');
  for (const m of [{ hip: 0.512, thigh: 0.207, shin: 0.234, shoulder: 0.27, upperArm: 0.16 },      // a VRM
                   { hip: 0.33, thigh: 0.15, shin: 0.18, shoulder: 0.19, upperArm: 0.125 }]) {      // the figure
    const l = pianoLayout(m);
    assert.ok(l.lift < 0 && l.benchY < m.hip + l.lift);
    assert.ok(l.keyY > m.hip + l.lift && l.keyY < m.hip + l.lift + m.shoulder);
    assert.ok(l.keyZ > m.thigh * 0.8 && l.keyWidth > 0);
  }
});

test('coming to the piano: it appears first, she turns, sits, then her hands go to the keys; going reverses it', async () => {
  const { pianoStage } = await import('./logic.mjs');
  const first = (on, key) => [...Array(300).keys()].map(i => i / 100).find(s => pianoStage(s, on)[key] > 0.5);
  assert.ok(first(true, 'show') < first(true, 'turn') && first(true, 'turn') < first(true, 'sit') && first(true, 'sit') < first(true, 'hands'));
  const gone = (key) => [...Array(300).keys()].map(i => i / 100).find(s => pianoStage(s, false)[key] < 0.5);
  assert.ok(gone('hands') < gone('sit') && gone('sit') < gone('turn') && gone('turn') < gone('show'));
  assert.deepEqual(pianoStage(5, true), { show: 1, turn: 1, sit: 1, hands: 1 });
  assert.deepEqual(pianoStage(5, false), { show: 0, turn: 0, sit: 0, hands: 0 });
});

test('she plays a tune: the right hand high and busy, the left low on the beats, and it follows the beat clock', async () => {
  const { pianoPerformance, keyUnder, PIANO } = await import('./logic.mjs');
  const s = [...Array(800).keys()].map(i => pianoPerformance(i * 0.02));
  const hits = k => s.filter((x, i) => i && x[k].press > 0.9 && s[i - 1][k].press <= 0.9).length;
  assert.ok(hits('R') > hits('L') && hits('L') > 0);
  assert.ok(s.every(x => x.R.x >= -1 && x.R.x <= 1 && x.L.x >= -1 && x.L.x <= 1 && x.L.x < x.R.x));
  assert.ok(new Set(s.map(x => keyUnder(x.R.x))).size > 4, 'the melody moves over the keys');
  assert.deepEqual(pianoPerformance(1, 3.5).R, pianoPerformance(9, 3.5).R);
  assert.ok(s.some(x => x.dreamy > 0.9) || [...Array(2200).keys()].some(i => pianoPerformance(i * 0.01).dreamy > 0.9));
  assert.equal(keyUnder(-1), 0); assert.equal(keyUnder(1), PIANO.keys - 1);
});

test('at the piano she sits with level thighs and looks down at her hands, and back at you when she glances', async () => {
  const { pianoBody, PIANO } = await import('./logic.mjs');
  const down = pianoBody({ sit: 1, hands: 1 }, { glance: 0, sway: 0, lean: 0, nod: 0, toward: 0, breath: 0 });
  const glance = pianoBody({ sit: 1, hands: 1 }, { glance: 1, sway: 0, lean: 0, nod: 0, toward: 0, breath: 0 });
  assert.ok(down.leftUpperLeg[0] < -1.3 && down.leftLowerLeg[0] > 1.3);
  // glancing she turns her head back against the way she sits, toward you
  assert.ok(down.head[0] > 0.15 && glance.head[0] < down.head[0] && -Math.sign(PIANO.yaw) * glance.head[1] > 0.4);
});

test('she phrases the music: building, then both hands lift off for a breath at the end of each phrase', async () => {
  const { pianoPerformance } = await import('./logic.mjs');
  const at = beats => pianoPerformance(0, beats);
  // a phrase is 16 beats: the breath comes at its very end, with both hands off the keys and nothing pressed
  const breath = at(15.4);
  assert.ok(breath.breath > 0.9 && breath.R.lift > 0.8 && breath.L.lift > 0.6 && breath.R.press === 0 && breath.L.press === 0);
  assert.ok(at(4).breath === 0 && at(4).R.lift < 0.5);
  // it builds: louder in the third bar than at the start, and she leans in more
  assert.ok(at(10).intensity > at(0.5).intensity && at(10).lean > at(0.5).lean);
  // the arm's weight: the wrist dips into a note, deeper when it's louder
  const loud = at(10.01), soft = at(0.01);
  assert.ok(loud.R.dip >= soft.R.dip);
  // her left hand rolls chords: it plays on most eighths, not just the beat
  const lefts = [...Array(32).keys()].filter(k => at(k / 2 + 0.04).L.press > 0.1).length;   // just after each eighth
  assert.ok(lefts >= 24, `left hand notes: ${lefts}`);
});

test('her hands take a shape for what she does: open to wave, a finger on her chin, closed on a handle', async () => {
  const { HANDS, handPose, restingHands, mixHand, breeze } = await import('./logic.mjs');
  const mean = h => h.curl.reduce((a, b) => a + b, 0) / 4;
  // the shapes differ where it shows: a waving hand is flat and fanned, a grip is a fist with the thumb across
  assert.ok(mean(HANDS.open) < 0.3 && HANDS.open.spread > 0.5 && HANDS.open.thumb < 0.5);
  assert.ok(mean(HANDS.grip) > 2.5 && HANDS.grip.thumb > 1.5);
  assert.ok(HANDS.chin.curl[0] < 1 && HANDS.chin.curl[1] > 2);                 // index out, the others folded
  for (const h of Object.values(HANDS)) assert.ok(h.curl[3] >= h.curl[0]);      // the little finger curls most
  // resting hands are the old relaxed curl, with the thumb moving along; nothing laid over them leaves them be
  assert.deepEqual(handPose(2.5).left, restingHands(2.5).left);
  assert.deepEqual(restingHands(2.5).right.curl, fingerCurl(2.5).right);
  // a layer takes over by its weight, one hand only when it names only one
  const half = handPose(2.5, [[{ right: HANDS.grip }, 0.5]]), full = handPose(2.5, [[{ right: HANDS.grip }, 1]]);
  assert.deepEqual(half.left, restingHands(2.5).left);
  assert.ok(mean(half.right) > mean(restingHands(2.5).right) && mean(half.right) < mean(full.right));
  assert.deepEqual(full.right, mixHand(restingHands(2.5).right, HANDS.grip, 1));
  // a later layer wins over an earlier one (a gesture over her pose)
  assert.deepEqual(handPose(1, [[{ right: HANDS.chin }, 1], [{ right: HANDS.open }, 1]]).right.spread, HANDS.open.spread);
  // talking opens her fingers, never past straight; walking, the two hands trail their arms the opposite way
  for (let t = 0; t < 20; t += 0.3) {
    const quiet = handPose(t), loud = handPose(t, [], { talk: 1 });
    for (const side of ['left', 'right']) {
      assert.ok(mean(loud[side]) <= mean(quiet[side]) + 1e-9 && loud[side].curl.every(c => c > 0));
    }
  }
  const { swing } = walkCycle(1);
  assert.equal(swing.left, -swing.right);
  const walking = handPose(3, [], { swing });
  assert.notEqual(Math.sign(mean(walking.left) - mean(handPose(3).left)), Math.sign(mean(walking.right) - mean(handPose(3).right)));
  // gestures bring their hands, mirrored with the gesture
  assert.ok(mean(gesture('wave', 1.4).hands.right) < 0.5);
  assert.ok(mean(gesture('wave', 0.05).hands.right) > 0.9);                    // still hanging as the arm starts up
  assert.deepEqual(gesture('think', 2).hands.right, HANDS.chin);
  assert.deepEqual(gesture('yawn', 1.6, 1).hands.right, gesture('yawn', 1.6, -1).hands.left);
  assert.deepEqual(poseFor('thinking').hands, { right: HANDS.chin });
  assert.deepEqual(poseFor('idle').hands, {});
  // the breeze on her hair is small, comes and goes, and is never the same for long
  let most = 0, least = 1;
  for (let t = 0; t < 120; t += 0.25) {
    const m = Math.hypot(...breeze(t));
    most = Math.max(most, m); least = Math.min(least, m);
  }
  assert.ok(most > 0.03 && most < 0.1 && least < 0.005, `${most} ${least}`);
});

test('her feet: flat under a bent knee, rolling as she walks, pointed in the air', () => {
  // standing idle, each foot turns up exactly as far as its shin slants back: the sole stays on the floor
  for (let t = 0; t < 40; t += 0.37) {
    const m = idleMotion(t);
    for (const side of ['left', 'right']) {
      assert.ok(Math.abs(m[`${side}UpperLeg`][0] + m[`${side}LowerLeg`][0] + m[`${side}Foot`][0]) < 1e-9);
    }
  }
  // walking: toes down just after the leg was furthest back, toes up just before it lands in front, and the two
  // feet half a cycle apart
  let down = [0, 0], up = [0, 0];
  for (let ph = 0; ph < 2 * Math.PI; ph += 0.02) {
    const { bones } = walkCycle(ph);
    if (bones.leftFoot[0] > down[1]) down = [ph, bones.leftFoot[0]];
    if (bones.leftFoot[0] < up[1]) up = [ph, bones.leftFoot[0]];
    assert.ok(Math.abs(bones.leftFoot[0] - walkCycle(ph + Math.PI).bones.rightFoot[0]) < 1e-9);
  }
  assert.ok(down[1] > 0.25 && down[1] < 0.45 && up[1] < -0.15 && up[1] > -0.35);
  assert.ok(walkCycle(down[0]).bones.leftUpperLeg[0] > 0);                      // pushing off: that leg is behind her
  assert.ok(walkCycle(up[0]).bones.leftUpperLeg[0] < 0);                        // landing: it is in front
  // a hop: soles flat while she crouches, toes pointed at the top
  const crouch = gesture('hop', 0.14).bones, top = gesture('hop', 0.27).bones;
  assert.ok(Math.abs(crouch.leftUpperLeg[0] + crouch.leftLowerLeg[0] + crouch.leftFoot[0]) < 1e-9);
  assert.ok(top.leftFoot[0] > 0.4 && top.rightFoot[0] > 0.4);
  // sitting on the floor her soles are on it; on an edge her feet hang, toes down
  const sat = sitPose(1).bones;
  assert.ok(Math.abs(sat.leftUpperLeg[0] + sat.leftLowerLeg[0] + sat.leftFoot[0]) < 1e-9);
  assert.ok(perchPose(1, 0).bones.leftFoot[0] > 0.2 && perchPose(0, 1).bones.leftFoot[0] < -0.4);
});

test('her arms follow through: they lag, swing a little past where they stop and settle; the rest stays tight', async () => {
  const { followJoint, LOOSE } = await import('./logic.mjs');
  const q = a => [0, 0, Math.sin(a / 2), Math.cos(a / 2)], angle = r => 2 * Math.atan2(r[2], r[3]);
  for (const name of ['rightHand', 'leftLowerArm']) {
    const memory = new Map();
    followJoint(memory, name, q(0), 1 / 30, 0.5);
    let most = 0, first;
    for (let i = 0; i < 60; i++) {
      const a = angle(followJoint(memory, name, q(1), 1 / 30, 0.5));
      if (i === 0) first = a;
      most = Math.max(most, a);
    }
    assert.ok(first < 0.3, `${name} lags: ${first}`);
    assert.ok(most > 1.01 && most < 1.16, `${name} swings a little past: ${most}`);       // (a loose wrist most)
    assert.ok(Math.abs(angle(followJoint(memory, name, q(1), 1 / 30, 0.5)) - 1) < 0.005);
  }
  // joints that carry her weight or her pose stay on the short filter: exactly that share of the way
  const tight = new Map();
  followJoint(tight, 'hips', q(0), 1 / 30, 0.5);
  assert.ok(Math.abs(angle(followJoint(tight, 'hips', q(1), 1 / 30, 0.5)) - 0.5) < 1e-9);
  assert.ok(!LOOSE.hips && !LOOSE.leftUpperLeg && !LOOSE.head);
  // follow 1 (pinned, or after a pause) puts a loose joint straight there and stops it
  const pinned = new Map();
  followJoint(pinned, 'rightHand', q(0), 1 / 30, 0.5);
  followJoint(pinned, 'rightHand', q(1), 1 / 30, 0.5);
  assert.deepEqual(followJoint(pinned, 'rightHand', q(2), 1 / 30, 1), q(2));
  assert.ok(Math.abs(angle(followJoint(pinned, 'rightHand', q(2), 1 / 30, 0.5)) - 2) < 1e-9);
  // the short way round, and no dt (another figure's rig) means the plain filter
  const plain = new Map();
  followJoint(plain, 'rightHand', q(0.2), 0, 0.5);
  assert.ok(Math.abs(angle(followJoint(plain, 'rightHand', q(0.6), 0, 0.5)) - 0.4) < 1e-9);
});

test('her mouth plays the sounds she says, leans into the next one, and her head dips on stressed syllables', async () => {
  const { speechShapes, speechBeat } = await import('./logic.mjs');
  const said = [[0, 0.1, null, 0, 0], [0.1, 0.3, 'aa', 0.9, 1], [0.3, 0.4, null, 0, 0], [0.4, 0.6, 'ou', 0.8, 0],
                [0.6, 0.7, 'ih', 0.5, 0.5]];
  assert.deepEqual(speechShapes(said, 0.05), { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });       // lips shut ("m")
  assert.deepEqual(speechShapes(said, 0.18), { aa: 0.9, ih: 0, ou: 0, ee: 0, oh: 0 });
  assert.equal(speechShapes(said, 0.35).aa, 0);                                              // shut for the "b"
  // into the next sound in the last 60 ms: half way through that stretch, half of each
  const mid = speechShapes(said, 0.57);
  assert.ok(Math.abs(mid.ou - 0.4) < 1e-9 && Math.abs(mid.ih - 0.25) < 1e-9);
  assert.ok(speechShapes(said, 0.27).aa < 0.9);                                             // closing toward the "b"
  assert.equal(speechShapes(said, 0.7), null);                                               // over
  assert.equal(speechShapes(null, 0.2), null);
  // beats: on stressed vowels only, peaking a little after the vowel starts and gone half a second later
  assert.equal(speechBeat(said, 0.05), 0);
  assert.ok(speechBeat(said, 0.22) > 0.99 && speechBeat(said, 0.22) <= 1);
  assert.ok(speechBeat(said, 0.45) < speechBeat(said, 0.3));
  assert.ok(speechBeat(said, 0.72) <= 0.5);                                                  // the secondary stress
  assert.equal(speechBeat(said, 1.4), 0);
});


test('quiet idle moments mirror naturally and leave seated limbs alone', () => {
  for (const name of ['neckEase', 'quietGlance']) {
    assert.ok(FIDGETS.includes(name) && SEATED_FIDGETS.includes(name) && PERCHED_FIDGETS.includes(name));
    assert.ok(IDLE[name].weight > 0);
    for (let t = 0; t < GESTURES[name]; t += 1 / 60) {
      const right = gesture(name, t, 1), left = gesture(name, t, -1);
      assert.ok(Object.keys(right.bones).every(b => !/Leg|Foot|Arm|Hand/.test(b)));
      assert.equal(right.bones.head[0], left.bones.head[0]);
      assert.equal(right.bones.head[1], -left.bones.head[1]);
      assert.equal(right.bones.head[2], -left.bones.head[2]);
      assert.equal(right.look[0], -left.look[0]);
      for (const v of Object.values(right.face)) assert.ok(Number.isFinite(v) && v >= 0 && v <= 1);
    }
  }
  const aside = gesture('quietGlance', 1.4), back = gesture('quietGlance', 3.5);
  assert.ok(aside.look[0] > 0.5 && back.look[0] === 0);
  assert.equal(aside.face.happy, 0);
  assert.ok(back.face.happy > 0.2, 'smile follows the return of attention');
  assert.ok(gesture('neckEase', 1.5).eyes > 0.3);
  assert.ok(gesture('neckEase', 3.2).bones.head[0] > 0.08, 'chin follows the release');
});

test('broken off, a fidget lets go in order: eyes and head first, a hand at her face comes away before the arm drops', () => {
  const at = gesture('tuckHair', 1.5), start = cutShort(at, 'tuckHair', 0);
  for (const [bone, w] of Object.entries(start.weights)) assert.ok(Math.abs(w - (at.weights?.[bone] ?? at.weight)) < 1e-9, `${bone} jumps`);
  const s = 0.2, mid = cutShort(at, 'tuckHair', s), was = b => at.weights?.[b] ?? at.weight;
  const left = b => mid.weights[b] / was(b);                              // how much of each bone is still held
  assert.ok(left('head') < 0.3, 'her head is yours at once');
  assert.ok(left('rightLowerArm') > left('rightUpperArm'), 'the elbow stays bent while the arm drops');
  assert.ok(mid.handWeight > mid.weight, 'the fingers settle last');
  // every bone only lets go, never grabs back
  for (let t = 0; t < CUT_S; t += 1 / 30) {
    const a = cutShort(at, 'tuckHair', t), b = cutShort(at, 'tuckHair', t + 1 / 30);
    if (b) for (const bone of Object.keys(a.weights)) assert.ok(b.weights[bone] <= a.weights[bone] + 1e-9);
  }
  assert.equal(cutShort(at, 'tuckHair', CUT_S), null);
  // an ordinary fidget: the arm from the shoulder out
  const wrist = cutShort(gesture('checkWrist', 1.2), 'checkWrist', 0.5);
  assert.ok(wrist.weights.leftUpperArm < wrist.weights.leftLowerArm && wrist.weights.leftLowerArm < wrist.weights.leftHand);
});

test('woken from a doze by something, her eyes open at once and she comes up from the chest', () => {
  const at = gesture('doze', 2.2), s = cutShort(at, 'doze', 0.1);
  assert.ok(at.eyes > 0.5 && s.eyes < 0.15 * at.eyes, 'her eyes open within a blink');
  assert.equal(s.ownBlinks, false);
  assert.ok(s.alert * s.weight >= 1, 'wide awake: no heavy lids');
  const held = b => s.adds[b][0] / at.adds[b][0];
  assert.ok(held('chest') < held('neck') && held('neck') < held('head'), 'chest first, then neck, then head');
});

test('a window come up beside her: eyes there first, shoulder and chest flinch, the arm comes up after, the hand last', () => {
  const at = t => gesture('brace', t, 1);
  assert.ok(at(0.06).eyes > 0.9, 'a blink as her eyes jump to it');
  assert.ok(at(0.1).look[0] < -0.5, 'she looks to her right: your left');
  assert.ok(gesture('brace', 0.1, -1).look[0] > 0.5);
  assert.ok(at(0.25).weights.rightShoulder > at(0.25).weights.rightUpperArm, 'the shoulder before the arm');
  assert.ok(at(0.3).weights.rightUpperArm > at(0.3).weights.rightHand, 'the hand trails');
  assert.ok(at(0.5).adds.chest[0] < -0.05 && at(0.5).adds.chest[2] < -0.04, 'chest back and away from it (a negative tilt: to her left)');
  assert.ok(gesture('brace', 0.5, -1).adds.chest[2] > 0.04);
  assert.ok(at(0.5).face.surprised > 0.5 && at(1.6).face.happy > 0.2 && at(1.6).face.surprised < 0.05);
  assert.ok(at(1.85).weights.rightUpperArm < 0.05 && at(1.85).weight < 0.3, 'all let go by the end');
  assert.equal(at(GESTURES.brace), null);
});

test('she flinches only standing about, and not twice in a row', () => {
  assert.ok(mayStartle({ idle: true }));
  assert.ok(!mayStartle({ idle: false }));
  assert.ok(!mayStartle({ idle: true, busy: true }), 'walking, sitting, on a window, mid-gesture');
  assert.ok(!mayStartle({ idle: true, sinceLast: STARTLE_EVERY - 1 }));
});

test('typing to her: she watches the box while you type, looks back at you in a pause, glances aside in a long one', () => {
  assert.deepEqual(typingAttention(null), { down: 0, aside: 0, lean: 0 }, 'an open, empty box is not typing');
  assert.deepEqual(typingAttention(0.2, false), { down: 0, aside: 0, lean: 0 });
  const typing = typingAttention(0.3);
  assert.ok(typing.down === 1 && typing.lean === 1 && typing.aside === 0);
  const pause = typingAttention(TYPING.watch + 1);
  assert.ok(pause.down === 0 && pause.aside === 0, 'back at you');
  assert.ok(typingAttention(TYPING.watch + 0.2).lean > typingAttention(TYPING.watch + 0.2).down, 'her chest lets go after her eyes');
  assert.ok(typingAttention(7).aside > 0.9, 'a long pause: a glance aside');
  assert.equal(typingAttention(TYPING.asideTo + 1).aside, 0, 'only once, then back to you');
  for (let s = 0; s < 12; s += 0.05) {
    const a = typingAttention(s), b = typingAttention(s + 0.05);
    assert.ok(Math.abs(a.down - b.down) < 0.2 && Math.abs(a.aside - b.aside) < 0.2, 'no jumps');
  }
});

test('getting into music: head first, then shoulders, then her body; a song she was into stopping gets a "huh?"', () => {
  const run = (g, on, seconds, gone = true) => { for (let t = 0; t < seconds; t += 1 / 30) g = grooveStep(g, on, 1 / 30, gone); return g; };
  let g = run(null, true, 1.4);
  assert.ok(g.head > 0.2 && g.shoulders === 0 && g.body === 0, 'her head joins first');
  g = run(g, true, 2);
  assert.ok(g.head === 1 && g.shoulders === 1 && g.body === 1);
  const depths = []; g = run(g, true, 0); for (let i = 0; i < 400; i++) { g = grooveStep(g, true, 0.05); depths.push(g.depth); }
  assert.ok(Math.max(...depths) > 0.97 && Math.min(...depths) < 0.78, 'fuller and lighter over a phrase');
  // bobbing parts follow who joined: shoulders lead the head by 80 ms
  const half = bobMotion(0.02, 1, 120, { head: 1, shoulders: 0, body: 0 });
  assert.ok(half.head[0] > 0.1 && half.rightShoulder[2] === 0 && half.chest[0] === 0);
  const full = bobMotion(-0.12, 1, 120);
  assert.ok(full.rightShoulder[2] > full.head[0] / 0.14 * 0.05, 'shoulders are down before her head');
  // the music stops: the parts stay while she fades out, then the tilt
  g = run(g, false, 0.1);
  assert.equal(g.head, 1);
  assert.ok(g.after != null);
  assert.ok(Math.abs(afterMusic(0.8).head[2]) > 0.05 && afterMusic(0.2).head[2] < 0.01, 'her last dip first, then the tilt');
  g = run(g, false, GROOVE.after);
  assert.equal(g.after, null);
  assert.deepEqual(afterMusic(null), {});
  // a short burst of music, or walking off while it plays: no "huh?"
  assert.equal(run(run(null, true, 3), false, 0.1).after, null);
  assert.equal(run(run(null, true, 10), false, 0.1, false).after, null);
  // it comes back quickly: she carries on; after a long break she gets into it afresh
  assert.ok(run(run(run(null, true, 10), false, 1), true, 0.1).on > 9);
  assert.ok(run(run(run(null, true, 10), false, 5), true, 0.1).on < 1);
  // the music comes back while she can't bob, or she gets busy: the "huh?" is off
  const stopped = run(run(null, true, 10), false, 0.3);
  assert.equal(grooveStep(stopped, false, 1 / 30, false).after, null);
  assert.equal(grooveStep(stopped, false, 1 / 30, true, false).after, null);
});

test('speaking, her arm makes one point per thought: ready before the stressed vowel, held to the end, let go after', () => {
  // "so I THOUGHT about it" [pause] "and it WORKS, right" with a "m"-like closure in the middle of the first
  const v = (a, b, stress = 0) => [a, b, 'aa', 0.8, stress], shut = (a, b) => [a, b, null, 0, 0];
  const segs = [v(0, 0.2), v(0.2, 0.4), v(0.45, 0.6, 1), shut(0.6, 0.68), v(0.68, 1.1), v(1.1, 1.3),
                shut(1.3, 1.8),                                     // a breath
                v(1.8, 2.2), v(2.2, 2.4), v(4.3, 4.5, 1), v(4.5, 5.0), v(5.0, 5.4)];
  const plan = phrasePlan(segs);
  assert.equal(plan.length, 2, 'the lip closure doesn\'t split a phrase; one gesture per phrase');
  assert.equal(plan[0].peak, 0.45);
  assert.ok(Math.abs(plan[0].start - (0.45 - PHRASE.prep)) < 1e-9 && plan[0].end === 1.3);
  assert.ok(plan[0].side !== plan[1].side, 'the other hand next time');
  const hand = plan[0].side === 1 ? 'right' : 'left';
  const at = x => phraseGesture(plan, x).bones ?? {};
  assert.deepEqual(at(0.05), {}, 'nothing before it starts');
  assert.ok(Math.abs(at(0.3)[hand + 'UpperArm'][0]) > Math.abs(at(0.3)[hand + 'LowerArm'][1]) / 0.9 * 0.35, 'the upper arm leads the elbow');
  assert.ok(Math.abs(at(0.54)[hand + 'LowerArm'][1]) > Math.abs(at(1.0)[hand + 'LowerArm'][1]), 'the point, then the hold');
  assert.ok(Math.abs(at(1.2)[hand + 'UpperArm'][0]) > 0.15, 'held to the end of the phrase');
  const going = at(1.5);
  assert.ok(Math.abs(going[hand + 'UpperArm'][0]) / 0.35 < Math.abs(going[hand + 'Hand'][1]) / 0.3, 'the wrist lets go last');
  assert.deepEqual(at(1.3 + PHRASE.release + 0.01), {});
  // short phrases and stress-less ones get nothing; gestures don't crowd each other
  assert.deepEqual(phrasePlan([v(0, 0.3, 1), shut(0.3, 0.8), v(0.8, 1.0, 1)]), []);
  assert.deepEqual(phrasePlan([v(0, 2)]), []);
  const busy = []; for (let k = 0; k < 6; k++) busy.push(v(k * 1.2, k * 1.2 + 0.4, 1), v(k * 1.2 + 0.4, k * 1.2 + 0.9), shut(k * 1.2 + 0.9, k * 1.2 + 1.2));
  const many = phrasePlan(busy);
  for (let k = 1; k < many.length; k++) assert.ok(many[k].peak - many[k - 1].peak >= PHRASE.every);
});

test('the pointer still beside her: she watches, reaches, stops just short of it, holds, and lets go; once', () => {
  const run = (s, obs, seconds) => { for (let t = 0; t < seconds; t += 1 / 30) s = catchStep(s, obs, 1 / 30); return s; };
  const here = { near: true, free: true };
  let s = run(null, here, 0.5);
  assert.equal(s.phase, 'dwell');
  s = run(s, { ...here, moved: true }, 1 / 30);                     // a twitch of the mouse: she waits again
  s = run(s, here, 0.5);
  assert.equal(s.phase, 'dwell');
  s = run(s, here, 0.4);
  assert.equal(s.phase, 'reach');
  assert.ok(s.look === 1 && s.weight < 0.05, 'eyes first, the arm after');
  s = run(s, here, 1.0);
  assert.ok(s.weight > 0.95 && s.point > 0.5 && s.track);
  s = run(s, here, 0.7);
  assert.equal(s.phase, 'back');
  s = run(s, here, CATCH.back + 0.1);
  assert.ok(s.phase === 'off' && s.weight === 0);
  // still there: not again (it has to leave and come back, and not within CATCH.every s)
  s = run(s, here, 5);
  assert.equal(s.phase, 'off');
  s = run(run(s, { near: false, free: true }, CATCH.every), here, 1.0);   // gone a while and back: she tries again
  assert.equal(s.phase, 'reach');
});

test('the pointer gets away: her forearm follows a moment, then she gives up; busy, she lets go at once', () => {
  const run = (s, obs, seconds) => { for (let t = 0; t < seconds; t += 1 / 30) s = catchStep(s, obs, 1 / 30); return s; };
  const here = { near: true, free: true };
  let s = run(run(null, here, 0.85), here, 1.0);
  s = catchStep(s, { near: false, free: true, moved: true }, 1 / 30);
  assert.ok(s.phase === 'escape' && s.track && s.face.surprised > 0);
  s = run(s, { near: false, free: true, moved: true }, CATCH.follow + 0.05);
  assert.ok(s.phase === 'back' && !s.track, 'her hand stops following');
  assert.ok(s.face.surprised > 0);
  s = run(run(null, here, 0.85), here, 1.0);
  s = catchStep(s, { near: true, free: false }, 1 / 30);
  assert.equal(s.phase, 'back');
  // never while she is busy
  assert.equal(run(null, { near: true, free: false }, 3).phase, 'off');
});

test('within reach is beside her at arm height, and her hand stops short of the pointer', () => {
  assert.ok(inReach([0.25, 0], 0.3));
  assert.ok(!inReach([0.04, -0.2], 0.3), 'over her body');
  assert.ok(!inReach([0.6, 0], 0.3), 'too far');
  assert.ok(!inReach([0.2, 0.4], 0.3), 'above her head');
  const [x, y] = reachPoint([0, 0], [0.2, 0], 0.3);
  assert.ok(Math.abs(x - (0.2 - CATCH.short)) < 1e-9 && y === 0);
  assert.ok(Math.abs(Math.hypot(...reachPoint([0, 0], [0.3, 0.3], 0.3)) - 0.92 * 0.3) < 1e-9, 'never past her arm');
});

test('brushing a speck off her sleeve: look, lift the arm, two strokes toward the wrist, the brushing arm down first', () => {
  const at = t => gesture('brushSleeve', t, 1);
  assert.ok(at(0.3).weights.head > at(0.3).weights.leftUpperArm, 'eyes and head first, then the arm comes up');
  assert.ok(at(1.0).weights.leftUpperArm > 0.9 && at(1.0).ik.weight > 0.3 && at(1.0).ik.weight < 0.95, 'the other hand on its way');
  assert.equal(at(1.0).ik.hand, 'right');
  assert.equal(gesture('brushSleeve', 1, -1).ik.hand, 'left');
  // strokes: out along the sleeve, back a little (lifted), out again, shorter
  const a1 = at(1.25).ik.along, b1 = at(1.55).ik.along, a2 = at(1.8).ik.along, b2 = at(2.05).ik.along;
  assert.ok(b1 - a1 > 0.5 && a2 < b1 && b2 > a2 && b2 - a2 < b1 - a1);
  assert.ok(at(1.67).ik.above > at(1.4).ik.above, 'lifted off between strokes');
  assert.ok(at(2.6).ik.weights.UpperArm < 0.1 && at(2.6).weights.leftUpperArm > 0.9, 'the brushing arm goes down first');
  assert.ok(at(3.2).weights.head > at(3.2).weights.leftUpperArm, 'her head comes up last');
  for (let t = 0; t < GESTURES.brushSleeve; t += 1 / 30) {
    const g = at(t);
    assert.ok(g.ik.along >= 0 && g.ik.along <= 1 && g.ik.above > 0, 'on the sleeve, never inside it');
  }
  // broken off, the brushing hand lets go with its arm
  const cut = cutShort(at(1.4), 'brushSleeve', 0.4);
  assert.ok(cut.ik.weights.UpperArm < 0.6);
  // only standing: not sitting on the floor or on a window
  assert.ok(!SEATED_FIDGETS.includes('brushSleeve') && !PERCHED_FIDGETS.includes('brushSleeve'));
  assert.equal(IDLE.brushSleeve.every, 480);
});

test('after a longer walk she finished, one fuller breath: chest first, head last, and her own breath holds back', () => {
  const trip = { trip: true, cut: false, then: null, hide: undefined };
  assert.ok(settles(trip, 5));
  assert.ok(!settles(trip, 2), 'a short walk');
  assert.ok(!settles({ ...trip, cut: true }, 5), 'stopped by you');
  assert.ok(!settles({ ...trip, then: 0 }, 5), 'jumping up onto a window next');
  assert.ok(!settles({ ...trip, hide: 'in' }, 5), 'going behind a window');
  assert.ok(!settles({ side: 1 }, 5), 'a stroll in her box');
  const b = s => settleBreath(s).bones;
  assert.ok(b(0.6).leftShoulder[2] > 0 && b(0.6).rightShoulder[2] < 0, 'shoulders rise on the in-breath');
  const how = (s, bone, most) => Math.abs(b(s)[bone][0]) / most;     // how far along each part is
  assert.ok(how(0.45, 'chest', 0.045) > how(0.45, 'spine', 0.02) && how(0.45, 'spine', 0.02) > how(0.45, 'head', 0.03),
            'the chest opens first, the spine after it, her head last');
  assert.ok(b(1.4).leftUpperArm[2] > 0.02 && b(1.4).rightUpperArm[2] < -0.02, 'arms ease away from her sides');
  assert.ok(settleBreath(1).idle < 0.3 && settleBreath(SETTLE.length - 0.01).idle > 0.95);
  assert.deepEqual(settleBreath(SETTLE.length), { bones: {}, idle: 1 });
  for (let s = 0; s < SETTLE.length; s += 0.05)
    for (const v of Object.values(b(s))) assert.ok(v.every(x => Math.abs(x) <= 0.05), 'mild');
  for (const v of Object.values(b(SETTLE.length - 0.01))) assert.ok(v.every(x => Math.abs(x) < 0.005), 'nothing left over');
});

test('clicked, she gives a little backward, her head trailing; then forward, curious, and a small tilt', () => {
  assert.ok(tapMotion(0.08).bones?.chest[0] < -0.03 && tapMotion(0.08).bones?.head[0] > tapMotion(0.15).bones?.head[0], 'chest gives, head trails');
  assert.ok(tapMotion(0.4).bones?.head[0] > 0.02, 'then a touch forward');
  assert.ok(tapMotion(0.5, 1).bones?.head[2] > 0.03 && tapMotion(0.5, -1).bones?.head[2] < -0.03);
  assert.deepEqual(tapMotion(TAP.length), {});
  assert.deepEqual(tapMotion(null), {});
  for (const v of Object.values(tapMotion(TAP.length - 0.01).bones)) assert.ok(v.every(x => Math.abs(x) < 0.005), 'settled');
  for (let s = 0; s < TAP.length; s += 0.02) assert.equal(tapMotion(s).bones?.leftUpperLeg, undefined, 'her legs stay');
});

test('one hand lets go while the other comes up, the same hand waits, and stopping mid-phrase lets go smoothly', () => {
  // a long phrase (point at 0.4, held to 5.0), a short pause, another with a stressed vowel early on
  const v = (a, b, stress = 0) => [a, b, 'aa', 0.8, stress];
  const plan = phrasePlan([v(0, 0.4), v(0.4, 0.6, 1), v(0.6, 5.0), [5.0, 5.2, null, 0, 0], v(5.2, 5.6), v(5.6, 5.8, 1), v(5.8, 7.0)]);
  assert.equal(plan.length, 2);
  assert.notEqual(plan[0].side, plan[1].side);
  const hand = plan[1].side === 1 ? 'right' : 'left';
  // the second hand gets ready (not suddenly up) while the first still lets go: no jump anywhere
  for (let t = 5.0; t < 6.5; t += 1 / 60) {
    const a = phraseGesture(plan, t).bones ?? {}, b = phraseGesture(plan, t + 1 / 60).bones ?? {};
    for (const bone of new Set([...Object.keys(a), ...Object.keys(b)]))
      for (let i = 0; i < 3; i++) assert.ok(Math.abs((a[bone]?.[i] || 0) - (b[bone]?.[i] || 0)) < 0.13, `${bone} jumps at ${t.toFixed(2)}`);   // The larger vowel beat stays below 0.13 rad per frame; the old pop was 0.5.
  }
  assert.ok(Math.abs(phraseGesture(plan, 5.5).bones[hand + 'UpperArm'][0]) < Math.abs(phraseGesture(plan, 5.75).bones[hand + 'UpperArm'][0]), 'it gets ready');
  // she stops speaking in the middle of the hold: let go from there, the wrist last, and over within the release
  const stopped = t => phraseGesture(plan, t, 2.0).bones ?? {};
  const other = plan[0].side === 1 ? 'right' : 'left';
  assert.ok(Math.abs(stopped(1.9)[other + 'UpperArm'][0]) > 0.15);
  assert.ok(Math.abs(stopped(2.3)[other + 'UpperArm'][0]) < Math.abs(stopped(1.9)[other + 'UpperArm'][0]));
  assert.deepEqual(stopped(2.0 + PHRASE.release + 0.01), {});
});

// Quiet details share the existing gesture release, but have their own physical eligibility.
for (const name of ['fingerFan', 'ankleEase', 'thoughtRelease']) {
  test(`${name}: eligibility, mirrored motion, smooth curves and interruption at any point`, () => {
    const ctx = name === 'ankleEase' ? { perched: {} } : {};
    assert.ok(detailFits(name, ctx));
    for (const key of ['walk', 'sit', 'jumping', 'hide', 'visit', 'carried'])
      assert.ok(!detailFits(name, { ...ctx, [key]: true }), key);
    assert.ok(!detailFits(name, { ...ctx, waiting: false }), 'speech, piano, duet, typing');
    assert.ok(!detailFits(name, name === 'ankleEase' ? {} : { perched: {} }));
    const length = GESTURES[name];
    assert.equal(gesture(name, -0.1), null);
    assert.equal(gesture(name, length), null);
    const values = g => [g.weight, g.eyes || 0, g.calm || 0, ...(g.look || []),
      ...Object.entries(g.bones).flatMap(([b, a]) => a.map(x => x * (g.weights?.[b] ?? g.weight))),
      ...Object.values(g.adds || {}).flatMap(a => a.map(x => x * g.weight)),
      ...Object.values(g.hands || {}).flatMap(h => [...h.curl, h.spread, h.thumb]),
      ...Object.values(g.face || {})];
    for (const hz of [30, 60, 144]) {
      for (let t = 0; t < length - 1 / hz; t += 1 / hz) {
        const a = values(gesture(name, t)), b = values(gesture(name, t + 1 / hz));
        assert.ok(a.every((x, i) => Number.isFinite(x) && Math.abs(x - b[i]) < 0.22), `continuous at ${t}`);
      }
    }
    for (let t = 0; t < length; t += 0.17) {
      const g = gesture(name, t), mirrored = gesture(name, t, -1);
      for (const [bone, a] of Object.entries(g.bones)) {
        const other = bone.replace(/^left/, 'right');
        assert.equal(mirrored.bones[other][0], a[0]);
        assert.equal(mirrored.bones[other][2], -a[2]);
      }
      for (const [bone, a] of Object.entries(g.adds || {})) {
        const other = bone.startsWith('left') ? bone.replace(/^left/, 'right') : bone.replace(/^right/, 'left');
        const b = mirrored.adds[other];
        assert.ok(Math.abs(a[0] - b[0]) < 1e-12 && Math.abs(a[1] + b[1]) < 1e-12 && Math.abs(a[2] + b[2]) < 1e-12, 'additive parts mirror too');
      }
      const cut = cutShort(g, name, 0);
      assert.deepEqual(cut.adds, g.adds, 'no pop when interrupted');
      for (const bone of Object.keys(g.bones)) assert.equal(cut.weights[bone], g.weights?.[bone] ?? g.weight);
      assert.equal(cutShort(g, name, CUT_S), null, 'never left running');
      assert.equal(cutShort(g, name, 0.13).eyes, 0, 'eyes reopen first');
    }
    for (const t of [0, length - 0.00001]) {
      const g = gesture(name, t);
      assert.ok(g.weight < 0.0001);
      for (const w of Object.values(g.weights || {})) assert.ok(w < 0.0001);
    }
  });
}

test('finger fan: eyes, shoulder, elbow, wrist, then each finger; wrist follows the lowering elbow', () => {
  const at = t => gesture('fingerFan', t);
  assert.ok(at(0.2).look[1] < -0.1 && at(0.2).weights.leftUpperArm === 0);
  const w = at(0.6).weights;
  assert.ok(w.leftShoulder > w.leftUpperArm && w.leftUpperArm > w.leftLowerArm && w.leftHand === 0);
  const opened = at(1.6).hands.left.curl.map((x, i) => (HANDS.relaxed.curl[i] - x) / (HANDS.relaxed.curl[i] - HANDS.splay.curl[i]));
  assert.ok(opened.every((x, i) => !i || opened[i - 1] > x));
  assert.ok(at(2.3).hands.left.spread > 0.9);
  assert.deepEqual(at(2).bones.leftUpperArm, [-0.45, -0.15, -1.1]);
  assert.deepEqual(at(2).bones.leftLowerArm, [0, -1.25, 0, -1.1]);
  assert.deepEqual(at(2).look, [0.3, -0.35]);
  assert.deepEqual(at(4.75).hands.left, HANDS.relaxed);
  assert.ok(at(4).weights.leftHand > at(4).weights.leftLowerArm);
  assert.ok(at(4).weights.leftLowerArm > at(4).weights.leftUpperArm);
});

test('ankle easing: swing settles, shin clears, two shrinking circles, toes settle before the shin', () => {
  const at = t => gesture('ankleEase', t);
  assert.ok(at(0.4).calm > 0.99 && at(0.4).adds.leftLowerLeg[0] === 0);
  assert.ok(at(0.95).adds.leftLowerLeg[0] < -0.2 && at(0.95).adds.leftFoot[0] === 0);
  let crossings = 0, last = 0;
  for (let t = 1.11; t < 3.5; t += 0.01) {
    const z = at(t).adds.leftFoot[2];
    if (last && Math.sign(last) !== Math.sign(z)) crossings++;
    last = z;
    assert.equal(at(t).adds.leftUpperLeg, undefined, 'thigh and seat stay');
  }
  assert.equal(crossings, 3, 'two full circles');
  assert.ok(Math.abs(at(3.5).adds.leftFoot[0]) < Math.abs(at(1.4).adds.leftFoot[0]));
  assert.ok(Math.abs(at(4.1).adds.leftFoot[0]) < 0.001 && Math.abs(at(4.1).adds.leftLowerLeg[0]) > 0.1);
  for (const perched of [{ low: true }, { corner: 1 }]) assert.ok(!detailFits('ankleEase', { perched }));
});

test('quiet details: idle thresholds, cooldowns, posture and recent history decide the picker', () => {
  const picks = ctx => new Set(Array.from({ length: 2000 }, (_, i) => chooseIdle(ctx, i / 2000, 0.2).gesture));
  assert.ok(picks({ idleFor: 30 }).has('fingerFan'));
  for (const ctx of [{ idleFor: 24 }, { idleFor: 30, seated: true }, { idleFor: 30, perched: true },
                     { idleFor: 30, recent: ['fingerFan'] }, { idleFor: 30, since: { fingerFan: 239 } }])
    assert.ok(!picks(ctx).has('fingerFan'));
  const edge = { perched: true, canCross: true, perchedFor: 25 };
  assert.ok(picks(edge).has('ankleEase'));
  for (const ctx of [{}, { ...edge, canCross: false }, { ...edge, perchedFor: 24 },
                     { ...edge, since: { ankleEase: 179 } }, { ...edge, recent: ['ankleEase'] }])
    assert.ok(!picks(ctx).has('ankleEase'));
  assert.ok(!picks({ idleFor: 600 }).has('thoughtRelease'), 'event only');
});

test('thought release: a long thought earns one quiet ending, never during speech or after a busy ending', () => {
  const step = (s, state, seconds, free = true) => thoughtStep(s, { state, free }, seconds);
  for (const hz of [30, 60, 144]) {
    let s = null;
    for (let i = 0; i < 7 * hz; i++) s = step(s, 'thinking', 1 / hz);
    assert.ok(s.earned && !s.fire);
    s = step(s, 'speaking', 10);
    assert.ok(s.earned && !s.fire);
    s = step(s, 'idle', 1 / hz);
    assert.ok(s.fire);
    assert.ok(!step(s, 'idle', 1).fire);
    assert.ok(!step(step(s, 'thinking', 7), 'idle', 0.1).fire, 'cooldown spans turns');
  }
  assert.ok(!step(step(null, 'thinking', 5.9), 'idle', 0.01).fire);
  assert.ok(step(step(null, 'thinking', 6), 'idle', 0.01).fire);
  let s = step(step(null, 'thinking', 7), 'idle', 0.1, false);
  assert.ok(!s.fire && !s.earned && !step(s, 'idle', 3).fire, 'busy event discarded');
  assert.ok(!step(step(step(null, 'thinking', 7), 'speaking', 61), 'idle', 0.1).fire, 'expires');
  assert.ok(!step(step(step(null, 'thinking', 7), 'listening', 1), 'idle', 0.1).fire, 'new input clears it');
  s = step(step(null, 'thinking', 7), 'idle', 0.1);
  s = step(s, 'idle', 61);
  assert.ok(step(step(s, 'thinking', 7), 'idle', 0.1).fire, 'can earn it again');
  const at = t => gesture('thoughtRelease', t);
  assert.ok(at(0.15).eyes > 0 && at(0.15).adds.head[0] === 0);
  assert.ok(at(0.5).adds.head[0] > 0 && at(0.5).adds.chest[0] === 0);
  assert.ok(at(1.4).eyes === 0 && at(1.4).adds.head[0] < 0 && at(1.4).face.happy > 0);
  assert.ok(at(2.3).adds.leftHand[0] > at(2.3).adds.chest[0], 'wrists settle last');
});

test('quiet details apply to the built-in figure even without shoulders, fingers or foot bones', async () => {
  const THREE = await import('./vendor/three.module.js');
  const { buildFigure } = await import('./figure.mjs');
  const rig = buildFigure(THREE);
  assert.equal(rig.node('leftShoulder'), null);
  for (const name of ['fingerFan', 'ankleEase', 'thoughtRelease']) {
    for (const side of [-1, 1]) {
      for (let t = 0; t < GESTURES[name]; t += 1 / 30) {
        const g = gesture(name, t, side), base = name === 'ankleEase' ? perchPose(1, 0).bones : poseFor('idle').bones;
        for (const bone of BONES) {
          const angles = base[bone].map((x, i) => x + (g.adds?.[bone]?.[i] || 0) * g.weight);
          rig.setBone(bone, withinLimits(bone, angles), g.bones[bone], g.weights?.[bone] ?? g.weight, 1, 1 / 30);
        }
        rig.setFingers?.(g.hands);
        rig.setBlink(g.eyes || 0);
        rig.look(...(g.look || [0, 0]));
        rig.update(1 / 30);
        rig.root.updateMatrixWorld(true);
        rig.root.traverse(node => assert.ok(node.matrixWorld.elements.every(Number.isFinite), name));
      }
    }
  }
});

test('arm releases keep the elbow folded until the upper arm is at least sixty percent down', () => {
  for (let t = 0; t <= 1; t += 0.005) {
    const r = armRelease(t, 1);
    assert.ok(r.UpperArm <= r.LowerArm && r.LowerArm <= r.Hand && r.Hand <= r.fingers);
    if (r.UpperArm > 0.4) assert.equal(r.LowerArm, 1);
  }
  assert.deepEqual(armRelease(-1, 1), { Shoulder: 1, UpperArm: 1, LowerArm: 1, Hand: 1, fingers: 1 });
  assert.ok(Object.values(armRelease(1, 1)).every(x => x === 0));
  for (const [name, start, duration, hand] of [
    ['tuckHair', 1.75, 1.2, 'right'], ['brace', 0.8, 1.05, 'right'], ['almostSneeze', 2.05, 1.5, 'right'],
    ['checkWrist', 2.6, 0.8, 'left'], ['brushSleeve', 2.65, 0.9, 'left'], ['fingerFan', 3.4, 1.35, 'left']]) {
    for (const side of [1, -1]) {
      const h = side === 1 ? hand : hand === 'right' ? 'left' : 'right';
      const held = gesture(name, start, side);
      for (let p = 0; p < 1; p += 0.025) {
        const g = gesture(name, start + p * duration, side);
        const upper = g.weights[h + 'UpperArm'] / held.weights[h + 'UpperArm'];
        const lower = g.weights[h + 'LowerArm'] / held.weights[h + 'LowerArm'];
        assert.ok(lower >= upper - 1e-9, name);
        if (upper > 0.4) assert.equal(lower, 1, name);
        assert.deepEqual(g.bones[h + 'LowerArm'], held.bones[h + 'LowerArm'], 'bend stays in the target');
      }
    }
  }
});

test('a face-level interruption clears forward before lowering without opening the elbow', () => {
  for (const name of ['tuckHair', 'almostSneeze', 'yawn']) for (const side of [1, -1]) {
    const g = gesture(name, 1.4, side), h = side === 1 ? 'right' : 'left';
    const cut = cutShort(g, name, 0.1);
    assert.ok(Math.abs(cut.bones[h + 'UpperArm'][0] - g.bones[h + 'UpperArm'][0] + 0.1) < 1e-9);
    assert.equal(cut.weights[h + 'LowerArm'], g.weights?.[h + 'LowerArm'] ?? g.weight);
    assert.deepEqual(cut.bones[h + 'LowerArm'], g.bones[h + 'LowerArm']);
    assert.deepEqual(cutShort(g, name, 0).bones, g.bones, 'no initial jump');
  }
});

test('hair tuck reaches forward without a wind-up or fist; brace protects the collarbone', () => {
  for (let t = 0; t < 0.9; t += 0.01) assert.ok(gesture('tuckHair', t).weight >= 0);
  const tuck = gesture('tuckHair', 1.4);
  assert.ok(tuck.bones.rightUpperArm[0] < -0.75 && tuck.bones.rightUpperArm[2] >= 0.75);
  assert.ok(tuck.hands.right.curl[0] < 0.25 && tuck.hands.right.curl[1] < 0.25);
  const brace = gesture('brace', 0.6);
  assert.ok(brace.bones.rightUpperArm[0] === -0.55 && brace.bones.rightUpperArm[1] >= 0.4);
  assert.equal(brace.bones.rightLowerArm[1], 1.7);
  assert.ok(brace.hands.right.spread >= 0.35);
});

test('sneeze breaths visibly lift the chin and both shoulders while the elbow stays low', () => {
  const first = gesture('almostSneeze', 0.9), second = gesture('almostSneeze', 1.3);
  assert.ok(Math.abs(first.bones.head[0] + 0.18) < 0.001);
  assert.ok(Math.abs(second.bones.head[0] + 0.25) < 0.001);
  assert.ok(second.eyes > first.eyes && second.bones.neck[0] > second.bones.head[0]);
  assert.equal(second.bones.leftShoulder[2], 0.05);
  assert.equal(second.bones.rightShoulder[2], -0.05);
  assert.equal(second.bones.rightUpperArm[2], 1.25);
  assert.equal(second.bones.rightLowerArm[1], 2.4);
});

test('sleeve and fan sit in front of her; the brushing elbow keeps its bend on release', () => {
  const sleeve = gesture('brushSleeve', 1.4), fan = gesture('fingerFan', 2);
  assert.deepEqual(sleeve.bones.leftUpperArm, [-0.35, -0.35, -1.25]);
  assert.equal(sleeve.bones.leftLowerArm[1], -1.35);
  assert.ok(fan.bones.leftUpperArm[0] === -0.45 && fan.bones.leftUpperArm[1] < 0 && fan.bones.leftHand[1] < 0);
  const release = gesture('brushSleeve', 2.35).ik.weights;
  assert.ok(release.UpperArm < 0.5 && release.LowerArm === 1);
});

test('tap has a visible shoulder hitch, surprise then smile; thought release breathes out visibly', () => {
  const tap = tapMotion(0.1);
  assert.equal(tap.bones.chest[0], -0.07);
  assert.equal(tap.bones.leftShoulder[2], 0.05);
  assert.equal(tap.bones.rightShoulder[2], -0.05);
  assert.equal(tap.face.surprised, 0.3);
  assert.ok(tapMotion(0.4).face.happy > 0 && tapMotion(0.4).face.surprised === 0);
  const thought = gesture('thoughtRelease', 1.4);
  assert.equal(thought.adds.leftShoulder[2], -0.06);
  assert.equal(thought.adds.chest[0], 0.04);
  assert.equal(thought.adds.head[2], 0.05);
  assert.ok(gesture('thoughtRelease', 2.2).face.happy >= 0.18);
});

test('phrase hands open finger by finger, turn up, and close after the elbow drops', () => {
  const plan = [{ start: 0, peak: 0.4, end: 2, side: 1 }];
  const opening = phraseGesture(plan, 0.2).hands.right.curl;
  const amount = opening.map((x, i) => (HANDS.relaxed.curl[i] - x) / (HANDS.relaxed.curl[i] - 0.12));
  assert.ok(amount.every((x, i) => !i || amount[i - 1] > x));
  const held = phraseGesture(plan, 1);
  assert.ok(held.bones.rightUpperArm[0] < -0.3 && held.bones.rightLowerArm[1] > 0.8);
  assert.equal(held.bones.rightHand[1], 0.3);
  assert.ok(phraseGesture(plan, 0.49).bones.rightLowerArm[1] > 1);
  const falling = phraseGesture(plan, 2.2);
  assert.ok(falling.bones.rightUpperArm[0] > held.bones.rightUpperArm[0]);
  assert.equal(falling.bones.rightLowerArm[1], held.bones.rightLowerArm[1]);
  assert.deepEqual(falling.hands.right, held.hands.right);
  assert.ok(phraseGesture(plan, 2.74).hands.right.curl[0] > 0.79);
  assert.deepEqual(phraseGesture(plan, 0.5, -1), {}, 'a cancelled future phrase never starts');
});

test('typing eyes step with each key, cap, and restart after a six-tenths pause', () => {
  assert.equal(typingEyeStep(1, 0), 0.015);
  assert.equal(typingEyeStep(10, 0.59), 0.15);
  assert.equal(typingEyeStep(100, 0.1), 0.25);
  assert.equal(typingEyeStep(10, 0.6), 0);
  assert.equal(typingEyeStep(10, null), 0);
  assert.equal(typingKeyCount(10, 0.59), 11);
  assert.equal(typingKeyCount(10, 0.6), 1);
  assert.equal(typingKeyCount(10, null), 1);
});


test('entries lead with the upper arm before folding the elbow, on either side', () => {
  for (const [name, end, hand] of [['tuckHair', 1, 'right'], ['brace', 0.6, 'right'],
    ['almostSneeze', 1, 'right'], ['brushSleeve', 1.3, 'left'], ['fingerFan', 1.3, 'left']]) {
    for (const side of [1, -1]) {
      const h = side === 1 ? hand : hand === 'left' ? 'right' : 'left';
      let leads = false;
      for (let t = 0; t < end; t += 0.01) {
        const g = gesture(name, t, side), upper = g.weights?.[h + 'UpperArm'] ?? g.weight;
        const lower = g.weights?.[h + 'LowerArm'] ?? g.weight;
        assert.ok(upper >= lower && lower >= 0, `${name} at ${t}`);
        leads ||= upper > lower;
        if (g.ik) assert.ok(g.ik.weights.UpperArm >= g.ik.weights.LowerArm);
      }
      assert.ok(leads, name);
    }
  }
  for (let t = 0; t < 1; t += 0.01) {
    const w = armEntry(t, 1);
    assert.ok(w.UpperArm >= w.LowerArm && w.LowerArm >= w.Hand);
    const c = catchStep({ phase: 'reach', t, since: 0, away: false }, { free: true }, 0);
    assert.ok(c.weights.UpperArm >= c.weights.LowerArm);
  }
  for (const side of [1, -1]) for (let t = 0; t <= 0.4; t += 0.01) {
    const h = side === 1 ? 'right' : 'left';
    const g = phraseGesture([{ start: 0, peak: 0.4, end: 2, side }], t);
    assert.ok(Math.abs(g.bones[h + 'UpperArm'][0]) / 0.35 + 1e-9 >= Math.abs(g.bones[h + 'LowerArm'][1]) / 0.9);
  }
});

test('sleeve target stays low and finger fan keeps its elbow open away from the face', () => {
  for (const side of [1, -1]) {
    const h = side === 1 ? 'left' : 'right';
    for (let t = 0; t < GESTURES.brushSleeve; t += 1 / 60) {
      const g = gesture('brushSleeve', t, side), arm = g.bones[h + 'UpperArm'];
      assert.ok(Math.abs(arm[0]) <= 0.35 && Math.abs(arm[2]) >= 1.25);
      assert.ok(Math.abs(g.bones[h + 'LowerArm'][1]) <= 1.35);
      assert.ok(g.ik.above > 0 && g.ik.above <= 0.051);
    }
    for (let t = 0; t < GESTURES.fingerFan; t += 1 / 60) {
      const g = gesture('fingerFan', t, side), arm = g.bones[h + 'UpperArm'];
      assert.ok(Math.abs(arm[0]) <= 0.45 && arm[2] * side === -1.1);
      assert.ok(Math.abs(g.bones[h + 'LowerArm'][1]) <= 1.25, 'open elbow preserves forward clearance');
      assert.ok(Math.abs(g.bones[h + 'Hand'][1]) === 0.8, 'fingers turn up clear of the chin');
    }
  }
});


test('finger fan holds a readable wider spread, then closes before the arm drops', () => {
  for (const side of [1, -1]) {
    const hand = side === 1 ? 'left' : 'right';
    for (const t of [1.9, 2.2, 2.6]) assert.ok(gesture('fingerFan', t, side).hands[hand].spread >= 1.59);
    assert.ok(gesture('fingerFan', 3.35, side).hands[hand].spread < 0.2);
    assert.deepEqual(gesture('fingerFan', 4.75, side).hands[hand], HANDS.relaxed);
  }
});
