// The avatar's decisions that need no 3D and no page: which pose a state means, how her whole body moves while
// idle, the one-off gestures (a wave, a hop), when she blinks, how far her mouth opens, where the things orbiting
// her are. avatar.js applies these to the model's bones; logic.test.mjs checks them.
//
// Angles are radians [x, y, z] on a figure that faces the viewer (+z) in a T-pose, her left arm along +x, applied
// in three.js' default order. So: x nods or swings forward (positive = head and spine forward; negative = an arm
// or thigh forward), y turns (and bends an elbow: negative for the left arm, positive for the right), z tilts
// (and lowers the arms: negative for the left, positive for the right). An optional fourth number is a twist
// about the bone's own length, applied before the others: it is what turns an upper arm so the elbow can bend
// upward, the way a real arm does when it waves. The built-in figure (figure.mjs) and a VRM's normalised bones
// (vrmrig.mjs) share this convention.

export const STATES = ['idle', 'listening', 'thinking', 'speaking'];

export const BONES = ['hips', 'spine', 'chest', 'neck', 'head',
  'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand',
  'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg'];

/** What she shows for the overlay's state. Awake with the microphone closed is "listening" for the orb, idle for her. */
export function avatarState(uiState, micOpen) {
  if (uiState === 'listening') return micOpen ? 'listening' : 'idle';
  return uiState === 'thinking' || uiState === 'speaking' ? uiState : 'idle';
}

// standing relaxed: the model comes in a T-pose, so the arms are brought down to her sides
const REST = {
  leftShoulder: [0, 0, -0.06], rightShoulder: [0, 0, 0.06],
  leftUpperArm: [0.06, 0, -1.3], rightUpperArm: [0.06, 0, 1.3],     // close to her sides, hanging a touch behind
  leftLowerArm: [0, -0.3, 0], rightLowerArm: [0, 0.3, 0],           // elbows never locked straight
  leftHand: [0.06, 0, -0.14], rightHand: [0.06, 0, 0.14],           // wrists hanging loose
};

// what each state changes from standing relaxed
const POSES = {
  idle: { bones: {}, expressions: {} },
  listening: {                                  // leans in, head tilted, hands brought a little forward
    bones: { spine: [0.09, 0, 0], neck: [0.04, 0, 0], head: [0.03, 0, 0.12],
             leftUpperArm: [-0.25, 0, -1.2], rightUpperArm: [-0.25, 0, 1.2],
             leftLowerArm: [0, -0.9, 0], rightLowerArm: [0, 0.9, 0] },
    expressions: {},
  },
  thinking: {                                   // looks up and aside, weight on one leg, a hand toward her chin
    bones: { hips: [0, 0, 0.05], spine: [0, 0, -0.05], neck: [-0.06, 0.08, 0], head: [-0.18, 0.22, -0.06],
             rightUpperArm: [-0.75, 0, 1.0], rightLowerArm: [0, 1.5, 0],
             leftUpperLeg: [0, 0, -0.05], rightUpperLeg: [-0.1, 0, -0.05], rightLowerLeg: [0.2, 0, 0] },
    expressions: {},
  },
  speaking: {                                   // open and relaxed: arms still down by her sides, elbows loose
    // (her hands used to come up in front of her thighs and pump back and forth, which looked awkward)
    bones: { spine: [0.02, 0, 0], head: [0.02, 0, 0],
             leftUpperArm: [0.03, 0, -1.24], rightUpperArm: [0.03, 0, 1.24],
             leftLowerArm: [0, -0.4, 0], rightLowerArm: [0, 0.4, 0] },
    expressions: { relaxed: 0.5 },
  },
};

const four = a => [a[0] || 0, a[1] || 0, a[2] || 0, a[3] || 0];

/** The whole-body pose for a state: every bone in BONES, plus expression weights. */
export function poseFor(state) {
  const p = POSES[state] || POSES.idle;
  const bones = {};
  for (const name of BONES) bones[name] = four(p.bones[name] || REST[name] || [0, 0, 0]);
  return { bones, expressions: { ...p.expressions } };
}

/** Which leg she stands on at time t, -1…1 (positive: her hip is out to one side and her right knee is loose).
 *  She settles onto a leg, stays there 6 to 12 seconds, then shifts: quickly, a little too far, and settles back.
 *  Sometimes she stays nearly even. Never the same twice in a row, and it doesn't repeat. */
export function weightShift(t) {
  const u = t / 9 + 0.35 * Math.sin(t * 0.19), k = Math.floor(u), f = u - k;
  const at = n => (hash(n * 1.7) < 0.5 ? -1 : 1) * (hash(n * 1.7) < 0.5 === hash(n * 1.7 - 1.7) < 0.5 ? 0.25 : 1) *
                  (0.55 + 0.45 * hash(n + 0.4));
  return at(k - 1) + (at(k) - at(k - 1)) * windUp(f / 0.17);
}

/** The small movement of her whole body while she just stands there, added on top of the pose. Nothing in it
 *  repeats exactly. She stands on one leg at a time (weightShift) with the other knee loose, and sways a little on
 *  top of that on two slow rhythms; each part of her follows the one below it a moment late (hips, then spine,
 *  chest, neck, head), so she never moves as one stiff block. Her shoulders tip against her hips, her legs lean
 *  against them so her feet stay where they are, her knees are never locked, and each arm hangs and drifts on a
 *  rhythm of its own with a loose wrist trailing it. */
export function idleMotion(t) {
  const wave = (period, late = 0) => Math.sin(2 * Math.PI * (t - late) / period);
  // `late`: seconds behind her hips
  const sway = late => 0.045 * weightShift(t - late) + 0.014 * wave(7.3, late) + 0.006 * wave(3.1, late - 0.5);
  // her breath isn't a metronome: its pace wanders (about 4 to 4.7 s), some breaths are deeper than others, and
  // breathing in is quicker than breathing out
  const breath = late => {
    const a = 2 * Math.PI * ((t - late) / 4.3 + 0.12 * Math.sin((t - late) * 0.17));
    return (0.8 + 0.2 * Math.sin(t * 0.091 + 1)) * Math.sin(a + 0.4 * Math.sin(a));
  };
  // standing on one leg turns her pelvis a little as well as tipping it; her chest turns back against it a moment
  // later, and her thighs turn back too so her feet keep pointing where they did
  const twist = late => 0.4 * sway(late);
  const drift = 0.03 * wave(11) + 0.012 * wave(4.7);
  const hips = sway(0), on = weightShift(t - 0.15);
  const knee = side => 0.05 + 0.11 * Math.max(0, side * on) + 0.008 * wave(5.9, side);     // the leg she isn't standing on
  const arm = (period, late) => 0.6 * sway(0.45 + late) + 0.012 * wave(period, late);
  const [armL, armR] = [arm(5.3, 0), arm(6.7, 1.9)];
  const [handL, handR] = [0.8 * sway(0.9) + 0.02 * wave(3.7, 0.4), 0.8 * sway(1.0) + 0.02 * wave(4.1, 2.2)];
  return {
    hips: [0, twist(0), hips], spine: [0.008 * breath(0.3), -0.4 * twist(0.12), -0.55 * sway(0.12)],
    chest: [0.018 * breath(0), -0.7 * twist(0.26), -0.45 * sway(0.26)],
    neck: [-0.006 * breath(0.6), 0.3 * drift, 0.15 * sway(0.42)],
    head: [0.008 * breath(0.8), 0.7 * drift, 0.3 * sway(0.6)],
    leftShoulder: [0, 0, -0.02 * breath(0.15) - 0.3 * sway(0.34)], rightShoulder: [0, 0, 0.02 * breath(0.15) - 0.3 * sway(0.34)],
    leftUpperLeg: [-0.5 * knee(-1), -twist(0), -hips], rightUpperLeg: [-0.5 * knee(1), -twist(0), -hips],
    leftLowerLeg: [knee(-1), 0, 0], rightLowerLeg: [knee(1), 0, 0],
    leftUpperArm: [armL, 0, -0.012 * breath(0.3)], rightUpperArm: [-armR, 0, 0.012 * breath(0.3)],
    leftLowerArm: [0, -0.9 * Math.abs(armL) - 0.02 * (1 + wave(8.3)), 0], rightLowerArm: [0, 0.9 * Math.abs(armR) + 0.02 * (1 + wave(9.7, 3)), 0],
    leftHand: [handL, 0, 0], rightHand: [-handR, 0, 0],
  };
}

/** How curled the fingers of each hand are at time t, as a share of their relaxed curl: { left, right }, each
 *  [index, middle, ring, little]. A hanging hand curls more toward the little finger, and it is never quite still:
 *  each hand closes and opens a little on a slow rhythm of its own, the fingers one after another. */
export function fingerCurl(t) {
  const hand = (p1, p2, late) => [0.8, 1, 1.15, 1.3].map((gain, i) =>
    gain * (1 + 0.14 * Math.sin(2 * Math.PI * (t - late - 0.12 * i) / p1) + 0.08 * Math.sin(2 * Math.PI * (t - late - 0.2 * i) / p2)));
  return { left: hand(7.9, 3.3, 0), right: hand(9.1, 2.9, 1.7) };
}

const smooth = x => x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x);
// The curves that make a movement look alive instead of mechanical:
/** 0 to 1 that starts gently, goes a little past 1 (8%) and settles back. It eases in: a curve that leaves at
 *  full speed makes a limb snap, which is what made the first wave look wrong. */
const overshoot = x => x <= 0 ? 0 : x >= 1 ? 1 : x < 0.7 ? 1.08 * smooth(x / 0.7) : 1 + 0.08 * (1 - smooth((x - 0.7) / 0.3));
/** The same, but it first dips a little the other way (winding up). */
const windUp = x => x <= 0 ? 0 : x < 0.15 ? -0.06 * Math.sin(Math.PI * x / 0.15) : overshoot((x - 0.15) / 0.85);

