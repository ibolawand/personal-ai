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
  'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot'];
// (a foot's x: positive points her toes down, negative lifts them. A model without foot bones, like the built-in
// figure, just keeps its feet square to its shins.)

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
             // fitted on her model: the tip of her index finger on her chin, her thumb under it (the hand used to
             // stop beside her ear)
             rightUpperArm: [-0.63, 0, 1.11, 0.21], rightLowerArm: [0, 2.5, 0, 0.28], rightHand: [0.06, 0.33, 0.05],
             leftUpperLeg: [0, 0, -0.05], rightUpperLeg: [-0.1, 0, -0.05], rightLowerLeg: [0.2, 0, 0] },
    hands: { right: 'chin' },
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
  const hands = Object.fromEntries(Object.entries(p.hands || {}).map(([side, shape]) => [side, HANDS[shape]]));
  return { bones, expressions: { ...p.expressions }, hands };
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
    // the shin of a loose knee slants back by half the bend: the foot turns up as much, so its sole stays on the floor
    leftFoot: [-0.5 * knee(-1), 0, 0], rightFoot: [-0.5 * knee(1), 0, 0],
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

// ── her hands ──
// A hand is { curl: [index, middle, ring, little], spread, thumb }: each finger's curl as a share of the relaxed
// curl (0 straight, 1 hanging relaxed, about 3 a fist), how far the fingers fan out (0 together … 1 wide), and the
// thumb (0 held out … 1 relaxed … 2 folded across the palm). The rig turns that into finger joints (vrmrig.mjs).

/** The shapes her hands take. Fingers never all do the same: the little finger curls most, the index least. */
export const HANDS = {
  relaxed: { curl: [0.8, 1, 1.15, 1.3], spread: 0.15, thumb: 1 },
  open: { curl: [0.12, 0.05, 0.12, 0.28], spread: 0.85, thumb: 0.15 },     // a wave: palm out, fingers fanned
  splay: { curl: [-0.1, -0.15, -0.1, 0], spread: 1.2, thumb: 0 },          // a stretch: fingers wide and bent back a touch
  flat: { curl: [0.35, 0.3, 0.4, 0.6], spread: 0, thumb: 1.1 },            // fingers together: over a yawn, in her lap
  loose: { curl: [1.5, 1.8, 2.0, 2.2], spread: 0, thumb: 1.3 },            // half closed: holding her own wrist, behind her back
  grip: { curl: [2.5, 2.8, 2.95, 3.1], spread: 0, thumb: 1.9 },            // closed round a handle or a hem
  pinch: { curl: [1.5, 1.7, 1.95, 2.2], spread: 0.1, thumb: 1.6 },         // a card between fingers and thumb
  chin: { curl: [0.7, 2.5, 2.8, 3.0], spread: 0, thumb: 0.5 },             // thinking: chin between thumb and index
  point: { curl: [0.1, 1.7, 2.0, 2.3], spread: 0, thumb: 1.2 },            // her index finger out, reaching for the pointer
};

/** Her hands hanging relaxed at time t: { left, right }. Never quite still (fingerCurl), and as the fingers close
 *  a little the thumb comes in with them. */
export function restingHands(t) {
  const curls = fingerCurl(t);
  const hand = side => {
    const curl = curls[side], closed = (curl[1] - 1) / 0.22;                 // -1…1: how far through its little squeeze
    return { curl, spread: HANDS.relaxed.spread - 0.08 * closed, thumb: 1 + 0.1 * closed };
  };
  return { left: hand('left'), right: hand('right') };
}

/** One hand `w` (0…1) of the way from `a` to `b`. */
export function mixHand(a, b, w) {
  const m = (x, y) => x + (y - x) * w;
  return { curl: a.curl.map((c, i) => m(c, b.curl[i])), spread: m(a.spread, b.spread), thumb: m(a.thumb, b.thumb) };
}

/** Her hands, from what she is doing. `layers` are [{ left?, right? }, weight] in order, each laid over the one
 *  before (a pose's hands, then a gesture's); `talk` (0…1) opens her fingers on the beats of her own voice, and
 *  `swing` (-1…1 per side, walking) lets them trail her arm: a little more closed on the way back, opening as the
 *  hand comes forward. */
export function handPose(t, layers = [], { talk = 0, swing = null } = {}) {
  const out = restingHands(t);
  for (const side of ['left', 'right']) {
    let h = out[side];
    if (swing) h = { ...h, curl: h.curl.map(c => c * (1 + 0.22 * swing[side])) };
    if (talk > 0) {                                                          // each hand on its own beat, like talkMotion
      const beat = 0.5 + 0.5 * Math.sin(t * (side === 'left' ? 3.3 : 2.9) + (side === 'left' ? -0.4 : 0.6));
      h = { curl: h.curl.map(c => c * (1 - 0.45 * talk * beat)), spread: h.spread + 0.35 * talk * beat, thumb: h.thumb - 0.3 * talk * beat };
    }
    for (const [hands, weight] of layers) {
      if (hands?.[side] && weight > 0) h = mixHand(h, hands[side], Math.min(1, weight));
    }
    out[side] = h;
  }
  return out;
}

/** A breath of air on her hair at time t, [x, z] (small: a share of how hard gravity pulls). It comes in slow
 *  gusts with still moments between them, never the same twice, so hair that hangs isn't frozen. */
export function breeze(t) {
  const gust = 0.5 + 0.5 * Math.sin(t * 0.23 + 1.3 * Math.sin(t * 0.071));
  return [0.07 * gust * Math.sin(t * 0.83 + 0.6 * Math.sin(t * 0.37)), 0.05 * gust * Math.sin(t * 0.61 + 2)];
}

