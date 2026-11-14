// The avatar's decisions that need no 3D: poses, blinking, the mouth, where the orbiting props sit.
import test from 'node:test';
import assert from 'node:assert/strict';
import { STATES, BONES, GESTURES, FIDGETS, WALK, avatarState, poseFor, idleMotion, gesture, walkCycle, stroll, strollLength,
  talkMotion, visemes, saccade, chooseIdle, IDLE, SEATED_FIDGETS, sitting, sitPose, LEG, spring, gazeWander, withinLimits, ease, nextBlink, blinkWeight, mouthWeight, ringPosition,
  TRIP, planTrip, trip, tripLength, cutLeg, LEDGE_Y, perchPose, dangle, jump, jumpLength, planPerch,
  PERCHED_FIDGETS, PEEK, planHide, peekOut, headPastEdge, lookBlink, edgeSit, edgeSitLength } from './logic.mjs';

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
      const limit = name.includes('Arm') ? 1.6 : 0.6;
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
      for (const a of angles) assert.ok(Math.abs(a) <= 0.06);
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
  assert.ok(gesture('hop', 0.12).bones.leftLowerLeg[0] > 0.5 && gesture('hop', 0.12).lift === 0);   // crouched, still down
  const lifts = Array.from({ length: 75 }, (_, i) => gesture('hop', i * 0.01).lift);
  assert.ok(Math.max(...lifts) > 0.1 && Math.min(...lifts) >= 0);
  assert.equal(gesture('hop', 0.45).lift, 0);
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
test('blinks come every 2 to 6 seconds and last 150 ms', () => {
  assert.equal(nextBlink(10, 0), 12); assert.equal(nextBlink(10, 1), 16);
  assert.equal(blinkWeight(4.9, 5), 0); assert.equal(blinkWeight(5.075, 5), 1);
  assert.ok(blinkWeight(5.03, 5) > 0 && blinkWeight(5.03, 5) < 1); assert.equal(blinkWeight(5.2, 5), 0);
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
    assert.ok(length >= 2 && length <= 5, name);
    assert.ok(gesture(name, 0).weight === 0 && gesture(name, length - 0.001).weight < 0.01, name);
    assert.ok(gesture(name, length / 2).weight > 0.9 && gesture(name, length / 2).weight < 1.15, name);
    assert.equal(gesture(name, length), null);
    for (let t = 0; t < length; t += 0.1) {
      const g = gesture(name, t);
      assert.ok(g.lift >= 0 && g.lift < 0.03);
      for (const [bone, angles] of Object.entries(g.bones)) {
        assert.ok(BONES.includes(bone), `${name} ${bone}`);
        const most = name === 'stretch' && bone.includes('UpperArm') ? 3 : bone.includes('LowerArm') ? 2.5
          : bone.includes('Arm') ? 2 : 0.6;
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
  for (const name of ['shoulderRoll', 'hairTuck', 'tugJacket', 'think', 'smile', 'sigh', 'curious']) {
    assert.ok(FIDGETS.includes(name), name);
  }
  assert.ok(gesture('smile', GESTURES.smile / 2).face.happy > 0.3);                 // a small smile
  const think = gesture('think', GESTURES.think - 0.6);
  assert.ok(think.face.happy > 0.2);                                               // "got it": ends with a smile
  assert.ok(gesture('think', 1.5).bones.rightLowerArm[1] > 1.8);                    // hand up at her chin
  assert.ok(gesture('sigh', GESTURES.sigh * 0.7).face.relaxed > 0.3);
  const left = gesture('curious', 1.5, -1).look, right = gesture('curious', 1.5, 1).look;
  assert.ok(left[0] < -0.5 && right[0] > 0.5);                                      // looks toward a corner, either side
  const tuck = gesture('hairTuck', 1.3).bones;
  assert.ok(tuck.rightLowerArm[1] > 2 && tuck.rightUpperArm[3] < -0.8);               // forearm folded up toward her head
  // her hair goes back with her hand and stays tucked to the end (the page lets it slip forward later)
  assert.equal(gesture('hairTuck', 0.5).hair, 0);
  assert.ok(gesture('hairTuck', 1.1).hair > 0.2 && gesture('hairTuck', 1.1).hair < 0.9);
  assert.equal(gesture('hairTuck', GESTURES.hairTuck - 0.01).hair, 1);
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

test('on a window she does seated things and in time hops down; she only goes up when there is a window', () => {
  const picks = new Set();
  for (let i = 0; i < 300; i++) {
    const act = chooseIdle({ perched: true, perchedFor: 60, idleFor: 120 }, (i + 0.5) / 300, 0.3);
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