// ── walking ──

/** How she walks: `speed` in model units a second, `stepsPerS`, and `leg` (hip to ankle, measured on her model).
 *  The stride is worked out from them so a foot moves as far as her body does in a step: feet that swing further
 *  than she moves look like they are skating, which is what made the first walk look wrong. */
// a relaxed human stroll: about half her height a second, a little under two steps a second (at 0.3 units a
// second she walked in slow motion, and a walk across the screen took a quarter of a minute)
export const WALK = { speed: 0.45, stepsPerS: 1.85, leg: 0.44 };
const STRIDE = Math.asin(WALK.speed / WALK.stepsPerS / (2 * WALK.leg));     // thigh swing each way, radians

/** One moment of a walk, added on top of her pose: `phase` runs 2π per two steps. Legs swing against each
 *  other, each knee bends as its leg swings through, the arms swing gently against the legs, and her hips and chest
 *  turn a little against each other. `lift` is the small bob of her whole body: highest as a leg passes under her. */
export function walkCycle(phase) {
  const s = Math.sin(phase), c = Math.cos(phase);
  const a = STRIDE;
  return {
    lift: 0.008 * c * c,
    bones: {
      leftUpperLeg: [-a * s, 0, 0], rightUpperLeg: [a * s, 0, 0],
      // the knee bends while that foot is off the ground and swinging through, the most as it passes under her
      leftLowerLeg: [0.55 * Math.max(0, c) ** 1.5, 0, 0], rightLowerLeg: [0.55 * Math.max(0, -c) ** 1.5, 0, 0],
      leftUpperArm: [0.7 * a * s, 0, 0], rightUpperArm: [-0.7 * a * s, 0, 0],
      leftLowerArm: [0, -0.12 - 0.12 * Math.max(0, -Math.sin(phase - 0.5)), 0],
      rightLowerArm: [0, 0.12 + 0.12 * Math.max(0, Math.sin(phase - 0.5)), 0],
      leftHand: [0.1 * Math.sin(phase - 1.0), 0, 0], rightHand: [-0.1 * Math.sin(phase - 1.0), 0, 0],     // wrists trail the swing
      // her hips lead; spine, chest and head each turn against them a little later, and her head stays steady
      hips: [0, 0.05 * s, 0.02 * c], spine: [0.02, -0.035 * Math.sin(phase - 0.4), 0],
      chest: [0, -0.035 * Math.sin(phase - 0.8), -0.012 * Math.cos(phase - 0.8)],
      neck: [0, 0.015 * Math.sin(phase - 1.1), 0], head: [0.008 * Math.cos(2 * phase - 1.2), 0.02 * Math.sin(phase - 1.4), 0],
    },
  };
}

const TURN_S = 0.45, WALK_SPEED = WALK.speed, STEPS_PER_S = WALK.stepsPerS, SIDE_ON = 1.25;    // seconds, units/s, steps/s, radians
const RAMP_S = 0.4;                     // she takes this long to get up to walking speed, and to come to a stop

/** How long one leg of a stroll (`reach` one way) takes: she gets up to speed, walks, and slows to a stop. */
export const legLength = reach => reach / WALK_SPEED + RAMP_S;
/** How far into one leg she is after `u` seconds, in seconds' worth of walking at full speed. Her speed rises
 *  and falls on a smooth curve, so she never starts or stops moving at full speed. */
function legDistance(u, leg) {
  const start = x => { const X = Math.max(0, Math.min(1, x / RAMP_S)); return RAMP_S * (X ** 3 - X ** 4 / 2); };
  if (u <= RAMP_S) return start(u);
  if (u < leg - RAMP_S) return RAMP_S / 2 + (u - RAMP_S);
  return (leg - RAMP_S) - start(leg - u);
}
/** 0…1: how fast she is going along a leg, as a share of walking speed. */
const legSpeed = (u, leg) => smooth(u / RAMP_S) * smooth((leg - u) / RAMP_S);

/** Walking a leg of `leg` seconds, `u` seconds in: sets out.speed, out.amount and out.accel, and returns how far
 *  she has got (in seconds' worth of walking at full speed). */
function alongLeg(u, leg, out) {
  const e = 0.005;
  out.speed = out.amount = legSpeed(u, leg);
  out.accel = (legSpeed(u + e, leg) - legSpeed(u - e, leg)) / (2 * e);
  return legDistance(u, leg);
}

const PEEK_S = 2.2;                      // a pause at the far end: she looks out past the edge, then glances back

/** How long a stroll that goes `reach` to one side and back takes (longer when she pauses at the edge). */
export function strollLength(reach, peek = false) {
  return reach > 0.02 ? 4 * TURN_S + 2 * legLength(reach) + (peek ? PEEK_S : 0) : 0;
}

/** A short walk: she turns to one side (side = 1 or -1), walks `reach` that way, maybe pauses there (`peek`),
 *  turns round, walks back and faces front again. At `t` seconds in, or null when it is over (or there is no room):
 *    x, yaw     where she is and which way she faces (her body turns smoothly, never snaps)
 *    amount     how much of the walk cycle shows, 0…1;  phase  of the walk cycle, following the distance covered
 *    speed      0…1 of walking speed;  accel  how fast that changes (per second): negative while she slows down
 *    ahead      how far her body still has to turn: her head gets there first
 *    peek       0…1 while she stands at the edge looking out;  glance  0…1 as she looks back at you before turning */
export function stroll(t, reach, side = 1, peek = false) {
  const total = strollLength(reach, peek);
  if (!total || t < 0 || t >= total) return null;
  const leg = legLength(reach), full = legDistance(leg, leg), P = peek ? PEEK_S : 0;
  const marks = [TURN_S, TURN_S + leg, TURN_S + leg + P, 3 * TURN_S + leg + P, 3 * TURN_S + 2 * leg + P];
  const out = { amount: 0, speed: 0, accel: 0, ahead: 0, peek: 0, glance: 0 };
  const along = u => alongLeg(u, leg, out);
  let x, yaw, walked;
  if (t < marks[0]) {                                   // turning to the side
    yaw = SIDE_ON * smooth(t / TURN_S);
    [x, walked, out.ahead] = [0, 0, SIDE_ON - yaw];
  } else if (t < marks[1]) {                            // out
    walked = along(t - marks[0]);
    [x, yaw] = [WALK_SPEED * walked, SIDE_ON];
  } else if (t < marks[2]) {                            // at the edge: looking out past it, then back at you
    const u = t - marks[1];
    [x, yaw, walked] = [reach, SIDE_ON, full];
    out.peek = smooth(u / 0.5) * smooth((P - u) / 0.5);
    out.glance = smooth((u - 0.55 * P) / 0.35) * smooth((P - u) / 0.3);
  } else if (t < marks[3]) {                            // turning round, through facing the viewer
    yaw = SIDE_ON * (1 - 2 * smooth((t - marks[2]) / (2 * TURN_S)));
    [x, walked, out.ahead] = [reach, full, -SIDE_ON - yaw];
  } else if (t < marks[4]) {                            // back
    const d = along(t - marks[3]);
    [x, yaw, walked] = [reach - WALK_SPEED * d, -SIDE_ON, full + d];
  } else {                                              // facing front again
    yaw = -SIDE_ON * (1 - smooth((t - marks[4]) / TURN_S));
    [x, walked, out.ahead] = [0, 2 * full, -yaw];
  }
  return { ...out, x: side * x, yaw: side * yaw, ahead: side * out.ahead, phase: Math.PI * STEPS_PER_S * walked };
}

// ── walking across the screen ──
// With the overlay telling her how much screen there is on each side, a stroll is a trip: she walks somewhere
// else on the screen and stays there (the overlay's window travels with her steps). Without it (or with no room),
// she strolls inside her box and back.

/** The shortest trip, and her distance from the screen's edge at which she counts as there (units). */
export const TRIP = { min: 0.35, max: 1.4 };     // units: about 600 px at most, a few seconds of walking

/** How long a trip with a leg of `leg` seconds takes: turn, walk, maybe look out over the edge, face you again. */
export function tripLength(leg, peek = false) {
  return leg > 0 ? 2 * TURN_S + leg + (peek ? PEEK_S : 0) : 0;
}

/** Where a trip goes, from how far she can go each way ({ left, right }, units) and two random numbers 0…1:
 *  { side, leg (seconds), peek }, or null when there is no room either way. The side with more room is the
 *  likelier one, so she drifts back toward the middle; about one trip in three goes all the way to the edge, and
 *  there she pauses and looks out past it. */
export function planTrip(room, r1, r2) {
  const sides = [[-1, Math.max(0, room?.left || 0)], [1, Math.max(0, room?.right || 0)]].filter(([, r]) => r >= TRIP.min);
  // (a far edge is out of reach for one walk: she goes part of the way, and the edge itself only when it is near)
  if (!sides.length) return null;
  const total = sides.reduce((sum, [, r]) => sum + r, 0);
  const [side, r] = sides.length === 2 && r1 * total >= sides[0][1] ? sides[1] : sides[0];
  const toEdge = r2 < 0.35 && r <= TRIP.max;
  const reach = Math.min(r, TRIP.max);
  const dist = toEdge ? r : TRIP.min + (reach - TRIP.min) * 0.9 * Math.max(0, r2 - 0.35) / 0.65;
  return { side, leg: legLength(dist), peek: toEdge };
}

/** A trip `t` seconds in: she turns toward `side`, walks a leg of `leg` seconds, maybe pauses looking out past the
 *  edge (`peek`, glancing back at you at the end), and turns to face you again where she is. The same fields as
 *  stroll(), with x how far she has gone (signed); null once it is over. */