const smooth = x => x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x);
/** Rises over `rise` s from `start`, holds, and falls over `fall` s from `end` (0…1 at time `t`). */
const envelope = (t, start, rise, end, fall) => smooth((t - start) / rise) * (1 - smooth((t - end) / fall));
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
    swing: { left: Math.sin(phase - 0.8), right: -Math.sin(phase - 0.8) },     // for her fingers: they trail each arm
    bones: {
      leftUpperLeg: [-a * s, 0, 0], rightUpperLeg: [a * s, 0, 0],
      // the knee bends while that foot is off the ground and swinging through, the most as it passes under her
      leftLowerLeg: [0.55 * Math.max(0, c) ** 1.5, 0, 0], rightLowerLeg: [0.55 * Math.max(0, -c) ** 1.5, 0, 0],
      // her feet roll: the back foot pushes off its toes as it leaves the ground, and the front foot comes down
      // heel first, toes up (feet kept square to the shins made her walk on flat boards)
      leftFoot: [footRoll(phase), 0, 0], rightFoot: [footRoll(phase + Math.PI), 0, 0],
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

/** A foot's angle through the walk cycle (for the left foot; the right is half a cycle on): toes down as it pushes
 *  off behind her, toes up as it reaches forward to land, flat while it stands. */
function footRoll(phase) {
  return 0.34 * Math.max(0, Math.cos(phase + 1.25)) ** 2 - 0.24 * Math.max(0, Math.cos(phase - 1.3)) ** 3;
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

// ── follow-through: her arms carry on a moment after they are told to stop ──
// Every joint used to follow what it is told through the same short smoothing, so a whole arm started and stopped
// as one piece. Real limbs have weight: the upper arm lags a little, the forearm more, the hand most, and each
// carries on past where it stops and settles back (overlapping action, follow-through). These joints follow on a
// spring instead: [how quickly it swings (Hz), damping (below 1 it overshoots a little)].
export const LOOSE = {
  leftShoulder: [4.5, 0.85], rightShoulder: [4.5, 0.85],
  leftUpperArm: [5.5, 0.9], rightUpperArm: [5.5, 0.9],         // (looser, a waving arm hung out sideways on the way down)
  leftLowerArm: [3.6, 0.62], rightLowerArm: [3.6, 0.62],
  leftHand: [4.2, 0.5], rightHand: [4.2, 0.5],
};

// quaternions as [x, y, z, w] (as three.js' toArray), so this needs no 3D library
const qMul = (a, b) => [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
                        a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
const qInv = q => [-q[0], -q[1], -q[2], q[3]];
/** The rotation `q` as a vector: its axis times its angle (the short way round). */
function qLog(q) {
  const s = q[3] < 0 ? -1 : 1, v = [s * q[0], s * q[1], s * q[2]], n = Math.hypot(...v);
  if (n < 1e-9) return [0, 0, 0];
  const angle = 2 * Math.atan2(n, s * q[3]);
  return v.map(c => c / n * angle);
}
function qExp(r) {
  const angle = Math.hypot(...r);
  if (angle < 1e-9) return [0, 0, 0, 1];
  const k = Math.sin(angle / 2) / angle;
  return [r[0] * k, r[1] * k, r[2] * k, Math.cos(angle / 2)];
}
function qSlerp(a, b, u) {
  return qMul(qExp(qLog(qMul(b, qInv(a))).map(c => c * u)), a);
}

/** Where joint `name` is this frame, as a quaternion, when it is told to be at `target`. `memory` (a Map the rig
 *  keeps) holds where each joint was and how fast it turned. Loose joints (LOOSE) follow on a spring when `dt` is
 *  given; the rest close `follow` of the gap each frame (1: at once, and a loose joint then stops dead too). */
export function followJoint(memory, name, target, dt, follow = 1) {
  const was = memory.get(name);
  let q = target;
  if (was && follow < 1) {
    const loose = dt > 0 && LOOSE[name];
    if (loose) {
      // how far she is from where she is told, as a rotation, springs back to nothing; its speed carries on
      const off = qLog(qMul(was.q, qInv(target)));
      const v = was.v || [0, 0, 0];
      for (let i = 0; i < 3; i++) [off[i], v[i]] = spring(off[i], v[i], 0, dt, loose[0], loose[1]);
      q = qMul(qExp(off), target);
      memory.set(name, { q, v });
      return q;
    }
    q = qSlerp(was.q, target, follow);
  }
  memory.set(name, { q, v: [0, 0, 0] });
  return q;
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
const SIT_FOOT = -(SIT_THIGH + SIT_KNEE);       // her shins slant forward: her feet turn so the soles are on the floor
const SIT = {                                    // on the floor hugging her knees
  hips: [0, 0, 0], spine: [0.22, 0, 0], chest: [0.08, 0, 0], neck: [-0.05, 0, 0], head: [-0.12, 0, 0],
  leftUpperLeg: [SIT_THIGH, 0, -0.1], rightUpperLeg: [SIT_THIGH, 0, 0.1], leftLowerLeg: [SIT_KNEE, 0, 0], rightLowerLeg: [SIT_KNEE, 0, 0],
  // arms wrapped round her shins: elbows beside her knees, forearms across the front of her shins below them, one
  // hand over the other wrist (fitted on her model to those points; with elbows bent further her hands floated
  // above her knees, held apart)
  leftUpperArm: [-0.6, -0.52, -0.8, 0.6], leftLowerArm: [0, -1.25, 0, 0], leftHand: [-0.15, 0.05, -0.4, 0],
  rightUpperArm: [-0.9, 0.75, 1.25, 0.6], rightLowerArm: [0, 1.03, 0, 0.38], rightHand: [0, -0.05, 0.25, 0.15],
  leftFoot: [SIT_FOOT, 0, 0], rightFoot: [SIT_FOOT, 0, 0],
};
/** Her hands sitting on the floor: one holding the other wrist round her shins. */
export const SIT_HANDS = { left: HANDS.loose, right: HANDS.flat };
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
  leftFoot: [0.3, 0, 0.05], rightFoot: [0.38, 0, -0.05],     // feet hanging loose, toes down, not quite alike
};
/** Her hands sitting on an edge: resting flat in her lap. */
export const LEDGE_HANDS = { left: HANDS.flat, right: HANDS.flat };
/** How far she turns from facing you while she sits on an edge (radians; her head and eyes turn back to you).
 *  Square on, her skirt flips up at the front with her thighs level; a little turned, her near thigh hides it. */
export const PERCH_YAW = 0.45;
const CROUCH = {                                 // knees bent to jump or to land (feet under her hips)
  spine: [0.3, 0, 0], head: [-0.15, 0, 0],
  leftUpperLeg: [-0.5, 0, 0], rightUpperLeg: [-0.5, 0, 0], leftLowerLeg: [1.0, 0, 0], rightLowerLeg: [1.0, 0, 0],
  leftUpperArm: [0.55, 0, -1.25], rightUpperArm: [0.55, 0, 1.25],     // arms swung back, ready to throw forward
  leftFoot: [-0.5, 0, 0], rightFoot: [-0.5, 0, 0],                     // soles flat on the ground under slanting shins
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

/** How often she sits right on a window's top corner when the stretch she goes to ends at one (0…1). */
export const CORNER_CHANCE = 0.6;
/** Her legs swinging while she sits on a window's top corner: a carefree, steady swing, one leg forward as the
 *  other goes back, bigger and faster for a while and then lazier, never quite stopping. Each foot trails its
 *  shin, the thighs lift a little on the forward kick, and her body rocks back a hair against the legs. */
function cornerSwing(t) {
  const now = 0.65 + 0.35 * Math.sin(t * 0.21) * Math.sin(t * 0.13 + 0.7);          // lively bouts, lazy spells
  const phase = 2 * Math.PI * 1.15 * t + 0.6 * Math.sin(t * 0.17);                    // ~1.15 swings a second, never mechanical
  const kick = 0.42 * now, leg = side => Math.sin(phase + (side < 0 ? 0 : Math.PI));
  const lag = side => Math.sin(phase - 0.9 + (side < 0 ? 0 : Math.PI));              // the foot follows the shin
  const both = Math.sin(2 * phase);                                                     // twice a swing: a leg comes forward
  return {
    leftLowerLeg: [kick * leg(-1), 0, 0], rightLowerLeg: [kick * leg(1), 0, 0],
    // the thigh comes up a little as its shin kicks out (negative x: forward)
    leftUpperLeg: [-0.08 * now * Math.max(0, -leg(-1)), 0, 0], rightUpperLeg: [-0.08 * now * Math.max(0, -leg(1)), 0, 0],
    leftFoot: [0.6 * kick * lag(-1), 0, 0], rightFoot: [0.6 * kick * lag(1), 0, 0],
    spine: [-0.02 * now * both, 0, 0], head: [0.015 * now * both, 0, 0],               // a hair of counter-rock, head steady
  };
}

/** Her legs swinging while she sits on an edge: now and then a slow kick, one foot after the other; on a window's
 *  corner (`corner`, ±1) a steady, carefree swing (`cornerSwing`). */
export function dangle(t, corner = 0) {
  if (corner) return cornerSwing(t);
  const now = Math.max(0, Math.sin(t * 0.37) * Math.sin(t * 0.23 + 1));      // comes and goes
  const kick = 0.28 * now;
  // each foot trails its shin: toes down as it swings forward, up as it swings back
  return { leftLowerLeg: [kick * Math.sin(t * 2.4), 0, 0], rightLowerLeg: [kick * Math.sin(t * 2.4 + 2.2), 0, 0],
           leftFoot: [0.7 * kick * Math.sin(t * 2.4 - 1.1), 0, 0], rightFoot: [0.7 * kick * Math.sin(t * 2.4 + 2.2 - 1.1), 0, 0] };
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
 *  When the stretch ends at the window's own corner (`corners`: -1 left, 1 right) and `rc` (0…1) is below
 *  CORNER_CHANCE, she sits on that corner instead (the nearer one), just in from it: { dx, y, corner }.
 *  { dx, y } in pixels, or null when there is none. */
export function planPerch(seats, r, margin = 60, rc = 1) {
  // (a seat below her feet, `low`: the bottom panel's top edge; she sits down onto it where she stands)
  const ok = (seats || []).filter(s => s.half > margin && (s.y < 0 || s.low));
  if (!ok.length) return null;
  const weights = ok.map(s => 1 / (1 + Math.abs(s.x) / 300));
  let left = r * weights.reduce((a, b) => a + b, 0), pick = ok.at(-1);
  for (let i = 0; i < ok.length; i++) if ((left -= weights[i]) < 0) { pick = ok[i]; break; }
  const corners = (pick.corners || []).filter(c => c === -1 || c === 1);
  if (!pick.low && corners.length && rc < CORNER_CHANCE) {
    // the nearer corner (her side of the stretch's middle, or the only one)
    const corner = corners.length > 1 ? (pick.x > 0 ? -1 : 1) : corners[0];
    return { dx: pick.x + corner * (pick.half - margin), y: pick.y, corner };
  }
  const dx = Math.max(pick.x - pick.half + margin, Math.min(pick.x + pick.half - margin, 0));
  return { dx, y: pick.y };
}

// ── carried: someone drags her window ──
// Picked up, her feet leave the floor: her legs hang loose, toes down, and her arms lift a little for balance. Moved
// sideways, she swings like something held from above: her legs trail behind the movement and her upper body
// leans back the other way to stay upright, her head last. Change direction and she swings through; stop and she
// swings past once or twice and settles. Put down, her knees give and she straightens up with a small overshoot.

/** How she swings when carried: `hz` and `zeta` of the swing (below 1: it swings past and settles), how far a
 *  push of 1 unit/s² tips her (`gain`, radians), the most she tips (`max`), how fast her speed and push are read
 *  (`smooth`, seconds), and how far a fast throw may carry her speed (`fast`, units/s). */
export const CARRY = { hz: 1.4, zeta: 0.5, gain: 0.012, max: 0.32, smooth: 0.05, fast: 8 };

/** Her window's position `x`, `y` (units, x to the viewer's right, y up) at `t` seconds, read into how fast it
 *  goes and how hard it is pushed: { x, y, t, vx, vy, ax, ay }. Smoothed, so one jumpy reading doesn't jolt her. */
export function carryInput(prev, x, y, t) {
  if (!prev || !(t > prev.t)) return { x, y, t, vx: 0, vy: 0, ax: 0, ay: 0 };
  const dt = Math.min(0.1, t - prev.t), k = 1 - Math.exp(-dt / CARRY.smooth);
  const clip = v => Math.max(-CARRY.fast, Math.min(CARRY.fast, v));
  const vx = prev.vx + (clip((x - prev.x) / dt) - prev.vx) * k, vy = prev.vy + (clip((y - prev.y) / dt) - prev.vy) * k;
  return { x, y, t, vx, vy, ax: prev.ax + ((vx - prev.vx) / dt - prev.ax) * k, ay: prev.ay + ((vy - prev.vy) / dt - prev.ay) * k };
}

/** One step of her swing: `sway` { a, v } (radians, a hanging leg's sideways angle: positive swings her feet toward
 *  her own left, the viewer's right), pushed sideways by `ax` (units/s², to the viewer's right). Her feet trail the
 *  push: pushed right, they swing left. */
export function carrySwing(sway, ax, dt) {
  const target = Math.max(-CARRY.max, Math.min(CARRY.max, -ax * CARRY.gain));
  const [a, v] = spring(sway?.a || 0, sway?.v || 0, target, dt, CARRY.hz, CARRY.zeta);
  return { a: Math.max(-1.5 * CARRY.max, Math.min(1.5 * CARRY.max, a)), v };
}

/** Her body while held (`held` 0…1: picked up) swinging by `a` (carrySwing): bones added to her pose. Her legs
 *  swing from the hips with the knees following, her spine and chest lean back against them, her head stays
 *  nearly level (it is what she balances with). */
export function carryPose(held, a) {
  const k = held;
  return {
    // legs hang loose: knees a little bent, toes pointing down, the swing at the hips and the shins trailing it
    leftUpperLeg: [-0.1 * k, 0, a], rightUpperLeg: [-0.06 * k, 0, a],
    leftLowerLeg: [0.22 * k, 0, 0.25 * a], rightLowerLeg: [0.3 * k, 0, 0.25 * a],
    leftFoot: [0.45 * k, 0, 0], rightFoot: [0.38 * k, 0, 0],
    hips: [0, 0, 0.35 * a], spine: [0, 0, -0.45 * a], chest: [0.02 * k, 0, -0.3 * a],
    neck: [0, 0, -0.15 * a], head: [-0.03 * k, 0, -0.1 * a],
    // arms out from her sides a little, for balance (rest: about ±1.3 down)
    leftUpperArm: [0, 0, 0.22 * k], rightUpperArm: [0, 0, -0.22 * k],
    leftLowerArm: [0, -0.15 * k, 0], rightLowerArm: [0, 0.15 * k, 0],
  };
}

/** Put down `t` seconds ago: how far her knees give (a crouch weight, 0…1; perchPose keeps her feet down). Quick
 *  in, then up again, easing off (never past straight: a knee can't). */
export const LAND_S = 1.0;
export function setDown(t) {
  if (t < 0 || t >= LAND_S) return 0;
  if (t < 0.12) return 0.35 * smooth(t / 0.12);
  const u = (t - 0.12) / (LAND_S - 0.12);
  return Math.max(0, 0.35 * Math.exp(-3.5 * u) * (Math.cos(Math.PI * 1.1 * u) + 0.25) / 1.25) * (1 - smooth((u - 0.75) / 0.25));
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

// ── her mouth from what she says (Engines/LipSync.py sends the timeline of the sounds) ──

/** The mouth shapes at `at` seconds into a timeline of segments [start, end, shape (null: lips shut), open,
 *  stress]: { aa, ih, ou, ee, oh }, or null once the timeline is over (before it starts, the mouth is shut). Lips
 *  start toward the next sound in the last 60 ms of this one (coarticulation): a mouth that changes shape exactly on
 *  each sound looks like a puppet's. */
export function speechShapes(segments, at) {
  if (!segments?.length || at >= segments.at(-1)[1]) return null;
  const shapes = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
  const i = segments.findIndex(s => at >= s[0] && at < s[1]);
  if (i < 0) return shapes;
  const [a, b, shape, open] = segments[i], next = segments[i + 1];
  const lead = Math.min(0.06, (b - a) * 0.5);
  const u = next && Math.abs(next[0] - b) < 1e-6 ? smooth((at - (b - lead)) / lead) : 0;
  if (shape) shapes[shape] += open * (1 - u);
  if (u > 0 && next[2]) shapes[next[2]] += next[3] * u;
  return shapes;
}

/** How much the stressed syllables around `at` move her (0…1): each stressed vowel gives a beat that peaks about
 *  0.12 s after it starts and fades over a third of a second. Her head and chest dip on it, as people's do on the
 *  words they stress. */
export function speechBeat(segments, at) {
  let beat = 0;
  for (const [start, , , , stress] of segments || []) {
    const u = at - start;
    if (!stress || u < 0 || u > 0.6) continue;
    beat = Math.max(beat, stress * (u < 0.12 ? smooth(u / 0.12) : Math.exp(-(u - 0.12) / 0.15)));
  }
  return beat;
}

/** Only explicit laugh syllables from the playing audio drive these bounces.
 * Eyes lead the head; each shoulder pulse follows its ha, then settles. */
export function laughMotion(segments, at) {
  let bounce = 0, smile = 0, head = 0;
  for (const [start, end, , , , cue] of segments || []) {
    if (cue !== 'laugh') continue;
    const age = at - start, length = end - start;
    if (age < 0 || age > length + 0.22) continue;
    smile = Math.max(smile, smooth(age / 0.06) * (1 - smooth((age - length) / 0.22)));
    head = Math.max(head, smooth(age / 0.11) * (1 - smooth((age - length) / 0.20)));
    bounce = Math.max(bounce, smooth(age / 0.065) * (1 - smooth((age - 0.075) / 0.16)));
  }
  return { eyes: 0.65 * smile, happy: 0.8 * smile,
    bones: { leftShoulder: [0, 0, 0.105 * bounce], rightShoulder: [0, 0, -0.095 * bounce],
      chest: [-0.045 * bounce, 0, 0], neck: [-0.025 * head, 0, 0], head: [-0.10 * head, 0, 0.025 * head] } };
}

// ── a gesture for a whole thought ──

/** A silence at least `gap` s long ends a phrase (lips closing on "m" or "p" don't); a phrase shorter than `min` s
 *  gets no gesture; gestures come at least `every` s apart; the arm gets ready `prep` s before the stressed vowel
 *  and lets go over `release` s once the phrase is over. */
export const PHRASE = { gap: 0.18, min: 0.8, every: 2.4, prep: 0.25, release: 0.75 };

/** What her arms do while she says `segments` (her voice's timeline: [start, end, shape, open, stress]): at most one
 *  gesture per phrase, around one stressed vowel. [{ start, peak, end, side }] in seconds on the speech's clock:
 *  the arm starts at `start`, makes its point at `peak` (the stressed vowel), holds through the rest of the phrase
 *  and lets go at `end`. `side`: 1 her right hand, -1 her left; mostly taking turns, now and then the same hand
 *  twice. Decided once for the whole timeline, from the sounds only (never from what the words mean). */
export function phrasePlan(segments) {
  const phrases = [];
  let cur = null;
  for (const [a, b, shape] of segments || []) {
    const quiet = !shape && b - a >= PHRASE.gap, gapBefore = cur && a - cur.end >= PHRASE.gap;
    if (quiet || gapBefore) { if (cur) phrases.push(cur); cur = null; }
    if (quiet) continue;
    if (!cur) cur = { start: a, end: b, vowels: [] };
    cur.end = b;
  }
  if (cur) phrases.push(cur);
  // the stressed vowels in each phrase
  for (const p of phrases)
    p.vowels = (segments || []).filter(([a, , shape, , stress]) => shape && stress >= 1 && a >= p.start && a < p.end).map(sg => sg[0]);
  const plan = [];
  let lastPeak = -Infinity, side = 1;
  phrases.forEach(p => {
    if (p.end - p.start < PHRASE.min || !p.vowels.length) return;
    // the first stressed vowel with time to get ready for it, else the first one (the arm comes up in what time
    // there is); never in the last fifth of the phrase: no point made as she finishes
    const latest = p.end - 0.2 * (p.end - p.start);
    const peak = p.vowels.find(v => v - p.start >= 0.3 && v <= latest) ?? p.vowels.find(v => v <= latest);
    if (peak == null || peak - lastPeak < PHRASE.every) return;
    const next = plan.length % 3 === 2 ? side : -side;   // taking turns, every third gesture the same hand again
    const start = Math.max(p.start - 0.1, peak - PHRASE.prep);
    // the same hand only once it has let go of its last point (the other hand may come up while it does)
    const last = plan.findLast(g => g.side === next);
    if (last && start < last.end + PHRASE.release) return;
    side = next;
    plan.push({ start, peak, end: p.end, side });
    lastPeak = peak;
  });
  return plan;
}

/** Her arms at `at` s into what she says, from phrasePlan: angles added to her pose ({} with no gesture going on).
 *  The upper arm comes forward first and the elbow follows it a moment later; at the stressed vowel the forearm
 *  makes the point (a small beat down and back) and the chest goes with it; she holds it, settling a little, to
 *  the end of the phrase; then the upper arm lowers with the elbow still bent, the forearm follows and the wrist
 *  last. Her hand stays below her chest. */
export function phraseGesture(plan, at, stopAt = Infinity) {
  // (one hand may still be letting go while the other comes up: both count)
  const out = {}, hands = {};
  for (const p of plan || []) {
    if (p.start >= stopAt) continue;
    // she stopped speaking (`stopAt`, on the same clock): a point not yet over is let go of from there
    const g = stopAt < p.end ? { ...p, end: Math.max(p.start, stopAt) } : p;
    if (at < g.start || at >= g.end + PHRASE.release) continue;
    const side = g.side === 1 ? 'right' : 'left', release = armRelease(at - g.end, PHRASE.release);
    hands[side] = { curl: HANDS.relaxed.curl.map((v, i) => v + (0.12 - v) *
      smooth((Math.min(at, g.end) - g.start - 0.08 - i * 0.035) / 0.22) * release.fingers),
      spread: 0.15 + 0.1 * smooth((Math.min(at, g.end) - g.start) / 0.3) * release.fingers,
      thumb: 1 - 0.5 * smooth((Math.min(at, g.end) - g.start) / 0.3) * release.fingers };
    for (const [bone, v] of Object.entries(oneGesture(g, at))) out[bone] = (out[bone] || [0, 0, 0]).map((x, i) => x + v[i]);
  }
  return Object.keys(out).length ? { bones: out, hands } : {};
}

function oneGesture(g, at) {
  const ready = Math.max(0.12, g.peak - g.start);
  const heldAt = Math.min(at, g.end);
  const up = smooth((heldAt - g.start) / ready), elbow = smooth((heldAt - g.start - 0.06) / ready);
  const beat = Math.max(0, Math.sin(Math.PI * Math.min(1, Math.max(0, (heldAt - g.peak) / 0.18))));   // the point itself
  const settle = 0.08 * smooth((at - g.peak - 0.18) / 0.4);           // the hold relaxes a touch
  const release = armRelease(at - g.end, PHRASE.release);
  const off = x => release[x];
  const arm = up * off('UpperArm') * (1 - settle), fore = elbow * off('LowerArm') * (1 - settle), wrist = smooth((heldAt - g.start - 0.12) / ready) * off('Hand');
  const sign = g.side, name = g.side === 1 ? 'right' : 'left';
  return { [name + 'UpperArm']: [-0.35 * arm, 0, -sign * 0.08 * arm],
           [name + 'LowerArm']: [0, sign * (0.9 * fore + 0.2 * beat * release.LowerArm), 0],
           [name + 'Hand']: [-0.12 * wrist + 0.08 * beat * release.Hand, sign * 0.3 * wrist, 0],
           chest: [0.02 * beat * release.UpperArm, sign * 0.03 * arm, 0] };
}

/** A tiny jump of her eyes, [x, y], that holds for a moment and then jumps again: real eyes never rest still. */
export function saccade(t) {
  const k = Math.floor(t / 0.85 + 0.4 * Math.sin(t * 0.37));
  const rand = n => { const v = Math.sin(n * 127.1 + 311.7) * 43758.5453; return (v - Math.floor(v)) * 2 - 1; };
  return [0.06 * rand(k), 0.04 * rand(k + 0.5)];
}

// ── gestures: one-off movements ──

export const GESTURES = { wave: 2.8, hop: 0.75, stretch: 2.8, lookAround: 3.2, lean: 3.6, rock: 3.2,
  neckEase: 4.8, quietGlance: 4.6, shoulderRoll: 2.8, tugJacket: 2.4, think: 3.8, smile: 2.6, sigh: 2.8, curious: 3.4,
  yawn: 3.6, checkWrist: 3.4, shakeOut: 2.6, sideStretch: 3.8, showCard: 4.6, umbrella: 16, tuckHair: 3.0, doze: 5.0, almostSneeze: 3.6, crossAnkles: 7.2, brace: 1.9, brushSleeve: 3.6, fingerFan: 4.8, ankleEase: 5.2, thoughtRelease: 2.8 };   // seconds
/** What she does now and then while idle, when nothing else is going on. */
export const FIDGETS = ['neckEase', 'quietGlance', 'stretch', 'lookAround', 'lean', 'rock', 'shoulderRoll', 'tugJacket', 'think',
  'smile', 'sigh', 'curious', 'yawn', 'checkWrist', 'shakeOut', 'sideStretch', 'showCard', 'umbrella', 'tuckHair', 'doze', 'almostSneeze', 'crossAnkles', 'brushSleeve', 'fingerFan', 'ankleEase', 'thoughtRelease'];
/** What she does while sitting on the floor (her legs are busy, her arms around her knees). */
export const SEATED_FIDGETS = ['neckEase', 'quietGlance', 'lookAround', 'curious', 'smile', 'sigh', 'shoulderRoll', 'yawn', 'doze', 'standUp'];

/** Everything she may do of her own while idle, and how likely each is. `after`: only once she has been idle that
 *  many seconds (she sits down when she is bored). Standing up gets likelier the longer she sits. */
export const IDLE = {
  neckEase: { weight: 0.9, after: 20 }, quietGlance: { weight: 1.8 },
  windowVisit: { weight: 4, after: 12 },
  stroll: { weight: 4 }, stretch: { weight: 0.8 }, lookAround: { weight: 1.5 }, lean: { weight: 1.5 },
  rock: { weight: 0.8 }, shoulderRoll: { weight: 1 }, tugJacket: { weight: 0.8 },
  think: { weight: 1 }, smile: { weight: 1.2 }, sigh: { weight: 0.8 }, curious: { weight: 1.5 },
  yawn: { weight: 0.8, after: 30 }, checkWrist: { weight: 0.8 }, shakeOut: { weight: 0.8 }, sideStretch: { weight: 0.8 },
  tuckHair: { weight: 1.1 },
  fingerFan: { weight: 0.9, after: 25, every: 240 },
  ankleEase: { weight: 1, after: 25, every: 180 },
  doze: { weight: 0 },                   // only late at night (tired), at most every 10 min: see chooseIdle
  almostSneeze: { weight: 0.7, after: 15, every: 600 },   // rare: at most every 10 min (`every`, seconds)
  crossAnkles: { weight: 1.4 },
  brushSleeve: { weight: 0.8, after: 20, every: 480 },   // rare (8 min at least), standing only: both arms are busy          // only sitting on an ordinary window edge (canCross): not a corner, not the panel
  sit: { weight: 2.5, after: 45 }, standUp: { weight: 0 },
  perch: { weight: 3, after: 15 }, hopDown: { weight: 0 }, hide: { weight: 2.4, after: 10 },
  showCard: { weight: 3, after: 8 },     // only with a test to show (canCard): the overlay sends it, she keeps the hour
  umbrella: { weight: 4, after: 5 },     // only with rain coming (canUmbrella), every 20 min at most
};
/** She sits on a window at least this long (seconds) before she may hop down of her own. */
export const PERCH_MIN_S = 90;
/** What she does while sitting on top of a window. */
export const PERCHED_FIDGETS = ['neckEase', 'quietGlance', 'lookAround', 'curious', 'smile', 'sigh', 'shoulderRoll', 'think', 'yawn', 'checkWrist', 'tuckHair', 'doze', 'almostSneeze', 'ankleEase', 'hopDown'];

// ── tired late at night ──

/** How tired she is at `hour` (local time, 0…24 with fractions): 0 through the day, rising from 22:00 to its
 *  most at 1:00, staying there until 5:00 and gone by 8:00. Smooth all the way round, midnight included. */
export function tiredness(hour) {
  const h = ((hour % 24) + 24) % 24, x = h < 12 ? h + 24 : h;       // 12…36: the night in one piece
  return smooth((x - 22) / 3) * (1 - smooth((x - 29) / 3));
}
/** What tiredness does to her, at its most: upper lids that much down (0…1), blinks that much longer, her idle
 *  movement and breath that much slower. */
export const TIRED = { lids: 0.24, blinkSlow: 0.8, idleSlow: 0.3 };
/** She nods off at most once in this many seconds. */
export const DOZE_EVERY = 600;

/** What she does next while idle. `recent`: the names of what she did last (never repeated straight away;
 *  `since`: seconds since each, for the rare ones with `every`);
 *  `idleFor`: seconds with nothing going on; `seated`, `seatedFor`. Two random numbers 0…1 pick it. Returns
 *  { stroll: ±1, peek } | { gesture, side: ±1 } | { sit: true } | { stand: true } | { perch: true } | { hopDown: true }.
 *  `perched`: sitting on top of a window (for `perchedFor` s); `canPerch`: a window she could sit on is there;
 *  `canHide`: a window she could go behind and peek out from ({ hide: true }). */
export function chooseIdle({ recent = [], idleFor = 0, seated = false, seatedFor = 0, perched = false, perchedFor = 0,
                             canPerch = false, canHide = false, canVisit = false, canCard = false, canUmbrella = false,
                             tired = 0, sinceDoze = Infinity, since = {}, canCross = false }, r1, r2) {
  const weightOf = name => {
    if (name === 'ankleEase') return perched && canCross && perchedFor >= 25 && (since[name] ?? Infinity) >= IDLE[name].every ? IDLE[name].weight : 0;
    if (name === 'crossAnkles') return perched && canCross ? IDLE.crossAnkles.weight : 0;
    // (`since`: seconds since she last did each thing; one with `every` waits that long before it comes again)
    if (IDLE[name].every && (since[name] ?? Infinity) < IDLE[name].every) return 0;
    // late at night (`tired`, 0…1: tiredness) she yawns more, and now and then nods off for a moment (not twice
    // within DOZE_EVERY seconds, and only after a while with nothing going on)
    if (name === 'doze') return tired > 0.5 && sinceDoze > DOZE_EVERY && idleFor > 20 ? 2.5 * tired : 0;
    if (name === 'yawn' && tired > 0) return (perched || seated || idleFor >= IDLE.yawn.after) ? IDLE.yawn.weight * (1 + 3 * tired) : 0;
    if (name === 'windowVisit' && (!canVisit || seated || perched)) return 0;
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
  if (pick === 'windowVisit') return { windowVisit: true };
  return { gesture: pick, side: frac(r2 * 3) < 0.5 ? -1 : 1 };
}

/** A one-off movement at `t` seconds after it began: { weight, bones, lift, face?, look?, weights?, adds?,
 *  ownBlinks? } or null once it is over. `bones` replace the pose by `weight` (0…1), or by `weights[bone]` for the
 *  bones that lead on their own; `adds` are angles added to whatever pose she is in (times `weight`); with
 *  `ownBlinks` her usual blinking waits until it is over (its `eyes` decide); `lift` raises her whole body (in metres of the model); `face` is
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

const otherHands = (hands, side) => side === -1 ? { left: hands.right, right: hands.left } : hands;

/** Can she cross her ankles now (or keep them crossed)? Only sitting on an ordinary window edge: not in the air,
 *  not at a corner (her legs swing there), not on the bottom panel, not being carried. */
export function crossFits({ perched = null, jumping = false, carried = false } = {}) {
  return !!perched && !perched.low && !perched.corner && !jumping && !carried;
}

/** These quiet details give way to travel and occupied hands, including a seat transition requested mid-gesture. */
export function detailFits(name, { waiting = true, walk = false, sit = false, perched = null,
                                   jumping = false, hide = false, visit = false, carried = false } = {}) {
  if (!['fingerFan', 'ankleEase', 'thoughtRelease'].includes(name)) return true;
  if (!waiting || walk || sit || jumping || hide || visit || carried) return false;
  return name === 'ankleEase' ? crossFits({ perched }) : !perched;
}

/** After a long thought and its answer she takes a moment to let her concentration go. Only the first
 *  quiet frame can start it; a busy ending discards it, rather than saving a reaction for later. */
export function thoughtStep(old, { state, free }, dt) {
  const s = { previous: 'idle', thinking: 0, earned: false, age: 0, cooldown: 0, ...old, fire: false };
  s.cooldown = Math.max(0, s.cooldown - dt);
  if (state === 'thinking') {
    s.thinking = s.previous === 'thinking' ? s.thinking + dt : dt;
    s.earned = s.thinking >= 6;
    s.age = 0;
  } else {
    s.thinking = 0;
    s.age += dt;
    if (state === 'idle' && s.previous !== 'idle') {
      s.fire = s.earned && s.age <= 60 && s.cooldown === 0 && free;
      if (s.fire) s.cooldown = 60;
      s.earned = false;
    } else if (state !== 'speaking' || s.age > 60) s.earned = false;
  }
  s.previous = state;
  return s;
}

// She lowers the upper arm first, keeps the elbow folded until it is mostly down, then softens her hand.
export function armRelease(elapsed, duration) {
  const p = elapsed / duration;
  return { Shoulder: 1 - smooth(p / 0.6), UpperArm: 1 - smooth(p / 0.65),
    LowerArm: 1 - smooth((p - 0.38) / 0.47), Hand: 1 - smooth((p - 0.65) / 0.35),
    fingers: 1 - smooth((p - 0.75) / 0.25) };
}

// Entry runs forward: upper arm first, then elbow and wrist. Never reverse the release clock.
export function armEntry(elapsed, duration) {
  return Object.fromEntries(Object.entries(armRelease(elapsed, duration)).map(([part, w]) => [part, 1 - w]));
}

const ARM_ENTRIES = { tuckHair: [0.12, 0.75], brace: [0.12, 0.3], almostSneeze: [0.15, 0.7],
  checkWrist: [0, 0.7], brushSleeve: [0.25, 0.6] };

const ARM_EXITS = { tuckHair: [1.75, 1.2], brace: [0.8, 1.05], almostSneeze: [2.05, 1.5],
  checkWrist: [2.6, 0.8], brushSleeve: [2.65, 0.9], fingerFan: [3.4, 1.35] };

export function gesture(name, t, side = 1) {
  const act = gesturePose(name, t, side), exit = ARM_EXITS[name];
  const entry = ARM_ENTRIES[name];
  if (act && entry && t < exit[0]) {
    act.weights = { ...act.weights };
    for (const bone of Object.keys(act.bones)) {
      if (!bone.endsWith('LowerArm') && !bone.endsWith('Hand')) continue;
      const upper = bone.replace(/(LowerArm|Hand)$/, 'UpperArm');
      const delay = bone.endsWith('Hand') ? 0.24 : 0.12;
      act.weights[bone] = Math.min(act.weights?.[upper] ?? act.weight,
        smooth((t - entry[0] - delay) / entry[1]));
    }
  }
  if (act?.ik && name === 'brushSleeve' && t >= 2.05) {
    const held = gesturePose(name, 2.05, side), release = armRelease(t - 2.05, 0.9);
    act.ik = { ...held.ik, weights: release };
    act.hands = Object.fromEntries(Object.entries(held.hands).filter(([, hand]) => hand).map(([side, hand]) =>
      [side, mixHand(HANDS.relaxed, hand, release.fingers)]));
    act.handWeight = held.weight;
  }
  if (!act || !exit || t < exit[0]) return act;
  const held = gesturePose(name, exit[0], side), release = armRelease(t - exit[0], exit[1]);
  act.weights = { ...act.weights };
  for (const [bone, angles] of Object.entries(held.bones)) {
    const part = bone.replace(/^(left|right)/, '');
    if (!(part in release)) continue;
    act.bones[bone] = angles;
    act.weights[bone] = (held.weights?.[bone] ?? held.weight) * release[part];
  }
  if (name !== 'brushSleeve') act.hands = held.hands && Object.fromEntries(Object.entries(held.hands).filter(([, hand]) => hand).map(([side, hand]) =>
    [side, mixHand(HANDS.relaxed, hand, release.fingers)]));
  act.handWeight = held.handWeight ?? held.weight;
  return act;
}

function gesturePose(name, t, side = 1) {
  const length = GESTURES[name];
  if (!length || t < 0 || t >= length) return null;
  if (name === 'fingerFan') {
    // She looks down, brings a loosely closed hand out at chest height, then turns it so the fan is visible. The fingers
    // unfold one after another, stretch, and curl back in the same order; elbow down, wrist and fingers last.
    const part = (a, b, c, d) => envelope(t, a, b, c, d);
    const eyes = part(0, 0.25, 3.65, 0.65), head = part(0.12, 0.45, 3.8, 0.8);
    const shoulder = part(0.25, 0.5, 3.3, 0.65), arm = part(0.35, 0.6, 3.4, 0.8);
    const elbow = part(0.48, 0.6, 3.5, 0.8), wrist = part(0.7, 0.6, 3.7, 0.85);
    const fan = part(1.25, 0.6, 2.65, 0.65);
    const hand = { curl: HANDS.relaxed.curl.map((v, i) => v + (HANDS.splay.curl[i] - v) * part(1.25 + i * 0.09, 0.55, 2.65 + i * 0.09, 0.65)),
                   spread: 0.15 + 1.45 * fan, thumb: 1 - 0.85 * part(1.55, 0.55, 2.95, 0.65) };
    // The forearm supplies the roll; the wrist only finishes the turn, without bending past its range.
    const sl = side === 1 ? 'left' : 'right';
    return { weight: part(0, 0.25, 4.5, 0.3), lift: 0,
      weights: { [sl + 'Shoulder']: shoulder, [sl + 'UpperArm']: arm, [sl + 'LowerArm']: elbow, [sl + 'Hand']: wrist },
      bones: mirrorSide({ leftShoulder: [0, 0, -0.07], leftUpperArm: [-0.45, -0.15, -1.1],
        leftLowerArm: [0, -1.25, 0, -1.1], leftHand: [-0.7 + 0.12 * fan, -0.8, -0.8] }, side),
      adds: mirrorSide({ head: [0.16 * head, 0.12 * head, 0.02 * head], neck: [0.06 * head, 0.04 * head, 0],
        chest: [0.025 * part(0.3, 0.6, 3.5, 0.9), 0, 0] }, side),
      hands: otherHands({ left: hand }, side), look: [0.3 * side * eyes, -0.35 * eyes],
      face: { relaxed: 0.25 * part(2, 0.5, 3.8, 0.7) } };
  }
  if (name === 'ankleEase') {
    // On an ordinary ledge she stills her swing, lifts one shin clear, and rolls that ankle twice, the second
    // circle smaller. The toes soften before the shin drops and her ordinary swing returns. Her hips stay put.
    const part = (a, b, c, d) => envelope(t, a, b, c, d);
    const shin = part(0.4, 0.65, 3.85, 0.8), foot = part(0.95, 0.4, 3.5, 0.55);
    const phase = 4 * Math.PI * smooth((t - 1.1) / 2.4);
    const smaller = 1 - 0.4 * smooth((t - 2.3) / 1.2);
    const glance = part(0, 0.4, 2.8, 0.8);
    return { weight: part(0, 0.25, 4.85, 0.35), lift: 0, bones: {},
      calm: part(0, 0.4, 4.65, 0.55),
      adds: mirrorSide({ leftLowerLeg: [-0.22 * shin, 0, 0],
        leftFoot: [0.14 * foot * smaller * Math.cos(phase), 0, 0.09 * foot * smaller * Math.sin(phase)],
        chest: [-0.025 * part(0.15, 0.4, 3.9, 0.9), 0, 0],
        head: [0.12 * part(0.15, 0.45, 2.9, 0.8), 0, 0] }, side),
      look: [0.15 * side * glance, -0.55 * glance] };
  }
  if (name === 'thoughtRelease') {
    // The answer is over: eyes close gently, chin dips in a last trace of concentration, then her shoulders
    // soften. Her head comes back a little past level, eyes reopen, and a small smile settles with her wrists.
    const part = (a, b, c, d) => envelope(t, a, b, c, d);
    const dip = part(0.15, 0.4, 0.65, 0.65), soften = part(0.5, 0.55, 1.65, 0.9);
    const back = part(0.9, 0.5, 1.5, 0.9), wrist = part(0.7, 0.55, 1.9, 0.85);
    return { weight: part(0, 0.3, 2.45, 0.35), lift: 0, bones: {}, ownBlinks: true,
      eyes: 0.85 * part(0, 0.28, 0.65, 0.55),
      adds: { head: [0.09 * dip - 0.035 * back, 0, 0.05 * side * back], neck: [0.025 * dip, 0, 0],
        chest: [0.04 * soften, 0, 0], leftShoulder: [0, 0, -0.06 * soften], rightShoulder: [0, 0, 0.06 * soften],
        leftUpperArm: [0, 0, 0.025 * soften], rightUpperArm: [0, 0, -0.025 * soften],
        leftHand: [0.06 * wrist, 0, 0], rightHand: [0.06 * wrist, 0, 0] },
      face: { relaxed: 0.4 * soften, happy: 0.18 * part(1.1, 0.5, 2.2, 0.6) } };
  }
  if (name === 'brushSleeve') {                  // a speck on her sleeve: she looks, lifts the arm, brushes it off twice
    // Eyes down on her forearm and her head after them; that arm comes up in front of her, elbow bent; the other
    // hand comes over, its elbow leading, and brushes along the sleeve toward the wrist: a long stroke, a little lift
    // back, a shorter one; the brushing arm goes down while she still looks; then the sleeve arm, and her head
    // comes up last. The brushing hand is put on the sleeve by IK (`ik`: which hand, how far along the other
    // forearm from elbow to wrist, how far above it, and its weight), so it fits her own arms.
    const L = GESTURES.brushSleeve, sl = side === 1 ? 'left' : 'right';
    const look = smooth(t / 0.35) * (1 - smooth((t - 2.9) / 0.6));
    const lift = smooth((t - 0.25) / 0.6) * (1 - smooth((t - 2.65) / 0.85));
    const reach = smooth((t - 0.7) / 0.55) * (1 - smooth((t - 2.05) / 0.6));
    // along the sleeve: in to the elbow, a stroke out, back a little (lifting), a shorter stroke out
    const stroke1 = smooth((t - 1.25) / 0.3), back = smooth((t - 1.55) / 0.25), stroke2 = smooth((t - 1.8) / 0.25);
    const along = 0.2 + 0.65 * stroke1 - 0.5 * back + 0.45 * stroke2;
    const above = 0.025 + 0.025 * Math.sin(Math.PI * Math.min(1, Math.max(0, (t - 1.55) / 0.25))) + 0.025 * (1 - smooth((t - 0.95) / 0.3));
    return { weight: smooth(t / 0.2) * smooth((L - t) / 0.4), lift: 0,
             // (the sleeve arm and her head each keep their own time; her head turns toward that arm, as in checkWrist)
             weights: { [sl + 'Shoulder']: lift, [sl + 'UpperArm']: lift, [sl + 'LowerArm']: lift, [sl + 'Hand']: lift,
                        head: look, neck: look, chest: look, spine: look },
             bones: mirrorSide({ leftUpperArm: [-0.35, -0.35, -1.25], leftLowerArm: [0, -1.35, 0], leftHand: [0, -0.35, -0.15],
                                 spine: [0.03, 0, 0], chest: [0.04, 0.06, 0], neck: [0.1, 0.08, 0], head: [0.24, 0.16, 0.05] }, side),
             ik: { hand: sl === 'left' ? 'right' : 'left', sleeve: sl, along, above, weight: reach, weights: armEntry(t - 0.7, 0.55) },
             hands: otherHands({ right: mixHand(HANDS.relaxed, HANDS.flat, reach) }, side),
             look: [0.35 * side * look, -0.55 * look],
             face: { relaxed: 0.25 * smooth((t - 2.2) / 0.4) * smooth((L - t) / 0.5) } };
  }
  if (name === 'brace') {                        // a window came up right beside her: she flinches away, then looks
    // `side` is her side the window is on (1: her right). Eyes there first, with a blink; her near shoulder comes up
    // and her chest pulls back and away; the near arm draws in, the elbow bends and the forearm comes up in front of
    // her, the open hand a moment behind; a beat while she looks it over; then the shoulder and chest let go, the
    // arm comes down and the hand relaxes last, with a small "oh, it's only you" smile.
    const L = GESTURES.brace;
    const flinch = smooth((t - 0.08) / 0.14) * (1 - smooth((t - 0.75) / 0.65));
    const arm = smooth((t - 0.12) / 0.3) * (1 - smooth((t - 0.8) / 0.6));
    const hand = smooth((t - 0.22) / 0.25) * (1 - smooth((t - 1.2) / 0.6));
    const eyes = smooth(t / 0.1) * (1 - smooth((t - 1.2) / 0.6));
    const near = side === 1 ? 'right' : 'left';
    return { weight: smooth(t / 0.06) * smooth((L - t) / 0.3), lift: 0.004 * flinch,
             weights: { [near + 'Shoulder']: flinch, [near + 'UpperArm']: arm, [near + 'LowerArm']: arm, [near + 'Hand']: hand },
             bones: mirrorSide({ rightShoulder: [0, 0, -0.12], rightUpperArm: [-0.55, 0.4, 1.2], rightLowerArm: [0, 1.7, 0],
                                 rightHand: [0, 0, 0.25] }, side),
             // (her body on top of whatever she stands like: back and away from it. A positive tilt leans her toward
             // her right: away from a window there is negative. Measured on her model)
             adds: mirrorSide({ spine: [-0.03 * flinch, 0, -0.03 * flinch], chest: [-0.06 * flinch, 0, -0.05 * flinch],
                                neck: [-0.04 * flinch, 0, -0.02 * flinch], head: [-0.08 * flinch, 0, -0.04 * flinch] }, side),
             hands: otherHands({ right: mixHand(HANDS.relaxed, { curl: [0.15, 0.2, 0.25, 0.35], spread: 0.35, thumb: 0.4 }, hand) }, side),
             eyes: Math.max(0, 1 - Math.abs(t - 0.06) / 0.06),             // a blink as her eyes jump to it
             look: [-0.75 * side * eyes, 0.05 * eyes],                       // (screen x: her right is your left)
             face: { surprised: 0.6 * flinch, happy: 0.3 * smooth((t - 1.1) / 0.3) * smooth((L - t) / 0.4) } };
  }
  if (name === 'neckEase') {
    // A slow release of tension: shoulder first, ear toward it, then chin down
    // as she returns. No leg or arm targets, so this also works on a ledge.
    const hold = smooth(t / 0.65) * smooth((length - t) / 0.85);
    const tilt = smooth((t - 0.35) / 0.95) * (1 - smooth((t - 2.6) / 1.25));
    const release = smooth((t - 2.2) / 0.7) * smooth((length - t) / 1.1);
    const shoulder = smooth(t / 0.6) * (1 - smooth((t - 1.4) / 1.2));
    return { weight: hold, lift: 0,
      bones: mirrorSide({ rightShoulder: [0, 0, 0.06 - 0.12 * shoulder],
        neck: [0.04 * release, 0.025 * tilt, -0.09 * tilt],
        head: [0.12 * release, 0.06 * tilt, -0.24 * tilt],
        chest: [0.025 * release, 0, 0.025 * tilt] }, side),
      look: [0.12 * side * tilt, -0.18 * release],
      eyes: 0.45 * tilt, face: { relaxed: 0.35 * tilt * hold } };
  }
  if (name === 'quietGlance') {
    // Attention goes to the side before her head follows; she returns to the
    // viewer and gives a fleeting smile before settling back into stillness.
    const hold = smooth(t / 0.6) * smooth((length - t) / 0.9);
    const gaze = smooth(t / 0.4) * (1 - smooth((t - 2.15) / 0.55));
    const turn = smooth((t - 0.18) / 0.85) * (1 - smooth((t - 2.4) / 0.95));
    const smile = smooth((t - 2.7) / 0.55) * smooth((length - t) / 0.9);
    return { weight: hold, lift: 0,
      bones: mirrorSide({ neck: [0.015 * turn, 0.08 * turn, 0],
        head: [0.035 * turn - 0.025 * smile, 0.24 * turn, 0.07 * smile],
        chest: [0, 0.045 * turn, 0] }, side),
      look: [0.65 * side * gaze, 0.08 * gaze],
      face: { happy: 0.32 * smile, relaxed: 0.12 * hold } };
  }
  if (name === 'wave') {
    // A real wave: the elbow bends first, the shoulder lifts and the upper arm comes up beside her, turning so the
    // forearm can stand up; the forearm swings from the elbow with the hand trailing it. The arm winds up before it
    // rises, goes a little too far and settles; the swings die away, and on the way down the elbow stays bent
    // until the arm is nearly at her side (it never passes through sticking straight out).
    const rise = t / 0.85, fall = (t - (length - 0.75)) / 0.75;      // an unhurried lift: it used to snap up in 0.2 s
    // coming down, the arm lowers still turned and bent, and only untwists as it reaches her side: untwisting
    // while raised swings the bent forearm out at the viewer and leaves the arm sticking straight out sideways
    const raised = windUp(rise) * (1 - smooth(fall / 0.8));
    // (both settled late, the bent forearm stuck out sideways at hip height for the last quarter second)
    const turned = smooth(rise) * (1 - smooth((fall - 0.1) / 0.65));
    const bent = smooth(rise / 0.6) * (1 - smooth((fall - 0.15) / 0.6));
    const swing = smooth((t - 0.6) / 0.35) * smooth((length - 0.7 - t) / 0.4);
    const beat = 2 * Math.PI * 2.2 * (t - 0.6);
    return { weight: smooth(t / 0.12) * smooth((length - t) / 0.12), lift: 0,
             bones: { rightShoulder: [0, 0, 0.06 - 0.28 * raised],
                      // the elbow comes up to a little below her shoulder and forward, the forearm stands up: a
                      // friendly wave (lifting the arm out level with the shoulder looked stiff and took more room)
                      rightUpperArm: [0.06 * (1 - raised) - 0.25 * raised, 0.6 * raised, 1.3 - 0.8 * raised, -Math.PI / 2 * turned],
                      rightLowerArm: [0, 0.3 + 1.45 * bent + 0.35 * swing * Math.sin(beat), 0],
                      rightHand: [0.06, 0, 0.14 * (1 - bent) + 0.35 * swing * Math.sin(beat - 0.9)],
                      chest: [0, 0, 0.05 * raised], spine: [0, 0, 0.03 * raised], head: [0, 0, 0.09 * raised] },
             // her hand opens as the forearm comes up, and the fingers trail each swing a moment behind the palm
             hands: { right: mixHand(HANDS.relaxed, { ...HANDS.open, curl: HANDS.open.curl.map(c => c + 0.3 * swing * Math.sin(beat - 1.7)) }, bent) } };
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
                      spine: [-0.08, 0, 0], chest: [-0.08, 0, 0], head: [-0.15, 0, 0] },
             hands: { left: HANDS.splay, right: HANDS.splay } };       // fingers stretched wide, too
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
                      // fitted on her model: her fingers across her open mouth (her forearm used to cover it, the hand out past her cheek)
                      rightUpperArm: [-0.59, 0.5, 1.05, -0.08], rightLowerArm: [0, 2.23, 0, 0.21], rightHand: [-0.75, -0.1, 0.3],
                      chest: [-0.1 * wide + 0.06 * sag, 0, 0], spine: [-0.04 * wide + 0.05 * sag, 0, 0],
                      neck: [-0.05 * wide + 0.05 * sag, 0, 0], head: [-0.1 * wide + 0.12 * sag, 0.12, -0.04] }, side),
             // the hand over her mouth with its fingers together; the other one clenches a little as she yawns
             hands: otherHands({ right: HANDS.flat, left: mixHand(HANDS.relaxed, HANDS.loose, wide) }, side),
             mouth: 0.85 * wide, eyes: smooth((t - 0.8) / 0.35) * (1 - smooth((t - 2.5) / 0.4)),
             face: { relaxed: 0.6 * sag } };
  }
  if (name === 'tuckHair') {                    // a strand of hair brushed back behind her ear, head yielding into her hand
    // Her head tips toward the hand first (anticipation); the elbow leads the reach and the forearm folds up after it;
    // her fingertips land at her temple and sweep slowly back behind her ear while her head leans into them; a beat
    // and a small smile; then the elbow drops first, the wrist trails it, and her fingers relax last.
    const up = smooth((t - 0.12) / 0.75) * (1 - smooth((t - 1.85) / 0.95));
    const fold = smooth((t - 0.3) / 0.55);                                   // the forearm folds up after the elbow
    const sweep = smooth((t - 0.9) / 0.5);                                   // temple → behind her ear
    const yield_ = smooth(t / 0.3) * (1 - smooth((t - 1.75) / 0.9));         // her head leaning toward the hand
    const lean = sweep * (1 - smooth((t - 1.6) / 0.7));                      // and further into it during the sweep
    const mix = (a, b) => a + (b - a) * sweep;
    const tuck = smooth((t - 0.95) / 0.35) * (1 - smooth((t - 2.0) / 0.9));  // fingers hooking the strand, then letting go
    // her head, neck and chest lead: they blend in on their own weight, from the start and never the other way
    // first; her arm follows without swinging away from her cheek
    const lead = smooth(t / 0.25) * (1 - smooth((t - 1.85) / 0.95));
    return { weight: up, lift: 0, weights: { head: lead, neck: lead, chest: lead },
             bones: mirrorSide({
               rightShoulder: [0, 0, 0.06 - 0.08 * up],
               // on the way down the elbow drops close by her side (not out sideways through a T-pose) and the
               // forearm unfolds after it
               rightUpperArm: [mix(-0.85, -0.8), 0.25, mix(0.8, 0.75), mix(-0.6, -0.75)],
               rightLowerArm: [0, 1.6 + 0.8 * fold, 0],          // 2.5: folded as far as an elbow goes
               rightHand: [mix(0, 0.25), 0, mix(0.35, 0.2)],
               chest: [0, -0.03 * lean, 0.02 * yield_],
               neck: [0.02 * yield_, -0.04 * lean, 0.05 * yield_ + 0.03 * lean],
               head: [0.04 * yield_, -0.09 * lean, 0.09 * yield_ + 0.06 * lean] }, side),
             hands: otherHands({ right: mixHand(HANDS.relaxed, mixHand({ curl: [0.12, 0.15, 0.25, 0.3], spread: 0.1, thumb: 0.8 },
                                                                    { curl: [0.2, 0.22, 0.32, 0.38], spread: 0.05, thumb: 0.9 }, tuck),
                                                smooth((t - 0.2) / 0.5) * (1 - smooth((t - 2.3) / 0.6))) }, side),
             // a glance down and aside while she does it, then back up at you with a small smile
             look: [-0.25 * side * yield_, -0.15 * yield_ * (1 - sweep)],
             face: { happy: 0.3 * smooth((t - 1.35) / 0.35) * smooth((GESTURES.tuckHair - t) / 0.7) } };
  }
  if (name === 'doze') {                         // late at night: she nods off for a moment and jerks awake
    // Her lids get heavy and her head sinks, slowly and then heavier; halfway it catches itself a little and goes on
    // sinking; then she starts awake: her chest first, then her neck, then her head comes up, a touch past upright,
    // eyes open at once, two quick blinks, a small shake of the head and a sheepish little smile.
    const L = GESTURES.doze, WAKE = 2.7;
    const on = smooth(t / 0.5) * smooth((L - t) / 0.8);
    const sinking = smooth(t / WAKE) ** 1.4 - 0.12 * Math.sin(Math.PI * Math.min(1, Math.max(0, (t - 1.3) / 0.5)));
    // each part wakes a moment after the one below it, and goes a little past upright before it settles
    const part = late => t < WAKE ? sinking : sinking * (1 - overshoot((t - WAKE - late) / 0.28));
    const chest = part(0), neck = part(0.05), head = part(0.1);
    const awake = smooth((t - WAKE) / 0.12);
    const blink = x => Math.max(0, 1 - Math.abs(t - x) / 0.07);              // two quick blinks after waking
    const shake = smooth((t - WAKE - 0.4) / 0.2) * Math.exp(-3 * Math.max(0, t - WAKE - 0.5)) * Math.sin(2 * Math.PI * 2.4 * (t - WAKE - 0.4));
    // (added on top of whatever she is doing: standing, sitting on the floor or on a window keep their own pose)
    return { weight: on, lift: 0, ownBlinks: true, bones: {},
             adds: { spine: [0.03 * chest, 0, 0], chest: [0.08 * chest, 0, 0],
                      leftShoulder: [0, 0, 0.04 * chest], rightShoulder: [0, 0, -0.04 * chest],     // shoulders slack
                      neck: [0.17 * neck, 0.04 * shake, 0], head: [0.36 * head, 0.12 * shake, 0.05 * head] },
             eyes: Math.max(t < WAKE ? smooth((t - 0.3) / 1.9) : 1 - awake, blink(WAKE + 0.35), blink(WAKE + 0.6)),
             alert: awake * (1 - smooth((t - WAKE - 1.2) / 1.0)),          // wide awake a moment: no heavy lids
             look: [0, -0.35 * (t < WAKE ? sinking : 1 - awake)],
             face: { relaxed: 0.6 * (t < WAKE ? sinking : 1 - awake), happy: 0.3 * smooth((t - WAKE - 0.7) / 0.4) * smooth((L - t) / 0.6) } };
  }
  if (name === 'almostSneeze') {                 // a sneeze coming... coming... and it doesn't
    // She goes still, her chin lifts and her chest fills as her eyes squint and a hand comes up under her nose; a
    // smaller second breath in; a frozen, uncertain beat (a tiny tremble); nothing. She lets the breath go, sags a
    // little with relief and a small smile; her elbow drops first, the wrist trails, the fingers reopen last.
    const L = GESTURES.almostSneeze;
    const up = smooth((t - 0.15) / 0.7) * (1 - smooth((t - 2.05) / 0.95));
    const lead = smooth(t / 0.3) * (1 - smooth((t - 2.3) / 1.0));           // head and chest lead, never the wrong way
    const breath = 0.72 * smooth((t - 0.25) / 0.6) + 0.28 * smooth((t - 1.05) / 0.25);   // two breaths in
    const held = breath * (1 - smooth((t - 1.65) / 0.45));                   // ...and let go
    const relief = smooth((t - 1.75) / 0.4) * (1 - smooth((t - 2.6) / 0.8));
    const tremble = smooth((t - 1.3) / 0.1) * (1 - smooth((t - 1.6) / 0.1)) * Math.sin(2 * Math.PI * 9 * t);
    const trail = smooth((t - 2.1) / 0.4) * (1 - smooth((t - 2.6) / 0.5));
    return { weight: up, lift: 0.004 * held, weights: { head: lead, neck: lead, chest: lead, spine: lead },
             bones: mirrorSide({ rightShoulder: [0, 0, -0.05 * held], leftShoulder: [0, 0, 0.05 * held],
                      rightUpperArm: [-0.6, 0.55, 1.25, -0.08], rightLowerArm: [0, 2.4, 0, 0.21],
                      rightHand: [-0.7 + 0.5 * trail, -0.1, 0.4],
                      spine: [-0.03 * held + 0.03 * relief, 0, 0], chest: [-0.07 * held + 0.05 * relief, 0, 0],
                      neck: [-0.09 * held + 0.03 * relief, 0, 0], head: [-0.25 * held + 0.06 * relief + 0.01 * tremble, 0.08 * held, 0] }, side),
             // a cupped hand over her nose, fingers together; it opens again last
             hands: otherHands({ right: mixHand(HANDS.relaxed, { curl: [0.45, 0.5, 0.6, 0.75], spread: 0, thumb: 1.1 },
                                                smooth((t - 0.2) / 0.5) * (1 - smooth((t - 2.6) / 0.8))) }, side),
             eyes: 0.8 * held, mouth: 0.22 * held,
             look: [0, 0.2 * held],
             face: { relaxed: 0.5 * relief, happy: 0.3 * smooth((t - 2.0) / 0.4) * smooth((L - t) / 0.7) } };
  }
  if (name === 'crossAnkles') {                  // sitting on a window: she crosses her ankles a while, then swings again
    // Her legs' swing dies away and her chest leans back a touch (anticipation); one knee lifts a little so its foot
    // clears the other, the thigh turns in and the foot comes over in front of the other ankle, the toes following a
    // moment later; she rests like that, wiggling the toes once; then uncrosses the same way back (lifting to clear
    // again) and her legs start swinging. Added on top of her sitting pose (fitted on her model by measuring her
    // ankles: the thigh turned about its length swings the foot across with the knee staying put).
    const L = GESTURES.crossAnkles, OUT = L - 1.2;                         // uncrossing starts here
    const c = smooth((t - 0.3) / 0.7) * (1 - smooth((t - OUT) / 0.8));     // crossed (0…1)
    const toes = smooth((t - 0.4) / 0.7) * (1 - smooth((t - OUT - 0.1) / 0.8));
    const clear = Math.sin(Math.PI * Math.min(1, Math.max(0, (t - 0.3) / 0.7))) + Math.sin(Math.PI * Math.min(1, Math.max(0, (t - OUT) / 0.8)));
    const wiggle = Math.sin(Math.PI * Math.min(1, Math.max(0, (t - 3.6) / 0.6)));
    const brace = Math.sin(Math.PI * Math.min(1, Math.max(0, t / 0.6))) + Math.sin(Math.PI * Math.min(1, Math.max(0, (t - OUT + 0.1) / 0.6)));
    return { weight: smooth(t / 0.2) * smooth((L - t) / 0.2), lift: 0, bones: {},
             // her swing quiets before she crosses and comes back once she has uncrossed
             calm: smooth(t / 0.5) * (1 - smooth((t - L + 0.4) / 0.4)),
             adds: mirrorSide({ leftUpperLeg: [-0.05 * c - 0.08 * clear, 0.25 * c, -0.06 * c],
                                leftLowerLeg: [-0.15 * c, 0, 0], leftFoot: [0.1 * toes + 0.12 * wiggle, 0, 0],
                                chest: [-0.03 * brace, 0, 0] }, side) };
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
             hands: otherHands({ left: HANDS.loose }, side),
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
                      head: [0.04 * shrug, 0, 0.1 * flap(1.3, -0.5)] },
             // limp fingers flapping after the wrists
             hands: { left: { curl: HANDS.relaxed.curl.map(c => 0.7 * c + 0.6 * flap(5.3, -1.4)), spread: 0.4, thumb: 0.7 },
                      right: { curl: HANDS.relaxed.curl.map(c => 0.7 * c + 0.6 * flap(4.7, 0)), spread: 0.4, thumb: 0.7 } } };
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
             hands: otherHands({ right: mixHand(HANDS.relaxed, HANDS.splay, Math.max(0, lean)) }, side),
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
             hands: { left: HANDS.pinch, right: HANDS.pinch },
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
                      spine: [0.05, 0, 0], neck: [0.1, 0, 0], head: [0.22, 0, 0] },
             // hands closed on the hem, tightening with each tug
             hands: { left: mixHand(HANDS.pinch, HANDS.grip, tug), right: mixHand(HANDS.pinch, HANDS.grip, tug) },
             look: [0, -0.7] };
  }
  if (name === 'think') {                        // hand to her chin, eyes up and aside... then "got it", a small smile
    const aha = smooth((t - (length - 1.3)) / 0.35);
    return { weight: inOut, lift: 0,
             bones: { rightUpperArm: [-0.63, 0, 1.11, 0.21], rightLowerArm: [0, 2.5, 0, 0.28], rightHand: [0.06, 0.33, 0.05],   // as in the thinking pose
                      leftUpperArm: [-0.45, 0, -1.15], leftLowerArm: [0, -1.5, 0],
                      hips: [0, 0, 0.04 * side], spine: [0, 0, -0.04 * side],
                      neck: [-0.05, 0.08 * side * (1 - aha), 0], head: [-0.14 * (1 - aha), 0.2 * side * (1 - aha), -0.08 * side] },
             hands: { right: HANDS.chin, left: HANDS.loose },
             look: [0.55 * side * (1 - aha), 0.65 * (1 - aha)],
             face: { relaxed: 0.3 * (1 - aha), happy: 0.5 * aha * inOut } };
  }
  if (name === 'smile') {                        // a quiet smile, without an unvoiced giggle
    return { weight: inOut, lift: 0,
             bones: { head: [0, 0.1 * side, 0.26 * side], neck: [0, 0.04 * side, 0.08 * side],
                      chest: [0, 0, 0.06 * side], spine: [0, 0, 0.05 * side] },
             face: { happy: 0.45 * inOut } };
  }
  if (name === 'sigh') {                         // a big breath in (chest and shoulders up), and a long breath out: she slumps
    const inhale = Math.sin(Math.PI * smooth(t / 1.4)), out = smooth((t - 1.0) / 0.8) * smooth((length - t) / 0.6);
    return { weight: inOut, lift: 0.006 * inhale,
             bones: { chest: [-0.1 * inhale + 0.09 * out, 0, 0], spine: [-0.03 * inhale + 0.08 * out, 0, 0],
                      leftShoulder: [0, 0, -0.06 + 0.22 * inhale - 0.06 * out], rightShoulder: [0, 0, 0.06 - 0.22 * inhale + 0.06 * out],
                      neck: [-0.04 * inhale + 0.08 * out, 0, 0], head: [-0.1 * inhale + 0.22 * out, 0, 0.05 * side * out] },
             // her fingers close a little on the breath in and hang limp on the way out
             hands: Object.fromEntries(['left', 'right'].map(h => [h, { curl: HANDS.relaxed.curl.map(c => c * (1 + 0.5 * inhale - 0.35 * out)), spread: 0.15, thumb: 1 }])),
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
                      neck: [0, 0, 0.05 * sway], head: [-0.08 * sway, 0, -0.12 * sway] },
             hands: { left: HANDS.loose, right: HANDS.loose } };          // one hand holding the other
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
  // her arms swing back as she winds up and come up and out, elbows bent, as she leaves the ground (kept straight
  // and only lifted sideways, she hopped like a penguin); her fingers fly open, and her toes point while she is up
  const up = Math.max(0, lift / 0.12), bend = Math.max(0, crouch);
  const airHand = mixHand(HANDS.relaxed, HANDS.splay, up);
  return { weight: smooth((length - t) / 0.12), lift,
           bones: { leftUpperLeg: [-0.4 * crouch, 0, 0], rightUpperLeg: [-0.4 * crouch, 0, 0],
                    leftLowerLeg: [0.8 * bend, 0, 0], rightLowerLeg: [0.8 * bend, 0, 0],
                    leftFoot: [0.5 * up - 0.4 * bend, 0, 0], rightFoot: [0.5 * up - 0.4 * bend, 0, 0],
                    spine: [0.1 * late, 0, 0], chest: [0.06 * later, 0, 0], head: [0.1 * later - 0.12 * (lift / 0.12), 0, 0],
                    leftShoulder: [0, 0, -0.06 + 0.12 * up], rightShoulder: [0, 0, 0.06 - 0.12 * up],
                    leftUpperArm: [0.1 + 0.3 * bend - 0.5 * up, 0, -1.3 + 0.3 * up], rightUpperArm: [0.1 + 0.3 * bend - 0.5 * up, 0, 1.3 - 0.3 * up],
                    leftLowerArm: [0, -0.3 - 1.0 * up - 0.2 * bend, 0], rightLowerArm: [0, 0.3 + 1.0 * up + 0.2 * bend, 0] },
           hands: { left: airHand, right: airHand } };
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

/** She flinches at a window come up beside her (brace) only standing about with nothing else going on, and not
 *  again within this many seconds (windows opening one after another startle her once). */
export const STARTLE_EVERY = 20;
export function mayStartle({ idle = false, busy = false, sinceLast = Infinity } = {}) {
  return idle && !busy && sinceLast >= STARTLE_EVERY;
}

// ── watching you type ──

/** While you type to her: how long after your last key she still watches the box, and when she glances aside once
 *  in a longer pause (giving you room to think instead of staring at you). Seconds. */
export const TYPING = { watch: 1.5, asideFrom: 6, asideTo: 8.2 };

/** Where her attention is while the text box is open: `since` seconds since your last key in it (null: nothing
 *  typed since it opened: an empty box is not typing). { down, aside, lean }: how much she looks down at the box
 *  (0…1), how much she glances aside (0…1, once a pause has gone on), how far she leans in (0…1). In between
 *  she looks at you. Each key brings her back to the box at once; her eyes get there first, her head after. */
export function typingEyeStep(keys, since) {
  return since == null || since >= 0.6 || since < 0 ? 0 : Math.min(0.25, Math.max(0, keys) * 0.015);
}

export function typingKeyCount(keys, since) {
  return since == null || since >= 0.6 ? 1 : keys + 1;
}