export function trip(t, leg, side = 1, peek = false) {
  const total = tripLength(leg, peek);
  if (!total || t < 0 || t >= total) return null;
  const full = legDistance(leg, leg), P = peek ? PEEK_S : 0;
  const marks = [TURN_S, TURN_S + leg, TURN_S + leg + P];
  const out = { amount: 0, speed: 0, accel: 0, ahead: 0, peek: 0, glance: 0 };
  let yaw, walked, step = 0;
  // turning, she takes a small step round (both feet staying planted while her body pivots reads as sliding)
  const turnStep = u => { out.amount = 0.5 * Math.sin(Math.PI * Math.min(1, Math.max(0, u))); return Math.PI * smooth(u); };
  if (t < marks[0]) {                                   // turning to the side
    yaw = SIDE_ON * smooth(t / TURN_S);
    [walked, out.ahead] = [0, SIDE_ON - yaw];
    step = turnStep(t / TURN_S);
  } else if (t < marks[1]) {                            // walking
    step = Math.PI;
    [walked, yaw] = [alongLeg(t - marks[0], leg, out), SIDE_ON];
  } else if (t < marks[2]) {                            // at the edge: looking out past it, then back at you
    const u = t - marks[1];
    [walked, yaw, step] = [full, SIDE_ON, Math.PI];
    out.peek = smooth(u / 0.5) * smooth((P - u) / 0.5);
    out.glance = smooth((u - 0.55 * P) / 0.35) * smooth((P - u) / 0.3);
  } else {                                              // facing you again
    yaw = SIDE_ON * (1 - smooth((t - marks[2]) / TURN_S));
    [walked, out.ahead] = [full, -yaw];
    step = Math.PI + turnStep((t - marks[2]) / TURN_S);
  }
  return { ...out, x: side * WALK_SPEED * walked, yaw: side * yaw, ahead: side * out.ahead,
    phase: Math.PI * STEPS_PER_S * walked + step };
}

/** Something happened `u` seconds into a trip with a leg of `leg` seconds: the shorter leg that has her slow down
 *  from right where she is, with no jump in where she is or how fast she goes (unchanged once she is already
 *  slowing down or has arrived). */
export function cutLeg(leg, u) {
  const w = u - TURN_S;
  if (w >= leg - RAMP_S) return leg;
  return Math.max(2 * RAMP_S, w + RAMP_S);
}

// ── springs and wandering eyes ──

/** One step of a damped spring pulling `x` (moving at `v`) toward `target`: [x, v]. `freq` is how quickly it
 *  swings (Hz) and `zeta` how damped it is: below 1 it overshoots a little and settles (follow-through, the lean
 *  as she stops), 1 gets there as fast as it can without overshooting. */
export function spring(x, v, target, dt, freq = 2, zeta = 0.5) {
  const w = 2 * Math.PI * freq, n = Math.max(1, Math.ceil(dt * 240)), h = dt / n;
  for (let i = 0; i < n; i++) {                         // small steps: stable whatever the frame rate
    // implicit in the spring: unconditionally stable, and with zeta 1 it never overshoots
    const vNext = (v - h * w * w * (x - target)) / (1 + 2 * zeta * w * h + h * h * w * w);
    x += h * vNext;
    v = vNext;
  }
  return [x, v];
}

// places on the screen her eyes wander to when nobody is moving the mouse: the corners, the edges, something just
// below the middle, and now and then you (0, 0). In the same -1…1 as the mouse.
const GAZE = [[0, 0], [0.85, 0.65], [-0.85, 0.65], [0.85, -0.55], [-0.85, -0.55], [0.45, 0.8], [-0.45, 0.8],
              [0.3, -0.15], [-0.35, -0.1], [0, 0.5], [0.7, 0.1], [-0.7, 0.1]];
const hash = n => { const v = Math.sin(n * 91.345 + 47.853) * 43758.5453; return v - Math.floor(v); };

/** Where her eyes wander at time t, [x, y]: one place held for a few seconds (not always as long), then another. */
export function gazeWander(t) {
  const k = Math.floor(t / 2.8 + 0.5 * Math.sin(t * 0.23));
  const [x, y] = GAZE[Math.floor(hash(k) * GAZE.length) % GAZE.length];
  return [x + 0.08 * (hash(k + 0.3) * 2 - 1), y + 0.06 * (hash(k + 0.7) * 2 - 1)];
}

// ── sitting down ──

/** Her legs, measured on her model: hip height, thigh and shin length (model units). */
export const LEG = { hip: 0.512, thigh: 0.207, shin: 0.234 };
// thighs well up and shins slanting forward, feet in front of her: that brings her bottom down onto the floor
// (with her shins upright she hovered in a squat)
const SIT_THIGH = -2.4, SIT_KNEE = 2.0;
const SIT = {                                    // on the floor hugging her knees
  hips: [0, 0, 0], spine: [0.22, 0, 0], chest: [0.08, 0, 0], neck: [-0.05, 0, 0], head: [-0.12, 0, 0],
  leftUpperLeg: [SIT_THIGH, 0, -0.1], rightUpperLeg: [SIT_THIGH, 0, 0.1], leftLowerLeg: [SIT_KNEE, 0, 0], rightLowerLeg: [SIT_KNEE, 0, 0],
  // arms wrapped round her shins: elbows beside her knees, forearms across the front of her shins below them, one
  // hand over the other wrist (fitted on her model to those points; with elbows bent further her hands floated
  // above her knees, held apart)
  leftUpperArm: [-0.6, -0.52, -0.8, 0.6], leftLowerArm: [0, -1.25, 0, 0], leftHand: [-0.15, 0.05, -0.4, 0],
  rightUpperArm: [-0.9, 0.75, 1.25, 0.6], rightLowerArm: [0, 1.03, 0, 0.38], rightHand: [0, -0.05, 0.25, 0.15],
};
const SIT_DOWN_S = 2.3, STAND_UP_S = 2.0, TURN_SIT_S = 0.55;   // seconds; the turn comes first (and last)

/** `base` (a pose, standing by default) folded `w` (0…1) of the way into sitting. */
export function sitPose(w, base = poseFor('idle')) {
  const bones = {};
  for (const name of BONES) {
    const from = base.bones[name], to = SIT[name] ? four(SIT[name]) : from;
    bones[name] = from.map((a, i) => a + (to[i] - a) * w);
  }
  return { bones, expressions: { ...base.expressions } };
}

/** Where her ankle is from her hip, [down, forward], with her legs folded `w` of the way. */
function ankleFrom(w) {
  const thigh = SIT_THIGH * w, shin = thigh + SIT_KNEE * w;
  return [LEG.thigh * Math.cos(thigh) + LEG.shin * Math.cos(shin), -LEG.thigh * Math.sin(thigh) - LEG.shin * Math.sin(shin)];
}

/** Sitting down `t` seconds after she began, standing up again from `standAt` (or null while she stays down):
 *  { w (how far folded, 0…1), turn (0…1 of the way to side-on), lift and back (how far her body drops and moves
 *  back), lean (forward, to get up) },
 *  or null once she is standing again. Her body drops and moves back exactly as far as her folding legs need,
 *  so her feet stay planted. `fold` forces w (for checking). */
export function sitting(t, standAt, fold) {
  // She turns side-on first and only then folds her legs; getting up, she unfolds and then turns back to you.
  // (Folding her knees up facing the viewer, her skirt rides up.)
  const down = u => smooth((u - TURN_SIT_S) / (SIT_DOWN_S - TURN_SIT_S)), turned = u => smooth(u / (TURN_SIT_S * 0.85));
  let w, lean = 0, turn;
  if (standAt != null && t >= standAt) {
    const unfold = STAND_UP_S - TURN_SIT_S, u = t - standAt;
    if (u >= STAND_UP_S) return null;
    const from = down(Math.min(standAt, SIT_DOWN_S));            // from however far down she got
    w = from * (1 - smooth(u / unfold));
    lean = from * 0.38 * Math.sin(Math.PI * Math.min(1, u / unfold * 1.15));   // weight forward over her feet
    turn = turned(Math.min(standAt, SIT_DOWN_S)) * (1 - smooth((u - unfold - 0.05) / (TURN_SIT_S * 0.85)));
  } else {
    [w, turn] = [down(t), turned(t)];
    lean = 0.12 * Math.sin(Math.PI * Math.min(1, Math.max(0, t - TURN_SIT_S) / (SIT_DOWN_S - TURN_SIT_S)));
  }
  if (fold != null) w = fold;
  const [drop, forward] = ankleFrom(w), [drop0, forward0] = ankleFrom(0);
  return { w, lean, turn, lift: drop - drop0, back: -(forward - forward0) };
}

// ── sitting on top of a window ──

/** How high the underside of her thighs is when she sits on an edge (units above her feet when standing): the
 *  window's top edge goes there. */
export const LEDGE_Y = 0.47;
/** How far above that edge she reaches, sitting there (her head and its ribbons; measured on her model): the
 *  room a window needs above it for her to sit on it. */
export const PERCH_HEADROOM = 0.48;
const LEDGE = {                                  // on the edge facing you: thighs out over it, legs hanging down
  spine: [0.08, 0, 0], chest: [0.03, 0, 0], neck: [-0.02, 0, 0], head: [-0.05, 0, 0],
  leftUpperLeg: [-1.5, 0, -0.07], rightUpperLeg: [-1.5, 0, 0.07], leftLowerLeg: [1.4, 0, 0], rightLowerLeg: [1.4, 0, 0],
  // hands in her lap, one over the other, keeping her skirt down (fitted on her model)
  leftUpperArm: [0.38, -0.23, -1.32, 0.12], leftLowerArm: [0, -1.76, 0, -0.04], leftHand: [-0.04, 0.26, -0.53, 0.15],
  rightUpperArm: [0.34, 0.07, 1.19, 0.27], rightLowerArm: [0, 1.83, 0, 0.65], rightHand: [0.08, 0.35, 0.19, 0.6],
};
/** How far she turns from facing you while she sits on an edge (radians; her head and eyes turn back to you).
 *  Square on, her skirt flips up at the front with her thighs level; a little turned, her near thigh hides it. */
export const PERCH_YAW = 0.45;
const CROUCH = {                                 // knees bent to jump or to land (feet under her hips)
  spine: [0.3, 0, 0], head: [-0.15, 0, 0],
  leftUpperLeg: [-0.5, 0, 0], rightUpperLeg: [-0.5, 0, 0], leftLowerLeg: [1.0, 0, 0], rightLowerLeg: [1.0, 0, 0],
  leftUpperArm: [0.55, 0, -1.25], rightUpperArm: [0.55, 0, 1.25],     // arms swung back, ready to throw forward
};
const CROUCH_DROP = (LEG.thigh + LEG.shin) * (1 - Math.cos(0.5));      // how far her body drops in that crouch

/** `base` with `ledge` (0…1) of sitting on an edge and `crouch` (0…1) of a crouch blended in: a pose and the lift
 *  (negative: lower) that keeps her feet on the ground while crouching. */
export function perchPose(ledge, crouch, base = poseFor('idle')) {
  const bones = {};
  for (const name of BONES) {
    let b = base.bones[name];
    if (LEDGE[name]) b = b.map((a, i) => a + (four(LEDGE[name])[i] - a) * ledge);
    if (CROUCH[name]) b = b.map((a, i) => a + (four(CROUCH[name])[i] - a) * crouch);
    bones[name] = b;
  }
  return { bones, expressions: { ...base.expressions }, lift: -CROUCH_DROP * crouch };
}

/** Her legs swinging now and then while she sits on an edge: a slow kick, one foot after the other. */
export function dangle(t) {
  const now = Math.max(0, Math.sin(t * 0.37) * Math.sin(t * 0.23 + 1));      // comes and goes
  const kick = 0.28 * now;
  return { leftLowerLeg: [kick * Math.sin(t * 2.4), 0, 0], rightLowerLeg: [kick * Math.sin(t * 2.4 + 2.2), 0, 0] };
}

const JUMP_PREP = 0.3, JUMP_LAND = 0.45;
const jumpFlight = dy => dy > 0 ? 0.4 + 0.2 * Math.sqrt(dy) : 0.3 + 0.25 * Math.sqrt(-dy);

/** How long a jump `dy` units up (onto an edge) or down (off it, to the floor) takes. */
export function jumpLength(dy) { return JUMP_PREP + jumpFlight(dy) + JUMP_LAND; }

/** A jump `t` seconds in: up onto an edge (dy > 0, from standing: crouch, spring up, legs tucking under her as she
 *  rises, land sitting with a small bounce) or down from one (dy < 0: lean and push off, drop, land in a crouch and
 *  stand up). { y (how far up she is, units), ledge, crouch (pose weights), lean (forward) }, or null once over.
 *  Her height follows one parabola, as a body in the air does. */
export function jump(t, dy) {
  const T = jumpFlight(dy), up = dy > 0;
  if (t < 0 || t >= JUMP_PREP + T + JUMP_LAND) return null;
  if (t < JUMP_PREP) {
    const p = smooth(t / JUMP_PREP);
    return up ? { y: 0, ledge: 0, crouch: p, lean: 0 } : { y: 0, ledge: 1, crouch: 0, lean: 0.25 * p };
  }
  if (t < JUMP_PREP + T) {
    // up: an arc that comes over the edge and down onto it; down: a fall from rest after a tiny push off (it
    // speeds up all the way, as falling does)
    const u = (t - JUMP_PREP) / T, hump = up ? 0.1 + 0.08 * dy : -dy / 4 + 0.05;
    const y = dy * u + hump * 4 * u * (1 - u);
    if (up) return { y, ledge: smooth((u - 0.25) / 0.6), crouch: 1 - smooth(u / 0.3), lean: 0.1 * (1 - u) };
    return { y, ledge: 1 - smooth(u / 0.5), crouch: smooth((u - 0.55) / 0.45), lean: 0.25 * (1 - smooth(u / 0.4)) };
  }
  const l = (t - JUMP_PREP - T) / JUMP_LAND;
  if (up) return { y: dy - 0.012 * Math.sin(Math.PI * l), ledge: 1, crouch: 0, lean: 0.06 * Math.sin(Math.PI * l) };
  return { y: dy, ledge: 0, crouch: 1 - smooth(l), lean: 0 };
}

/** Which seat to go to: `seats` are [{ x, half, y }] in pixels from the middle of the bottom of her box (x: the
 *  middle of a free stretch of a window's top edge, half: half its width, y: the edge, negative above). The
 *  nearest is likelier; on it, the spot nearest to her (keeping clear of the stretch's ends). `r` (0…1) picks.
 *  { dx, y } in pixels, or null when there is none. */
export function planPerch(seats, r, margin = 60) {
  // (a seat below her feet, `low`: the bottom panel's top edge; she sits down onto it where she stands)
  const ok = (seats || []).filter(s => s.half > margin && (s.y < 0 || s.low));
  if (!ok.length) return null;
  const weights = ok.map(s => 1 / (1 + Math.abs(s.x) / 300));
  let left = r * weights.reduce((a, b) => a + b, 0), pick = ok.at(-1);
  for (let i = 0; i < ok.length; i++) if ((left -= weights[i]) < 0) { pick = ok[i]; break; }
  const dx = Math.max(pick.x - pick.half + margin, Math.min(pick.x + pick.half - margin, 0));
  return { dx, y: pick.y };
}

// ── peeking out from behind an app ──
// She walks behind a window (the overlay cuts her picture where it covers her) until her middle is `inset` behind
// its side edge, faces you, and peeks out: a small side step toward the edge and a lean that bends her up from the
// hips, so her head and a shoulder come out past it; then she leans back in.

export const PEEK = { inset: 0.1, length: 4.2, step: 0.07 };
// how far each joint bends sideways at full lean (radians; her hips tip the other way), and the height of each
// joint above the floor on her model, for working out where her head ends up
const PEEK_LEAN = { hips: -0.06, spine: 0.15, chest: 0.17, neck: 0.15, head: 0.2 };
const PEEK_AT = { hips: 0.512, spine: 0.57, chest: 0.63, neck: 0.756, head: 0.798, top: 0.868 };

/** Which edge to peek out from: `edges` [{ id, x (units from her middle), out (-1 left edge, 1 right edge) }]; the
 *  nearer is likelier; `r` (0…1) picks. { id, dx (where her middle stops: just behind the edge), out } or null. */
export function planHide(edges, r) {
  const ok = (edges || []).filter(e => Number.isFinite(e?.x) && (e.out === 1 || e.out === -1));
  if (!ok.length) return null;
  const weights = ok.map(e => 1 / (1 + Math.abs(e.x)));
  let left = r * weights.reduce((a, b) => a + b, 0), pick = ok.at(-1);
  for (let i = 0; i < ok.length; i++) if ((left -= weights[i]) < 0) { pick = ok[i]; break; }
  return { id: pick.id, dx: pick.x - pick.out * PEEK.inset, out: pick.out };
}

/** How far her head moves toward the edge at full lean, side step included (units). */
export function headPastEdge(out = 1) {
  const names = ['hips', 'spine', 'chest', 'neck', 'head'], up = [...names.slice(1), 'top'];
  let bend = 0, x = PEEK.step;
  names.forEach((n, i) => { bend += PEEK_LEAN[n]; x += Math.sin(bend) * (PEEK_AT[up[i]] - PEEK_AT[n]); });
  return out * x;
}

/** The peek `t` seconds in, toward `out`: { bones (sideways bends, added to her pose), shift (units toward the
 *  edge), look, face, wave (true in about half the peeks, decided by `r`) } or null once it is over. */
export function peekOut(t, out = 1, r = 0) {
  if (t < 0 || t >= PEEK.length) return null;
  const w = smooth(t / 0.6) * smooth((PEEK.length - t) / 0.7);
  const bones = {};
  // (a positive sideways angle tips her toward her own right, the viewer's left: so toward `out` is -out)
  for (const [name, a] of Object.entries(PEEK_LEAN)) bones[name] = [0, 0, -out * a * w];
  bones.head = [0.05 * w, -0.25 * out * w, -out * PEEK_LEAN.head * w];     // her face turned back toward you
  return { bones, shift: out * PEEK.step * w, look: [0, 0], face: { happy: 0.35 * smooth((t - 0.9) / 0.5) * w },
           wave: r < 0.5 };
}

/** How long sitting down onto an edge below her (dy < 0, units) or getting up from it (dy > 0) takes. */
export function edgeSitLength(dy) { return 0.3 + 0.9 + 0.25 + 0 * dy; }

/** Sitting down onto an edge just below her feet (dy < 0: the top of the bottom panel), `t` seconds in: her knees
 *  bend, she lowers herself over the edge as her legs come forward, and settles; or getting up from it (dy > 0):
 *  she leans forward and pushes herself up to stand. { y (units, how far she has gone), ledge, crouch, lean } or
 *  null once it is over. */
export function edgeSit(t, dy) {
  const n = edgeSitLength(dy);
  if (t < 0 || t >= n) return null;
  const u = Math.min(1, Math.max(0, (t - 0.3) / 0.9)), p = smooth(t / 0.3), done = t >= 1.2;
  if (dy < 0) {
    if (t < 0.3) return { y: 0, ledge: 0, crouch: 0.5 * p, lean: 0.15 * p };
    if (!done) return { y: dy * smooth(u), ledge: smooth(u), crouch: 0.5 * (1 - smooth(u / 0.5)), lean: 0.15 * (1 - u) };
    return { y: dy, ledge: 1, crouch: 0, lean: 0.04 * Math.sin(Math.PI * (t - 1.2) / 0.25) };
  }
  if (t < 0.3) return { y: 0, ledge: 1, crouch: 0, lean: 0.25 * p };
  if (!done) return { y: dy * smooth(u), ledge: 1 - smooth(u), crouch: 0.4 * Math.sin(Math.PI * u), lean: 0.25 * (1 - smooth(u)) };
  return { y: dy, ledge: 0, crouch: 0, lean: 0 };
}