export function typingAttention(since, open = true) {
  if (!open || since == null || since < 0) return { down: 0, aside: 0, lean: 0 };
  const down = 1 - smooth((since - TYPING.watch) / 0.4);
  const aside = smooth((since - TYPING.asideFrom) / 0.5) * (1 - smooth((since - TYPING.asideTo + 0.6) / 0.6));
  // she leans in while you type and sits back slowly after: her chest lets go over most of a second
  return { down, aside, lean: 1 - smooth((since - TYPING.watch) / 0.9) };
}

// ── trying to catch the mouse pointer ──

/** The pointer beside her, within reach, still for `dwell` s: she reaches for it once (`reach` s: eyes on it, arm
 *  out, slowing just short of it, a curious hold); moved away meanwhile she follows it with her forearm for at most
 *  `follow` s and gives up. She lets go over `back` s. Not again for `every` s, nor before the pointer has left
 *  and come back. Arm lengths: `near`…`far` of her arm from her shoulder counts as within reach. */
export const CATCH = { dwell: 0.8, reach: 1.6, follow: 0.15, back: 1.0, every: 90, near: 0.45, far: 1.15, short: 0.06 };

/** Is the pointer where she could reach for it? `rel`: pointer minus her shoulder (units, x to her side: positive
 *  away from her body), `arm`: her arm's length. Beside her (not over her body), at about her arm's height. */
export function inReach(rel, arm) {
  const d = Math.hypot(rel[0], rel[1]) / arm;
  return rel[0] > 0.2 * arm && d >= CATCH.near && d <= CATCH.far && rel[1] < 0.6 * arm && rel[1] > -0.9 * arm;
}

/** Where her hand goes: toward the pointer from her shoulder, stopping `short` of it (she doesn't quite touch it)
 *  and never further than 92% of her arm. `shoulder`, `pointer`: [x, y]. */
export function reachPoint(shoulder, pointer, arm) {
  const dx = pointer[0] - shoulder[0], dy = pointer[1] - shoulder[1], d = Math.hypot(dx, dy) || 1;
  const go = Math.max(0, Math.min(0.92 * arm, d - CATCH.short));
  return [shoulder[0] + dx / d * go, shoulder[1] + dy / d * go];
}

/** One step of her trying to catch the pointer. `prev` null starts afresh; `near`: inReach now; `moved`: the
 *  pointer moved just now (not her: her own moving doesn't count); `free`: standing about with nothing going on.
 *  { phase: 'off' | 'dwell' | 'reach' | 'escape' | 'back', t (seconds in it), since (since her last try), away (the
 *  pointer has left since), from (her arm's weight when she started letting go), weight (her arm, 0…1), track (her
 *  hand still follows the pointer), point (0…1: her index finger out), look (0…1: her eyes and head on it), face }. */