// ── while she talks ──

/** Small movements of her whole upper body in time with her own voice (`level` 0…1), added to the speaking pose.
 *  Most of it is in her head, chest and shoulders: she leans into the louder moments, tilts and nods. Her hands
 *  only make small beats down by her sides; big forearm swings read as pumping her arms, not as talking.
 *  All of it is zero in silence. */
export function talkMotion(t, level) {
  const a = Math.max(0, Math.min(1, level));
  const beat = (speed, late = 0) => 0.5 + 0.5 * Math.sin(t * speed + late);
  return {
    leftLowerArm: [0, -0.1 * a * beat(3.3), 0], rightLowerArm: [0, 0.14 * a * beat(2.9, 1), 0],
    leftUpperArm: [-0.02 * a, 0, 0.03 * a * Math.sin(t * 1.6)], rightUpperArm: [-0.03 * a, 0, 0.03 * a * Math.sin(t * 1.4 + 2)],
    leftHand: [0.05 * a * Math.sin(t * 3.3 - 0.9), 0, 0], rightHand: [0.06 * a * Math.sin(t * 2.9 + 0.1), 0, 0],
    leftShoulder: [0, 0, -0.04 * a * beat(2.6)], rightShoulder: [0, 0, 0.04 * a * beat(2.2, 2)],
    chest: [0.03 * a * beat(3.1), 0.03 * a * Math.sin(t * 1.3), 0], spine: [0.015 * a * beat(3.1, -0.5), 0, 0],
    neck: [0, 0, 0.03 * a * Math.sin(t * 1.7 - 0.4)],
    head: [0.035 * a * Math.sin(t * 6.3), 0.03 * a * Math.sin(t * 1.9), 0.06 * a * Math.sin(t * 1.7 - 0.8)],
  };
}

const VOWELS = [['aa', 3.1, 0], ['ih', 4.3, 1.3], ['ou', 2.3, 2.1], ['ee', 5.2, 0.4], ['oh', 3.7, 4.0]];

/** Which mouth shapes she makes while her mouth is `open` (0…1): the five vowel shapes take turns, one leading at
 *  a time, so she looks like she is forming words and not flapping one shape. All zero when her mouth is shut. */
export function visemes(t, open) {
  const o = Math.max(0, Math.min(1, open));
  const raw = VOWELS.map(([name, speed, late]) => [name, Math.max(0, Math.sin(t * speed + late)) ** 2 + (name === 'aa' ? 0.15 : 0)]);
  const top = Math.max(...raw.map(([, v]) => v));
  return Object.fromEntries(raw.map(([name, v]) => [name, o * (v / top) ** 2]));
}

/** A tiny jump of her eyes, [x, y], that holds for a moment and then jumps again: real eyes never rest still. */
export function saccade(t) {
  const k = Math.floor(t / 0.85 + 0.4 * Math.sin(t * 0.37));
  const rand = n => { const v = Math.sin(n * 127.1 + 311.7) * 43758.5453; return (v - Math.floor(v)) * 2 - 1; };
  return [0.06 * rand(k), 0.04 * rand(k + 0.5)];
}

// ── gestures: one-off movements ──

export const GESTURES = { wave: 2.8, hop: 0.75, stretch: 2.8, lookAround: 3.2, lean: 3.6, rock: 3.2,
  shoulderRoll: 2.8, tugJacket: 2.4, think: 3.8, smile: 2.6, sigh: 2.8, curious: 3.4,
  yawn: 3.6, checkWrist: 3.4, shakeOut: 2.6, sideStretch: 3.8, showCard: 4.6, umbrella: 16 };   // seconds
/** What she does now and then while idle, when nothing else is going on. */
export const FIDGETS = ['stretch', 'lookAround', 'lean', 'rock', 'shoulderRoll', 'tugJacket', 'think',
  'smile', 'sigh', 'curious', 'yawn', 'checkWrist', 'shakeOut', 'sideStretch', 'showCard', 'umbrella'];
/** What she does while sitting on the floor (her legs are busy, her arms around her knees). */
export const SEATED_FIDGETS = ['lookAround', 'curious', 'smile', 'sigh', 'shoulderRoll', 'yawn', 'standUp'];

/** Everything she may do of her own while idle, and how likely each is. `after`: only once she has been idle that
 *  many seconds (she sits down when she is bored). Standing up gets likelier the longer she sits. */
export const IDLE = {
  stroll: { weight: 2 }, stretch: { weight: 0.8 }, lookAround: { weight: 1.5 }, lean: { weight: 1.5 },
  rock: { weight: 0.8 }, shoulderRoll: { weight: 1 }, tugJacket: { weight: 0.8 },
  think: { weight: 1 }, smile: { weight: 1.2 }, sigh: { weight: 0.8 }, curious: { weight: 1.5 },
  yawn: { weight: 0.8, after: 30 }, checkWrist: { weight: 0.8 }, shakeOut: { weight: 0.8 }, sideStretch: { weight: 0.8 },
  sit: { weight: 2.5, after: 45 }, standUp: { weight: 0 },
  perch: { weight: 2, after: 15 }, hopDown: { weight: 0 }, hide: { weight: 1.5, after: 10 },
  showCard: { weight: 3, after: 8 },     // only with a test to show (canCard): the overlay sends it, she keeps the hour
  umbrella: { weight: 4, after: 5 },     // only with rain coming (canUmbrella), every 20 min at most
};
/** She sits on a window at least this long (seconds) before she may hop down of her own. */
export const PERCH_MIN_S = 90;
/** What she does while sitting on top of a window. */
export const PERCHED_FIDGETS = ['lookAround', 'curious', 'smile', 'sigh', 'shoulderRoll', 'think', 'yawn', 'checkWrist', 'hopDown'];

/** What she does next while idle. `recent`: the names of what she did last (never repeated straight away);
 *  `idleFor`: seconds with nothing going on; `seated`, `seatedFor`. Two random numbers 0…1 pick it. Returns
 *  { stroll: ±1, peek } | { gesture, side: ±1 } | { sit: true } | { stand: true } | { perch: true } | { hopDown: true }.
 *  `perched`: sitting on top of a window (for `perchedFor` s); `canPerch`: a window she could sit on is there;
 *  `canHide`: a window she could go behind and peek out from ({ hide: true }). */
export function chooseIdle({ recent = [], idleFor = 0, seated = false, seatedFor = 0, perched = false, perchedFor = 0,
                             canPerch = false, canHide = false, canCard = false, canUmbrella = false }, r1, r2) {
  const weightOf = name => {
    if (name === 'showCard' && !canCard) return 0;
    if (name === 'umbrella' && !canUmbrella) return 0;
    if (name === 'hopDown') return perched ? Math.min(3, Math.max(0, (perchedFor - PERCH_MIN_S) / 30)) : 0;
    if (perched) return PERCHED_FIDGETS.includes(name) ? IDLE[name].weight : 0;
    if (name === 'perch' && (!canPerch || seated)) return 0;
    if (name === 'hide' && (!canHide || seated)) return 0;
    if (name === 'standUp') return seated ? Math.min(4, Math.max(0, (seatedFor - 20) / 8)) : 0;
    if (seated) return SEATED_FIDGETS.includes(name) ? IDLE[name].weight : 0;
    return idleFor >= (IDLE[name].after || 0) ? IDLE[name].weight : 0;
  };
  let options = Object.keys(IDLE).map(name => [name, weightOf(name)]).filter(([, w]) => w > 0);
  const fresh = options.filter(([name]) => !recent.includes(name));
  if (fresh.length) options = fresh;
  const sum = options.reduce((a, [, w]) => a + w, 0);
  let pick = options.at(-1)[0];
  for (let left = r1 * sum, i = 0; i < options.length; i++) {
    left -= options[i][1];
    if (left < 0) { pick = options[i][0]; break; }
  }
  const frac = x => x - Math.floor(x);
  if (pick === 'stroll') return { stroll: r2 < 0.5 ? -1 : 1, peek: frac(r2 * 7) < 0.5 };
  if (pick === 'sit') return { sit: true, side: frac(r2 * 5) < 0.5 ? -1 : 1 };
  if (pick === 'standUp') return { stand: true };
  if (pick === 'perch') return { perch: true };
  if (pick === 'hopDown') return { hopDown: true };
  if (pick === 'hide') return { hide: true };
  return { gesture: pick, side: frac(r2 * 3) < 0.5 ? -1 : 1 };
}

/** A one-off movement at `t` seconds after it began: { weight, bones, lift, face?, look? } or null once it is over.
 *  `bones` replace the pose by `weight` (0…1); `lift` raises her whole body (in metres of the model); `face` is
 *  expression weights; `look` is where on the screen she looks meanwhile. `side` (±1) mirrors the ones that have
 *  a side. */
/** The same pose for her other side: left and right bones swapped, and turns and tilts the other way. */
function mirrorSide(bones, side) {
  if (side !== -1) return bones;
  const out = {};
  for (const [k, v] of Object.entries(bones)) {
    const other = k.startsWith('left') ? 'right' + k.slice(4) : k.startsWith('right') ? 'left' + k.slice(5) : k;
    out[other] = [v[0], -v[1], -v[2], ...v.slice(3)];
  }
  return out;
}