export function catchStep(prev, { near = false, moved = false, free = false } = {}, dt) {
  const s = prev ? { ...prev } : { phase: 'off', t: 0, since: Infinity, away: true, from: 0 };
  s.since += dt;
  s.t += dt;
  if (!near) s.away = true;
  const go = (phase, from = 0) => Object.assign(s, { phase, t: 0, from, fromWeights: s.weights });
  if (s.phase === 'off' || s.phase === 'dwell') {
    const ready = near && free && s.away && s.since >= CATCH.every;
    if (!ready || moved) go(ready ? 'dwell' : 'off');
    else if (s.phase === 'off') go('dwell');
    else if (s.t >= CATCH.dwell) Object.assign(go('reach'), { since: 0, away: false, escaped: false });
  } else if (s.phase === 'reach') {
    const w = smooth((s.t - 0.25) / 0.85);
    if (!free) go('back', w);
    else if (moved && s.t > 0.25) s.escaped = !!go('escape', w);
    else if (s.t >= CATCH.reach) go('back', w);
  } else if (s.phase === 'escape' && (!free || s.t >= CATCH.follow)) go('back', s.from);
  else if (s.phase === 'back' && s.t >= CATCH.back) go('off');
  // what that looks like
  const reaching = s.phase === 'reach' ? smooth((s.t - 0.25) / 0.85) : 0;
  const letting = s.phase === 'escape' ? s.from : s.phase === 'back' ? s.from * (1 - smooth(s.t / CATCH.back)) : 0;
  s.weight = Math.max(reaching, letting);
  s.weights = s.phase === 'reach' ? armEntry(s.t - 0.25, 0.85)
    : s.phase === 'escape' ? s.fromWeights
    : s.phase === 'back' ? Object.fromEntries(Object.entries(armRelease(s.t, CATCH.back))
      .map(([part, w]) => [part, w * (s.fromWeights?.[part] ?? 1)])) : armEntry(0, 1);
  s.track = s.phase === 'reach' || s.phase === 'escape';
  s.point = s.phase === 'reach' ? smooth((s.t - 0.5) / 0.5) : s.phase === 'escape' ? 1 : s.phase === 'back' ? 1 - smooth(s.t / 0.6) : 0;
  s.look = s.phase === 'reach' || s.phase === 'escape' ? 1 : s.phase === 'back' ? 1 - smooth((s.t - 0.2) / 0.6) : 0;
  // a curious little smile while she holds it; it got away: a moment's surprise
  s.face = { happy: s.phase === 'reach' ? 0.3 * smooth((s.t - 1.0) / 0.3) : 0,
             surprised: s.phase === 'escape' || (s.phase === 'back' && s.escaped && s.t < 0.4) ? 0.4 : 0 };
  return s;
}

// ── a breath after a longer walk ──

/** A walk across the screen of at least `min` s that she finished (not stopped by you, not ending in a jump up or
 *  behind a window) leaves her with one fuller breath, `length` s long. */
export const SETTLE = { min: 4, length: 2.8 };

/** Does this walk (`walk`: { trip, cut, then, hide }) that just ended after `walked` seconds earn a settling breath? */
export function settles(walk, walked) {
  return !!walk && !!walk.trip && !walk.cut && walk.then == null && !walk.hide && walked >= SETTLE.min;
}

/** The settling breath, `s` s after she stopped: her chest opens, the spine a moment after it and her head lifts
 *  a little last; then a slow breath out, her arms easing a touch away from her sides, her head trailing; and back
 *  into her ordinary breathing. { bones (added to her pose), idle (0…1: how much of her ordinary breath goes on
 *  meanwhile, so the two don't add up) }. Mild: settling, not out of breath. */
export function settleBreath(s) {
  if (s == null || s < 0 || s >= SETTLE.length) return { bones: {}, idle: 1 };
  const part = late => smooth((s - 0.25 - late) / 0.6) * (1 - smooth((s - 0.85 - late) / 1.25));
  const chest = part(0), spine = part(0.08), head = part(0.18);
  const soften = smooth((s - 0.9) / 0.5) * (1 - smooth((s - 1.8) / 0.9));
  return { idle: 1 - 0.8 * smooth(s / 0.3) * (1 - smooth((s - 2.1) / 0.7)),
           bones: { chest: [-0.045 * chest, 0, 0], spine: [-0.02 * spine, 0, 0], neck: [-0.015 * head, 0, 0], head: [-0.03 * head, 0, 0],
                    leftShoulder: [0, 0, 0.03 * chest], rightShoulder: [0, 0, -0.03 * chest],
                    leftUpperArm: [0, 0, 0.04 * soften], rightUpperArm: [0, 0, -0.04 * soften] } };
}

// ── tapped ──

/** A click on her: the reaction lasts `length` s; clicks closer together than `every` s don't start it again. */
export const TAP = { length: 0.8, every: 1.5 };

/** `s` s after you clicked her: angles added to her pose ({} once over). A quick blink (avatar.js) and her chest
 *  gives a little backward, her neck and head trailing it; her chest comes back and her head a touch forward,
 *  curious; a small tilt of the head (`side` ±1) as she settles into listening. Upper body only: her legs stay. */
export function tapMotion(s, side = 1) {
  if (s == null || s < 0 || s >= TAP.length) return {};
  const give = smooth(s / 0.08) * (1 - smooth((s - 0.18) / 0.22));
  const trail = smooth((s - 0.06) / 0.12) * (1 - smooth((s - 0.22) / 0.22));
  const forward = smooth((s - 0.2) / 0.2) * (1 - smooth((s - 0.45) / 0.35));
  const tilt = smooth((s - 0.35) / 0.2) * (1 - smooth((s - 0.55) / 0.25));
  const hitch = smooth(s / 0.05) * (1 - smooth((s - 0.15) / 0.12));
  return { bones: { spine: [-0.015 * give, 0, 0], chest: [-0.07 * give + 0.012 * forward, 0, 0],
           neck: [-0.02 * trail + 0.01 * forward, 0, 0.015 * side * tilt],
           head: [-0.06 * trail + 0.05 * forward, 0, 0.07 * side * tilt],
           leftShoulder: [0, 0, 0.05 * hitch], rightShoulder: [0, 0, -0.05 * hitch] },
           face: { surprised: 0.3 * smooth(s / 0.04) * (1 - smooth((s - 0.25) / 0.1)), happy: 0.2 * forward } };
}

// ── breaking off a fidget ──

/** How long breaking off a fidget takes (seconds): her eyes and head are yours at once, her hands settle last. */
export const CUT_S = 0.85;
// A hand at her face first moves a little forward, then comes down with the elbow folded.
const AT_FACE = new Set(['tuckHair', 'almostSneeze', 'yawn']);
// when each part lets go after the cut: [delay, seconds]. Eyes first, then head and neck, then the body; the arm
// from the shoulder out, the fingers last
const LET_GO = { head: [0.04, 0.2], neck: [0.06, 0.22], chest: [0.12, 0.3], spine: [0.15, 0.35], hips: [0.15, 0.4],
                 Shoulder: [0.1, 0.35], UpperArm: [0.1, 0.4], LowerArm: [0.18, 0.4], Hand: [0.28, 0.4],
                 UpperLeg: [0.1, 0.5], LowerLeg: [0.15, 0.5], Foot: [0.2, 0.5], fingers: [0.4, 0.4] };
/** A fidget `s` seconds after it was broken off (something happened), from what it would be doing now (`act`,
 *  from gesture()). Instead of everything fading at once, she lets go in order: her eyes come to you at once
 *  (whatever shut them opens within 0.12 s), head and neck follow, then her chest; her arms come down from the
 *  shoulder out with the fingers last, and a hand at her face first comes away from it (AT_FACE). Nodding off she
 *  wakes from the chest up. Every bone gets its own weight (`weights`); `adds` are scaled per bone already
 *  (`addWeight`); `handWeight` is for her fingers. null once it is over. */