export function gesture(name, t, side = 1) {
  const length = GESTURES[name];
  if (!length || t < 0 || t >= length) return null;
  if (name === 'wave') {
    // A real wave: the elbow bends first, the shoulder lifts and the upper arm comes up beside her, turning so the
    // forearm can stand up; the forearm swings from the elbow with the hand trailing it. The arm winds up before it
    // rises, goes a little too far and settles; the swings die away, and on the way down the elbow stays bent
    // until the arm is nearly at her side (it never passes through sticking straight out).
    const rise = t / 0.85, fall = (t - (length - 0.75)) / 0.75;      // an unhurried lift: it used to snap up in 0.2 s
    // coming down, the arm lowers still turned and bent, and only untwists as it reaches her side: untwisting
    // while raised swings the bent forearm out at the viewer and leaves the arm sticking straight out sideways
    const raised = windUp(rise) * (1 - smooth(fall / 0.8));
    const turned = smooth(rise) * (1 - smooth((fall - 0.25) / 0.75));
    const bent = smooth(rise / 0.6) * (1 - smooth((fall - 0.4) / 0.6));
    const swing = smooth((t - 0.6) / 0.35) * smooth((length - 0.7 - t) / 0.4);
    const beat = 2 * Math.PI * 2.2 * (t - 0.6);
    return { weight: smooth(t / 0.12) * smooth((length - t) / 0.12), lift: 0,
             bones: { rightShoulder: [0, 0, 0.06 - 0.28 * raised],
                      // the elbow comes up to a little below her shoulder and forward, the forearm stands up: a
                      // friendly wave (lifting the arm out level with the shoulder looked stiff and took more room)
                      rightUpperArm: [0.06 * (1 - raised) - 0.25 * raised, 0.6 * raised, 1.3 - 0.8 * raised, -Math.PI / 2 * turned],
                      rightLowerArm: [0, 0.3 + 1.8 * bent + 0.35 * swing * Math.sin(beat), 0],
                      rightHand: [0.06, 0, 0.14 * (1 - bent) + 0.35 * swing * Math.sin(beat - 0.9)],
                      chest: [0, 0, 0.05 * raised], spine: [0, 0, 0.03 * raised], head: [0, 0, 0.09 * raised] } };
  }
  // into it with a small wind-up the other way, a touch too far, and settled; out of it gently, slowing all the way
  const inOut = windUp(t / 0.7) * (1 - (1 - smooth((length - t) / 0.6)) ** 2);
  if (name === 'stretch') {                      // both arms swung up in front of her and over her head, leaning back
    // Raised from hanging by swinging them forward, so they go up and come down in front of her. Raised out to
    // the sides (the first version) they came down through a T-pose, which read as a glitch, not a stretch.
    const reach = smooth(t / 1.0) * smooth((length - t) / 0.9);
    return { weight: reach, lift: 0.01 * reach,
             bones: { leftUpperArm: [-2.75, 0, -1.15], rightUpperArm: [-2.75, 0, 1.15],
                      leftLowerArm: [0, -0.3, 0], rightLowerArm: [0, 0.3, 0],
                      leftHand: [-0.2, 0, 0], rightHand: [-0.2, 0, 0],
                      spine: [-0.08, 0, 0], chest: [-0.08, 0, 0], head: [-0.15, 0, 0] } };
  }
  if (name === 'shoulderRoll') {                 // shoulders up and back down, then a slow neck stretch each way
    const up = Math.sin(Math.PI * smooth(t / 1.1)), tilt = Math.sin(2 * Math.PI * smooth((t - 0.9) / 1.6));
    return { weight: inOut, lift: 0,
             bones: { leftShoulder: [0, 0, -0.06 + 0.22 * up], rightShoulder: [0, 0, 0.06 - 0.22 * up],
                      chest: [-0.04 * up, 0, 0], neck: [0.03, 0, 0.14 * tilt * side], head: [0.05, 0, 0.2 * tilt * side] } };
  }
  if (name === 'yawn') {                         // a hand up to her mouth, head back, eyes shut... and she sags a little
    const up = windUp(t / 0.9) * (1 - smooth((t - (length - 1.0)) / 1.0));
    const wide = smooth((t - 0.7) / 0.6) * (1 - smooth((t - 2.3) / 0.5));       // the yawn itself
    const sag = smooth((t - 2.3) / 0.5) * smooth((length - t) / 0.6);
    return { weight: up, lift: 0.006 * wide,
             bones: mirrorSide({ rightShoulder: [0, 0, 0.06 - 0.1 * wide], leftShoulder: [0, 0, -0.06 + 0.08 * wide],
                      rightUpperArm: [-0.9, 0.6, 1.1], rightLowerArm: [0, 2.3, 0], rightHand: [-0.3, 0, 0.3],   // fitted: the back of her hand over her mouth
                      chest: [-0.1 * wide + 0.06 * sag, 0, 0], spine: [-0.04 * wide + 0.05 * sag, 0, 0],
                      neck: [-0.05 * wide + 0.05 * sag, 0, 0], head: [-0.1 * wide + 0.12 * sag, 0.12, -0.04] }, side),
             mouth: 0.85 * wide, eyes: smooth((t - 0.8) / 0.35) * (1 - smooth((t - 2.5) / 0.4)),
             face: { relaxed: 0.6 * sag } };
  }
  if (name === 'checkWrist') {                   // forearm up in front of her, a look down at her wrist, "oh", and down
    const up = windUp(t / 0.8) * (1 - smooth((t - (length - 0.8)) / 0.8));
    const read = smooth((t - 0.5) / 0.4) * (1 - smooth((t - 2.0) / 0.35));      // eyes and head down on it
    const oh = smooth((t - 2.0) / 0.25) * smooth((length - t) / 0.6);            // then up at you again
    return { weight: up, lift: 0,
             bones: mirrorSide({ leftShoulder: [0, 0, -0.1], leftUpperArm: [-0.5, 0, -1.12], leftLowerArm: [0, -1.65, 0],
                      leftHand: [0, 0.3 * read, -0.1],
                      spine: [0.04 * read, 0, 0], chest: [0.04 * read, 0.06 * read, 0],
                      neck: [0.1 * read, 0.08 * read, 0], head: [0.24 * read - 0.05 * oh, 0.16 * read, 0.06 * oh] }, side),
             look: [0.3 * side * read, -0.7 * read + 0.05 * oh], face: { happy: 0.35 * oh } };
  }
  if (name === 'shakeOut') {                     // loosens up: shoulders up and dropped, hands shaken out at her sides
    const on = smooth(t / 0.4) * smooth((length - t) / 0.5);
    const shrug = Math.sin(Math.PI * smooth(t / 0.9));
    const loose = smooth((t - 0.6) / 0.3) * Math.exp(-1.4 * Math.max(0, t - 0.9));     // dies away, like a real shake
    const flap = (speed, late) => loose * Math.sin(2 * Math.PI * speed * t + late);
    return { weight: on, lift: 0.006 * shrug,
             bones: { leftShoulder: [0, 0, -0.06 + 0.2 * shrug], rightShoulder: [0, 0, 0.06 - 0.2 * shrug],
                      leftUpperArm: [0.06 + 0.05 * flap(2.6, 0), 0, -1.22], rightUpperArm: [0.06 + 0.05 * flap(2.3, 1.1), 0, 1.22],
                      leftLowerArm: [0, -0.55 - 0.18 * flap(5.3, 0.6), 0], rightLowerArm: [0, 0.55 + 0.18 * flap(4.7, 2.0), 0],
                      leftHand: [0.4 * flap(5.3, -0.5), 0, -0.14], rightHand: [0.4 * flap(4.7, 0.9), 0, 0.14],
                      chest: [-0.04 * shrug, 0.03 * flap(2.6, 0), 0], neck: [0, 0, 0.05 * flap(1.3, 0)],
                      head: [0.04 * shrug, 0, 0.1 * flap(1.3, -0.5)] } };
  }
  if (name === 'sideStretch') {                  // one arm up over her head, leaning away from it, hip out the other way
    const reach = windUp(t / 1.2) * (1 - (1 - smooth((length - t) / 1.0)) ** 2);
    const lean = smooth((t - 0.7) / 0.9) * smooth((length - 0.6 - t) / 0.8);
    return { weight: reach, lift: 0.006 * Math.max(0, lean),
             bones: mirrorSide({ rightUpperArm: [-2.75, 0, 1.15], rightLowerArm: [0, 0.45, 0], rightHand: [-0.2, 0, 0],
                      rightShoulder: [0, 0, -0.1],
                      hips: [0, 0, 0.1 * lean], spine: [0, 0, -0.22 * lean], chest: [0, 0, -0.22 * lean],
                      neck: [0, 0, -0.06 * lean], head: [-0.05, 0, -0.12 * lean],
                      leftUpperLeg: [0, 0, -0.1 * lean], rightUpperLeg: [0, 0, -0.1 * lean] }, side),
             face: { relaxed: 0.5 * Math.max(0, lean) } };
  }
  if (name === 'showCard') {                     // a test coming up: she holds up a card with it, and looks at you
    const hold = smooth(t / 0.7) * smooth((length - t) / 0.7);
    const card = smooth((t - 0.25) / 0.65) * smooth((4.4 - t) / 0.7);
    return { weight: hold, lift: 0, card,
             // fitted on her model: hands a card's width apart at the height of her chest, in front of her; they hold
             // the card's bottom edge, so it stands up above them to below her chin (avatar.js placeCard)
             bones: { leftUpperArm: [-0.2, 0.075, -1.15, 0.225], rightUpperArm: [-0.125, 0.075, 1.15, 0.075],
                      leftLowerArm: [0, -1.566, 0], rightLowerArm: [0, 1.491, 0],
                      leftHand: [0, 0, 0], rightHand: [0, 0, 0],
                      chest: [0.04, 0, 0], head: [0.04, 0, 0.1] },
             look: [0, 0.05], face: { happy: 0.6 * hold } };
  }
  if (name === 'umbrella') {                     // rain coming: an umbrella from behind her back, snapped open
    return umbrellaMotion(t, length);
  }
  if (name === 'tugJacket') {                    // looks down and straightens her jacket with two small tugs
    const tug = Math.max(0, Math.sin(2 * Math.PI * (t - 0.7) / 0.55)) * smooth((t - 0.6) / 0.2) * smooth((1.9 - t) / 0.2);
    return { weight: inOut, lift: 0,
             bones: { leftUpperArm: [-0.32 + 0.1 * tug, 0, -1.2], rightUpperArm: [-0.32 + 0.1 * tug, 0, 1.2],
                      leftLowerArm: [0, -1.25, 0], rightLowerArm: [0, 1.25, 0],
                      leftHand: [0.2 * tug, 0, -0.1], rightHand: [0.2 * tug, 0, 0.1],
                      spine: [0.05, 0, 0], neck: [0.1, 0, 0], head: [0.22, 0, 0] }, look: [0, -0.7] };
  }
  if (name === 'think') {                        // hand to her chin, eyes up and aside... then "got it", a small smile
    const aha = smooth((t - (length - 1.3)) / 0.35);
    return { weight: inOut, lift: 0,
             bones: { rightUpperArm: [-0.8, 0, 1.0], rightLowerArm: [0, 2.05, 0], rightHand: [-0.2, 0, 0.25],
                      leftUpperArm: [-0.45, 0, -1.15], leftLowerArm: [0, -1.5, 0],
                      hips: [0, 0, 0.04 * side], spine: [0, 0, -0.04 * side],
                      neck: [-0.05, 0.08 * side * (1 - aha), 0], head: [-0.14 * (1 - aha), 0.2 * side * (1 - aha), -0.08 * side] },
             look: [0.55 * side * (1 - aha), 0.65 * (1 - aha)],
             face: { relaxed: 0.3 * (1 - aha), happy: 0.5 * aha * inOut } };
  }
  if (name === 'smile') {                        // a smile to herself: head tipped, shoulders scrunched up in a giggle
    const giggle = smooth((t - 0.5) / 0.3) * smooth((length - 0.6 - t) / 0.3) * (0.6 + 0.4 * Math.sin(2 * Math.PI * 2.4 * t));
    return { weight: inOut, lift: 0.004 * Math.max(0, giggle),
             bones: { head: [-0.06, 0.1 * side, 0.26 * side], neck: [0, 0.04 * side, 0.08 * side],
                      chest: [-0.03, 0, 0.06 * side], spine: [0, 0, 0.05 * side],
                      leftShoulder: [0, 0, 0.1 * giggle], rightShoulder: [0, 0, -0.1 * giggle] },
             face: { happy: 0.75 * inOut } };
  }
  if (name === 'sigh') {                         // a big breath in (chest and shoulders up), and a long breath out: she slumps
    const inhale = Math.sin(Math.PI * smooth(t / 1.4)), out = smooth((t - 1.0) / 0.8) * smooth((length - t) / 0.6);
    return { weight: inOut, lift: 0.006 * inhale,
             bones: { chest: [-0.1 * inhale + 0.09 * out, 0, 0], spine: [-0.03 * inhale + 0.08 * out, 0, 0],
                      leftShoulder: [0, 0, -0.06 + 0.22 * inhale - 0.06 * out], rightShoulder: [0, 0, 0.06 - 0.22 * inhale + 0.06 * out],
                      neck: [-0.04 * inhale + 0.08 * out, 0, 0], head: [-0.1 * inhale + 0.22 * out, 0, 0.05 * side * out] },
             face: { relaxed: 0.7 * smooth((t - 0.9) / 0.5) * smooth((length - t) / 0.5) } };
  }
  if (name === 'curious') {                      // something in a corner of the screen catches her eye: she leans to look
    const peer = smooth((t - 0.2) / 0.7) * smooth((length - t) / 0.7);
    const tilt = smooth((t - 1.1) / 0.4) * smooth((length - 0.8 - t) / 0.4);   // "hm?": her head tips further
    return { weight: inOut, lift: 0.008 * peer,                                  // up on her toes a little
             bones: { hips: [0, 0.05 * side * peer, -0.05 * side * peer],
                      spine: [0.06 * peer, 0.1 * side * peer, 0.07 * side * peer], chest: [0.05 * peer, 0.1 * side * peer, 0.04 * side * peer],
                      neck: [0, 0.08 * side * peer, 0.06 * side * peer],
                      head: [-0.04 * peer, 0.12 * side * peer, (0.16 + 0.14 * tilt) * side * peer] },
             look: [0.85 * side, 0.55] };
  }
  if (name === 'lookAround') {                   // a slow look to one side, then the other, her body turning along
    // her head leads; neck, chest, spine and hips each come round a moment after the part above (turning as one
    // block, she looked like a figure on a turntable)
    const turnAt = late => Math.sin(2 * Math.PI * Math.max(0, t - late) / length), turn = turnAt(0);
    return { weight: inOut, lift: 0,
             bones: { head: [-0.08, 0.6 * turn, 0.06 * turn], neck: [-0.03, 0.25 * turnAt(0.08), 0], chest: [0, 0.18 * turnAt(0.2), 0],
                      spine: [0, 0.08 * turnAt(0.3), 0], hips: [0, 0.05 * turnAt(0.4), 0] },
             look: [0.9 * turn, 0.15] };
  }
  if (name === 'lean') {                         // settles onto one leg: hip out, the other knee loose, head tipped
    return { weight: inOut, lift: 0,
             bones: mirrorSide({ hips: [0, 0.08, 0.15], spine: [0, -0.05, -0.13], chest: [0, 0, -0.06], neck: [0, 0, 0.05],
                      head: [0.02, -0.1, 0.16],
                      leftShoulder: [0, 0, -0.12], rightShoulder: [0, 0, 0.03],
                      leftUpperArm: [0.12, 0, -1.22], rightUpperArm: [-0.08, 0, 1.34],
                      leftUpperLeg: [0, 0, -0.15], rightUpperLeg: [-0.2, 0, -0.15], rightLowerLeg: [0.38, 0, 0] }, side) };
  }
  if (name === 'rock') {                         // hands behind her back, rocking heel to toe
    const sway = Math.sin(2 * Math.PI * t / 1.6);
    return { weight: inOut, lift: 0.014 * Math.max(0, inOut) * (0.5 + 0.5 * sway),
             // (fitted on her model: each hand just behind her lower back, about 4 cm from the middle)
             bones: { leftUpperArm: [0.8, 0, -1.3, 0.6], rightUpperArm: [0.8, 0, 1.3, 0.6],
                      leftLowerArm: [0, -1.0, 0], rightLowerArm: [0, 1.0, 0],
                      hips: [-0.04 * sway, 0, 0], spine: [0.09 * sway, 0, 0.06 * sway], chest: [0.04 * sway, 0, 0],
                      neck: [0, 0, 0.05 * sway], head: [-0.08 * sway, 0, -0.12 * sway] } };
  }
  // hop: wind up into a crouch (0–0.15 s), in the air (0.15–0.4 s), land and sink a little too far (0.4–0.52 s),
  // then straighten and settle (to 0.75 s). Her chest and head follow her hips a moment late.
  const air = (t - 0.15) / 0.25;
  const crouchAt = at => at < 0 ? 0 : at < 0.15 ? smooth(at / 0.15) : at < 0.4 ? 1 - smooth((at - 0.15) / 0.1)
    : at < 0.52 ? 0.7 * smooth((at - 0.4) / 0.12) : 0.7 * (1 - overshoot((at - 0.52) / 0.23));
  const crouch = crouchAt(t), late = crouchAt(t - 0.05), later = crouchAt(t - 0.1);
  // on the ground her body sinks as far as her bent legs take it (thigh and shin each tip 0.4 rad per crouch), so her
  // feet stay planted; in the air she rises in an arc
  const lift = air > 0 && air < 1 ? 0.12 * 4 * air * (1 - air) : 0 - WALK.leg * (1 - Math.cos(0.4 * Math.max(0, crouch)));
  return { weight: smooth((length - t) / 0.12), lift,
           bones: { leftUpperLeg: [-0.4 * crouch, 0, 0], rightUpperLeg: [-0.4 * crouch, 0, 0],
                    leftLowerLeg: [0.8 * Math.max(0, crouch), 0, 0], rightLowerLeg: [0.8 * Math.max(0, crouch), 0, 0],
                    spine: [0.1 * late, 0, 0], chest: [0.06 * later, 0, 0], head: [0.1 * later - 0.12 * (lift / 0.12), 0, 0],
                    leftUpperArm: [0.1, 0, -1.3 + 0.35 * (lift / 0.12)], rightUpperArm: [0.1, 0, 1.3 - 0.35 * (lift / 0.12)] } };
}