export function cutShort(act, name, s) {
  if (!act || s >= CUT_S) return null;
  const order = LET_GO;
  const arms = armRelease(s - 0.15, CUT_S - 0.15);
  const left = ([delay, seconds]) => 1 - smooth((s - delay) / seconds);
  const part = bone => order[bone] || order[bone.replace(/^(left|right)/, '')] || order.chest;
  const release = bone => arms[bone.replace(/^(left|right)/, '')] ?? left(part(bone));
  const weights = {};
  for (const bone of new Set([...Object.keys(act.bones || {}), ...Object.keys(act.weights || {})]))
    weights[bone] = (act.weights?.[bone] ?? act.weight) * release(bone);
  const adds = Object.fromEntries(Object.entries(act.adds || {}).map(([bone, v]) => {
    // nodding off she wakes from the chest up: chest, then the neck a moment later, then her head
    const r = name === 'doze' ? left([{ spine: 0, chest: 0, neck: 0.06, head: 0.12 }[bone] ?? 0, 0.3]) : release(bone);
    return [bone, v.map(x => x * r)];
  }));
  const bones = { ...act.bones };
  if (AT_FACE.has(name)) {
    const away = -0.1 * smooth(s / 0.075) * (1 - smooth((s - 0.15) / 0.15));
    for (const bone of Object.keys(act.bones || {})) if (bone.endsWith('UpperArm'))
      bones[bone] = act.bones[bone].map((angle, i) => angle + (i === 0 ? away : 0));
  }
  const body = left(order.chest), eyesOpen = left([0, 0.12]);
  const ik = act.ik && { ...act.ik, weights: Object.fromEntries(Object.entries(arms).map(([k, v]) => [k, v * (act.ik.weights?.[k] ?? 1)])) };
  return { ...act, bones, weights, adds, ik, addWeight: act.weight, weight: act.weight * body,
           handWeight: (act.handWeight ?? act.weight) * arms.fingers, lift: (act.lift || 0) * left(order.spine),
           eyes: (act.eyes || 0) * eyesOpen, mouth: (act.mouth || 0) * eyesOpen, ownBlinks: false,   // her blinks are hers again
           // woken from a doze she is wide awake a moment: no heavy lids
           alert: name === 'doze' ? 1 / Math.max(0.05, act.weight * body) : act.alert };
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

/** How closed her eyes are at time t for a blink that began at `start`: 0, quickly up to 1, more slowly back to 0.
 *  `slow` (1 or more) stretches it: tired, her blinks are heavier and her eyes open more slowly. */
export function blinkWeight(t, start, slow = 1) {
  const x = (t - start) / slow;
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
           hands: { right: HANDS.grip },
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
export function bobMotion(beats, amount, bpm, parts = { head: 1, shoulders: 1, body: 1 }) {
  const a = Math.max(0, Math.min(1, amount));
  const every = bpm > 140 ? 2 : 1;
  const nb = beats / every;
  const dipAt = beat => {
    let d = beat - Math.floor(beat) - 0.06;                  // the dip is deepest just after the beat
    if (d > 0.5) d -= 1;
    return Math.abs(d) < 0.3 ? Math.cos(Math.PI * d / 0.6) ** 2 : 0;
  };
  const dip = dipAt(nb);
  const lead = dipAt(nb + 0.08 * bpm / 60 / every);          // her shoulders lead her head by 80 ms
  const sway = Math.sin(Math.PI * nb);
  const h = a * parts.head, sh = a * parts.shoulders, b = a * parts.body;   // who has joined in so far (grooveStep)
  return {
    head: [0.14 * h * dip, 0, 0.035 * h * sway], neck: [0.04 * h * dip, 0, 0.02 * h * sway],
    chest: [0.02 * b * dip, 0, -0.03 * b * sway], spine: [0.01 * b * dip, 0, -0.02 * b * sway],
    hips: [0, 0, 0.015 * b * sway],
    leftShoulder: [0, 0, -0.05 * sh * lead], rightShoulder: [0, 0, 0.05 * sh * lead],
    lift: 0.006 * b * (1 - dip),                           // up on the off-beat, feet down on the beat
  };
}

/** How she gets into music: { on (seconds she has been bobbing), head, shoulders, body (0…1: who has joined in),
 *  depth (0.75…1: how into it she is just now), after (seconds since a song she was into stopped, or null) }.
 *  Her head joins after a second of steady beat, her shoulders half a second later, her body after that; once
 *  she's in it she goes fuller and lighter over a phrase of about 12 s. When the beat stops after at least
 *  GROOVE.into seconds she gives a short puzzled tilt (afterMusic); the music coming back, or her becoming busy
 *  (`free` false: walking, carried, a gesture, at the piano, a duet), cancels that. `grooving`: the beat is there
 *  and she may bob (avatar.js decides that). */
export const GROOVE = { into: 8, after: 1.4, forget: 3 };
export function grooveStep(prev, grooving, dt, musicGone = true, free = true) {
  const s = prev ? { ...prev } : { on: 0, off: 0, was: false, after: null, head: 0, shoulders: 0, body: 0, depth: 0.875 };
  if (grooving) {
    if (s.off > GROOVE.forget) s.on = 0;                     // a while without: she gets into it afresh
    [s.on, s.off, s.after] = [s.on + dt, 0, null];
    // (only while she bobs: fading out, everyone who joined in stays in until it's gone)
    s.head = smooth((s.on - 1) / 0.8);
    s.shoulders = smooth((s.on - 1.5) / 0.8);
    s.body = smooth((s.on - 1.8) / 0.8);
    s.depth = 0.875 + 0.125 * Math.sin(2 * Math.PI * s.on / 12) * smooth((s.on - 6) / 4);
  } else {
    // a song she was into stopped (not just her walking off or doing something else)
    if (s.was && musicGone && free && s.on >= GROOVE.into) s.after = 0;
    else if (s.after != null && (s.after += dt) >= GROOVE.after) s.after = null;
    // the music back (while she can't bob: walking, at the piano) or something else to do: no "huh?"
    if (!musicGone || !free) s.after = null;
    s.off += dt;
  }
  s.was = grooving;
  return s;
}

/** The music she was into stopped (`after` seconds ago, grooveStep): her last dip trails off, then a small
 *  sideways tilt of the head and a glance up, "huh?", and she lets it go. Angles added to her pose; {} after. */
export function afterMusic(after) {
  if (after == null || after < 0 || after >= GROOVE.after) return {};
  const tilt = smooth((after - 0.5) / 0.3) * (1 - smooth((after - 1.0) / 0.4));
  return { head: [-0.03 * tilt, 0.04 * tilt, 0.07 * tilt], neck: [0, 0, 0.025 * tilt], look: [0.15 * tilt, 0.12 * tilt] };
}

// ── playing the piano (Spotify plays piano music: ui.set_piano; the piano itself is built in avatar.js) ──
//
// Staged three-quarters, as a concert audience sees a pianist: she turns to her left (the viewer's right) and sits at
// a small grand piano, so you see her face, her hands on the keys and the open lid. (Turned the other way, the
// piano's long straight bass side came at the viewer and hid her.) Her arms are placed by IK in avatar.js on the keys these functions choose; the
// rest of her (sitting, leaning, her head) are bone angles from here. Every distance is measured from her own body
// (pianoLayout), so the piano fits the built-in figure and any VRM.

export const PIANO = { yaw: 0.85, keys: 22, bpm: 92, view: 0.3 };

/** Where the bench and the keys go for her body. `m`: her measurements standing, from the rig: hip (height of her
 *  hip joints), thigh, shin (lengths), shoulder (height of her shoulder joints above her hip joints), upperArm.
 *  Returns heights and distances in her own frame (she faces +z): how far she sinks to sit (lift, negative), the
 *  bench top, and the front edge, height and width of the keys. */
export function pianoLayout(m) {
  const seatHip = m.shin * 1.02;                              // thighs level, feet flat on the floor
  const lift = seatHip - m.hip;
  const shoulder = seatHip + m.shoulder * 0.96;               // sitting she leans in a little
  return {
    lift,
    benchY: seatHip - 0.035 * (m.hip / 0.5),
    benchZ: -0.02,
    keyY: shoulder - m.upperArm * 1.08,                       // the keys a little below her elbows
    keyZ: m.thigh * 0.95,                                     // the front of the keys just past her knees
    keyWidth: m.thigh * 2.2,
  };
}

/** Coming in and going out, `since` seconds after the music started (on) or stopped (off). Each part 0…1 and they
 *  overlap, as a person moves: the piano grows in first, she turns as it appears, sits while still turning, and
 *  her hands go to the keys once she's down. Going: hands up first, she stands, turns back, the piano goes last. */
export function pianoStage(since, on) {
  const part = (from, to) => smooth(Math.max(0, Math.min(1, (since - from) / (to - from))));
  if (on) return { show: part(0, 0.45), turn: part(0.15, 0.8), sit: part(0.45, 1.35), hands: part(1.15, 1.75) };
  return { hands: 1 - part(0, 0.45), sit: 1 - part(0.3, 1.1), turn: 1 - part(0.7, 1.3), show: 1 - part(1.0, 1.45) };
}

/** The music she plays, as a pianist moves to it. `beats` is the music's beat clock (or null: her own time at
 *  PIANO.bpm); the same moment always gives the same result.
 *
 *  Taken from how real pianists move (and how anime piano scenes show it): the arm's weight goes into each accent,
 *  so the wrist dips at the note and comes back up in a small circle; the hand rolls a little on the forearm from
 *  note to note; a hand travelling along the keys rises in an arc. The music comes in four-bar phrases that build
 *  and fall back: she leans in as it builds, and at the end of each phrase both hands lift off the keys, the wrists
 *  trailing, her head comes up for a breath, and she sinks back in for the next one.
 *
 *  Per hand: x on the keyboard (-1 low … 1 high), press (0…1, how far the key is down), lift (how far the hand is
 *  off the keys, 0…1), dip (the wrist dropping into the note), roll (the forearm's turn, -1…1), finger (0…3).
 *  For her body: intensity (0…1 over the phrase), lean (into the keys), toward (sideways, toward the high notes),
 *  sway, nod, breath (the lift at a phrase end), and the moments dreamy (eyes closed) and glance (she looks at you). */
export function pianoPerformance(t, beats = null) {
  const b = beats ?? t * PIANO.bpm / 60;
  const frac = x => x - Math.floor(x);
  const clamp01 = x => Math.max(0, Math.min(1, x));
  // the right hand's melody over a four-bar phrase, in eighth notes: steps up the keyboard (0 = rest)
  const TUNE = [3, 0, 5, 6, 5, 4, 3, 2,  1, 0, 2, 3, 5, 6, 8, 0,  8, 7, 6, 5, 6, 7, 8, 10,  9, 8, 6, 5, 3, 0, 0, 0];
  // the left hand rolls broken chords: low, fifth, octave, fifth, one chord a bar
  const ROOTS = [0, 3, 4, 0], ROLL = [0, 2, 4, 2];
  const e = b * 2, n = Math.floor(e), i = ((n % 32) + 32) % 32, p = frac(e);
  const bar = Math.floor(i / 8), inBar = i % 8;
  const strike = q => q < 0 ? 0 : q < 0.08 ? smooth(q / 0.08) : Math.max(0, 1 - smooth((q - 0.08) / 0.6));
  // the phrase: builds over the first three bars, falls back in the fourth; the last half-bar is the breath
  const phraseP = (i + p) / 32;
  const intensity = 0.35 + 0.65 * Math.sin(Math.PI * Math.min(1, phraseP / 0.85)) ** 1.5;
  const breath = smooth(clamp01((phraseP - 0.9) / 0.06)) * (1 - smooth(clamp01((phraseP - 0.97) / 0.03)));

  // a hand gliding between its notes: it leaves late (holding the note), travels on an arc, lands with the beat
  const glide = (noteAt, lowX, step) => {
    const here = noteAt(i), there = noteAt((i + 1) % 32);
    const move = smooth(clamp01((p - 0.6) / 0.4));
    const xHere = lowX + step * here, xThere = lowX + step * there;
    return { x: xHere + (xThere - xHere) * move, arc: Math.sin(Math.PI * move) * Math.min(1, Math.abs(xThere - xHere) * 3) };
  };
  const lastNote = k => { let at = k, c = 0; while (!TUNE[at] && c++ < 8) at = (at + 31) % 32; return TUNE[at]; };
  const R = glide(k => lastNote(k) - 1, 0.0, 0.09);
  const L = glide(k => ROOTS[Math.floor(k / 8)] + ROLL[k % 4], -0.95, 0.055);
  const playsR = !!TUNE[i] && breath < 0.5, playsL = breath < 0.5;
  const pressR = playsR ? strike(p) : 0;
  const pressL = playsL ? strike(p) * (inBar === 0 ? 1 : 0.6) : 0;           // the bass note of each bar is the deepest
  // the wrist: drops into the note (deeper when the music is louder) and rises again, a small circle
  const dip = press => press * (0.5 + 0.5 * intensity);
  // between notes the hand stays near the keys; on a jump it arcs up; at the breath both hands lift off
  const liftR = 0.25 * R.arc + 0.9 * breath + (TUNE[i] ? 0 : 0.15 * (1 - breath));
  const liftL = 0.15 * L.arc + 0.75 * breath;
  // the forearm rolls toward the next note: thumb side going down the keys, little-finger side going up
  const rollR = Math.max(-1, Math.min(1, (R.x - (0.0 + 0.09 * (lastNote(i) - 1))) * 12)) * 0.6 + 0.2 * Math.sin(Math.PI * e);
  const rollL = 0.5 * Math.sin(Math.PI * (e + 0.5));

  // her moments: every ~20 s a few seconds with her eyes closed, and between them a glance at you
  const cycle = frac(t / 21);
  const window_ = (from, to) => smooth(clamp01((cycle - from) / 0.05)) * (1 - smooth(clamp01((cycle - to) / 0.05)));
  return {
    R: { x: R.x, press: pressR, lift: liftR, dip: dip(pressR), roll: rollR, finger: TUNE[i] ? TUNE[i] % 4 : 1 },
    L: { x: L.x, press: pressL, lift: liftL, dip: dip(pressL) * 0.8, roll: rollL, finger: ROLL[i % 4] === 0 ? 3 : ROLL[i % 4] === 4 ? 0 : 1 },
    intensity, breath,
    lean: 0.06 + 0.1 * intensity - 0.12 * breath,
    toward: 0.06 * (R.x - 0.3) + 0.03 * (L.x + 0.6),
    sway: 0.04 * Math.sin(2 * Math.PI * b / 8) * (0.5 + intensity),
    nod: 0.03 * strike(frac(b)) * intensity,
    dreamy: window_(0.35, 0.5), glance: window_(0.75, 0.86),
  };
}

/** Her body at the piano (not her arms: IK does those), for a stage and a moment of the performance: bone targets,
 *  blended in like a gesture. Sitting: thighs level, shins down, her back upright with a slight lean in toward the
 *  keys; her head bent to her hands, nodding on the beat, and turned back toward you when she glances. */
export function pianoBody(stage, perf) {
  const s = stage.sit, h = stage.hands;
  const g = perf ? perf.glance : 0, sway = perf ? perf.sway * h : 0, toward = perf ? perf.toward * h : 0;
  const lean = perf ? perf.lean * h : 0, breath = perf ? perf.breath * h : 0;
  // she leans in from the hips (her shoulders come over the keys, so her elbows can bend), toward the high notes,
  // and sits up at each breath with her head lifting; her head stays bent to her hands otherwise
  return {
    hips: [0.05 * s + 0.3 * lean, 0, 0],
    spine: [0.03 * s + 0.6 * lean, sway * 0.6, -toward * 0.6],
    chest: [0.02 * h + 0.3 * lean, sway, -toward],
    neck: [0.04 * h - 0.08 * breath, 0, 0],
    head: [((0.17 + (perf ? perf.nod : 0)) * (1 - 0.8 * g) - 0.3 * breath) * h, -PIANO.yaw * 0.75 * g, 0.06 * sway + 0.08 * g + 0.05 * breath],
    leftUpperLeg: [-1.5 * s, 0.08 * s, 0.02], rightUpperLeg: [-1.5 * s, -0.08 * s, -0.02],
    leftLowerLeg: [1.5 * s, 0, 0], rightLowerLeg: [1.5 * s, 0, 0],
  };
}

/** Which of `keys` white keys a hand at x (-1…1) is over: 0 at the low end. */
export function keyUnder(x, keys = PIANO.keys) {
  return Math.max(0, Math.min(keys - 1, Math.round((x + 1) / 2 * (keys - 1))));
}