/** The same angles, kept inside what the joint can do: an elbow or knee only bends its own way and not past
 *  folded, however poses, idle movement and gestures add up. Other bones pass through unchanged. */
export function withinLimits(name, angles) {
  const [x, y, z, twist = 0] = angles;
  const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
  if (name === 'leftLowerArm') return [x, clamp(y, -2.5, 0), z, twist];
  if (name === 'rightLowerArm') return [x, clamp(y, 0, 2.5), z, twist];
  if (name === 'leftLowerLeg' || name === 'rightLowerLeg') return [clamp(x, 0, 2.3), y, z, twist];
  return [x, y, z, twist];
}

/** One step toward `to`: within 5% of it after `seconds`, never past it. */
export function ease(from, to, dt, seconds = 0.3) {
  if (from === to) return to;
  return to + (from - to) * Math.exp(-3 * dt / seconds);
}

/** Should she blink as her gaze jumps from `from` to `to` (screen look, -1…1 each way)? A big jump is, as in
 *  people, covered by a blink; a small drift isn't, and never within a second of the last blink (`sinceBlink`). */
export function lookBlink(from, to, sinceBlink) {
  return sinceBlink > 1 && Math.hypot(to[0] - from[0], to[1] - from[1]) > 0.6;
}

/** When she blinks next: 2 to 6 seconds on, and now and then (`rand` above 0.88) a second blink straight after. */
export function nextBlink(now, rand) {
  return rand > 0.88 ? now + 0.12 : now + 2 + rand / 0.88 * 4;
}

/** A blink: her eyes shut fast (60 ms) and open again more slowly (140 ms), as real eyelids do. */
export const BLINK = { close: 0.06, open: 0.14, length: 0.2 };

/** How closed her eyes are at time t for a blink that began at `start`: 0, quickly up to 1, more slowly back to 0. */
export function blinkWeight(t, start) {
  const x = t - start;
  if (x <= 0 || x >= BLINK.length) return 0;
  const w = x < BLINK.close ? smooth(x / BLINK.close) : 1 - smooth((x - BLINK.close) / BLINK.open) ** 1.5;
  return Math.round(w * 1e6) / 1e6;
}

/** Mouth opening from the voice's volume: opens quickly, closes a little slower, shut in silence. */
export function mouthWeight(prev, level, dt) {
  const target = Math.min(1, Math.max(0, level) * 5);
  const tau = target > prev ? 0.04 : 0.12;
  const next = target + (prev - target) * Math.exp(-dt / tau);
  return level === 0 && next < 0.02 ? 0 : Math.min(1, next);
}

const RING_TURN_S = 12;

/** Where prop `index` of `count` is at time t, on a ring around her that is tilted toward the viewer. */
export function ringPosition(index, count, t, radius = 0.55, tilt = 0.35) {
  const a = 2 * Math.PI * (index / Math.max(1, count) + t / RING_TURN_S);
  const x = radius * Math.cos(a), flat = radius * Math.sin(a);
  return [x, -flat * Math.sin(tilt), flat * Math.cos(tilt)];
}

/** A companion reaction (Engines/Companion.py asks for one now and then) that fits what she's doing: nothing while
 *  she walks, jumps, peeks from behind a window or is in the middle of another gesture; sitting on the floor or on
 *  a window, a move that works sitting down. Returns the gesture to play, or null. */
const SITTING_INSTEAD = { think: 'curious', lean: 'lookAround', rock: 'smile', stretch: 'shoulderRoll',
  sideStretch: 'shoulderRoll', shakeOut: 'shoulderRoll', checkWrist: 'curious' };
export function reactionFor(name, { walking = false, jumping = false, hiding = false, gesturing = false,
                                    seated = false, perched = false } = {}) {
  if (!(name in GESTURES) || walking || jumping || hiding || gesturing) return null;
  if (!seated && !perched) return name;
  const fits = (seated ? SEATED_FIDGETS : PERCHED_FIDGETS).filter(n => n !== 'standUp' && n !== 'hopDown');
  if (fits.includes(name)) return name;
  return fits.includes(SITTING_INSTEAD[name]) ? SITTING_INSTEAD[name] : 'lookAround';
}

/** The text on her test card: the subject (at most 18 characters) and when ("Thursday", "tomorrow", …), or null. */
export function cardText(test) {
  const subject = String(test?.subject ?? '').trim();
  if (!subject) return null;
  const big = subject.length > 18 ? subject.slice(0, 17).trimEnd().padEnd(17, ' ') + '…' : subject;
  return { big, small: String(test?.when ?? '').trim() };
}

/** Her right arm through the umbrella: behind her hip (taking it out), up in front of her (opening it), resting
 *  near her shoulder (holding it). Fitted on her model. */
const UMB_ARM = {
  behind: { rightUpperArm: [0.481, 0.469, 1.2, 0.675], rightLowerArm: [0, 0.25, 0], rightHand: [0, 0, 0] },
  up: { rightUpperArm: [-0.487, -0.075, 0.975, 0.3], rightLowerArm: [0, 1.9, 0], rightHand: [0, 0, 0] },
  shoulder: { rightUpperArm: [0.112, -0.15, 1.225, 0.263], rightLowerArm: [0, 1.7, 0], rightHand: [0, 0, 0] },
};
const UMB_REST_DIR = (() => { const v = [-0.2, 1, -0.78], n = Math.hypot(...v); return v.map(x => x / n); })();
const lerpBones = (a, b, u) => Object.fromEntries(Object.keys(a).map(k => [k, a[k].map((v, i) => v + (b[k][i] - v) * u)]));
const lerpDir = (a, b, u) => { const v = a.map((x, i) => x + (b[i] - x) * u), n = Math.hypot(...v) || 1; return v.map(x => x / n); };

/** The umbrella gesture at `t` s: arm bones, and the umbrella itself: `shown` (0…1), `open` (0…1, a little past 1
 *  as it snaps open), `dir` (its shaft in her body's frame: x her left, y up, z toward you), `spin` (radians). */
function umbrellaMotion(t, length) {
  const DOWN = [0, -1, 0], UP = [0, 1, 0];
  const shown = smooth((t - 0.5) / 0.4) * (1 - smooth((t - 15.5) / 0.45));
  // opening: a quick push, then the canopy springs a little past open and settles; closing near the end
  let open = 0;
  if (t >= 1.8) open = t < 2.02 ? smooth((t - 1.8) / 0.22) : 1 + 0.14 * Math.exp(-(t - 2.02) * 7) * Math.sin((t - 2.02) * 18);
  open *= 1 - smooth((t - 14.4) / 0.7);
  // where the shaft points, and where her arm is, phase by phase
  let dir, arm;
  if (t < 0.9) [dir, arm] = [DOWN, UMB_ARM.behind];
  else if (t < 1.8) { const u = smooth((t - 0.9) / 0.9); [dir, arm] = [lerpDir(DOWN, UP, u), lerpBones(UMB_ARM.behind, UMB_ARM.up, u)]; }
  else if (t < 2.3) [dir, arm] = [UP, UMB_ARM.up];
  else if (t < 14.4) { const u = smooth((t - 2.3) / 0.7); [dir, arm] = [lerpDir(UP, UMB_REST_DIR, u), lerpBones(UMB_ARM.up, UMB_ARM.shoulder, u)]; }
  else if (t < 15.1) { const u = smooth((t - 14.4) / 0.7); [dir, arm] = [lerpDir(UMB_REST_DIR, UP, u), lerpBones(UMB_ARM.shoulder, UMB_ARM.up, u)]; }
  else { const u = smooth((t - 15.1) / 0.8); [dir, arm] = [lerpDir(UP, DOWN, u), lerpBones(UMB_ARM.up, UMB_ARM.behind, u)]; }
  // two twirls while it rests on her shoulder, a turn and a quarter each
  const spin = 2 * Math.PI * 1.25 * (smooth((t - 6) / 1.2) + smooth((t - 10.5) / 1.2));
  const glance = smooth((t - 2.0) / 0.3) * smooth((3.3 - t) / 0.3);   // she looks up at it as it opens
  const held = smooth((t - 2.3) / 0.5) * smooth((14.6 - t) / 0.5);
  return { weight: smooth(t / 0.5) * smooth((length - t) / 0.5), lift: 0,
           bones: { ...arm, head: [-0.06 * glance, 0, -0.05 * held] },
           umbrella: { shown, open, dir, spin },
           // she looks up at it as it opens; the rest of the time her gaze is her own (the mouse, glances)
           ...(glance > 0.01 ? { look: [-0.25 * glance, 0.05 + 0.5 * glance] } : {}),
           face: { happy: 0.35 * held } };
}

// ── bob to music (Engines/Beat.py finds the beat; she only moves to it) ──

/** Her beat clock: `bpm` and where the beats fall (`at`, a time on her own clock when a beat lands). Each report
 *  ("the next beat is in `nextIn` s", at time `t`) pulls it a third of the way, so the nod doesn't jitter; a clearly
 *  different tempo (another song) starts it afresh. */
export function beatClock(prev, bpm, nextIn, t) {
  const at = t + nextIn;
  if (!prev || !prev.bpm || Math.abs(bpm - prev.bpm) / prev.bpm > 0.05) return { bpm, at };
  const period = 60 / bpm;
  let err = ((at - prev.at) / period) % 1;                  // how far off the old clock is, in beats (-0.5…0.5)
  if (err > 0.5) err -= 1;
  if (err < -0.5) err += 1;
  return { bpm, at: prev.at + 0.35 * err * period };
}

/** How many beats have gone by at time `t` (a whole number exactly on a beat). */
export function beatsAt(clock, t) {
  return (t - clock.at) * clock.bpm / 60;
}

/** One moment of bobbing along, added on top of her pose: `beats` from her beat clock, `amount` 0…1, `bpm` for how
 *  often she nods (every beat, or every other beat when the song is fast: a frantic nod looks wrong). Her head dips
 *  just after the beat and comes back up, her body dips a touch with it and rises on the off-beat, and her shoulders
 *  and hips sway side to side over two nods. */
export function bobMotion(beats, amount, bpm) {
  const a = Math.max(0, Math.min(1, amount));
  const every = bpm > 140 ? 2 : 1;
  const nb = beats / every;
  const p = nb - Math.floor(nb);
  let d = p - 0.06;                                          // the dip is deepest just after the beat
  if (d > 0.5) d -= 1;
  const dip = Math.abs(d) < 0.3 ? Math.cos(Math.PI * d / 0.6) ** 2 : 0;
  const sway = Math.sin(Math.PI * nb);
  return {
    head: [0.14 * a * dip, 0, 0.035 * a * sway], neck: [0.04 * a * dip, 0, 0.02 * a * sway],
    chest: [0.02 * a * dip, 0, -0.03 * a * sway], spine: [0.01 * a * dip, 0, -0.02 * a * sway],
    hips: [0, 0, 0.015 * a * sway],
    leftShoulder: [0, 0, -0.05 * a * dip], rightShoulder: [0, 0, 0.05 * a * dip],
    lift: 0.006 * a * (1 - dip),                           // up on the off-beat, feet down on the beat
  };
}
