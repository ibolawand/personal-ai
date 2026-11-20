// Deterministic timing shared by the desktop scenes and their tests.
import { pianoStage, pianoBody } from './logic.mjs';

export const ACKNOWLEDGEMENTS = ['noteSaved', 'timerSaved', 'taskDone'];
const smooth = x => { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); };

export function acknowledgement(name, elapsed) {
  if (!ACKNOWLEDGEMENTS.includes(name) || elapsed < 0 || elapsed >= 2.4) return null;
  return { shown: smooth(elapsed / 0.3) * (1 - smooth((elapsed - 1.6) / 0.8)),
           lift: 0.07 * smooth(elapsed / 2.4), nod: 0.09 * Math.sin(Math.PI * smooth(elapsed / 0.7)) * (1 - smooth((elapsed - 0.7) / 0.2)) };
}

export function focusStage(elapsed, on, from = null) {
  const stage = pianoStage(elapsed, on);
  if (from) {
    for (const k of Object.keys(stage)) stage[k] = on ? from[k] + (1 - from[k]) * stage[k] : from[k] * stage[k];
  }
  for (const k of Object.keys(stage)) stage[k] = Math.max(0, Math.min(1, stage[k]));
  return stage;
}

export function writing(t) {
  const pause = smooth((t % 13 - 9) / 0.7) * (1 - smooth((t % 13 - 11.5) / 0.8));
  return { x: -0.06 + 0.018 * Math.sin(t * 5.5) + 0.015 * Math.sin(t * 0.7),
           z: 0.012 * Math.sin(t * 3.7), lift: 0.06 * pause, pause };
}

export function focusBody(stage, t) {
  const w = writing(t);
  return pianoBody(stage, { glance: w.pause * 0.5, sway: 0.005 * Math.sin(t * 0.8), toward: 0,
                           lean: 0.06 * (1 - w.pause), breath: 0, nod: 0 });
}

/** Gaze toward the speaker; occasional quiet nods rather than repeating a full gesture per line. */
export function conversationMotion(t, speaker, side = 1) {
  const listening = speaker === 'claude';
  const active = listening || speaker === 'aria';
  const nod = listening ? 0.045 * Math.max(0, Math.sin(t * 1.45)) ** 8 : 0;
  return { gaze: active ? (side >= 0 ? 1 : -1) * (listening ? 0.85 : 0.2) : 0, nod };
}

/** Additive conversational poses. Sparse movements with preparation, a hold and
 * a slower release; elapsed is relative to the current conversation state.
 * Voice activity controls strength, never the speed of a gesture. */
export function activeBody(state, elapsed, activity = 0, variation = 0) {
  // A repeatable variation per turn: different pace, size and leading hand.
  // Keep time continuous within a turn, including the quiet gaps between cycles.
  const v = Math.abs(Math.floor(variation)) % 5;
  const pace = [1, 0.91, 1.07, 0.96, 1.12][v];
  const size = [1, 0.82, 0.94, 0.88, 0.76][v];
  const t = Math.max(0, elapsed) * pace, a = Math.max(0, Math.min(1, activity)) * size;
  const enter = smooth(t / 0.7);
  const pulse = (at, rise, hold, fall) => smooth(at / rise) * (1 - smooth((at - rise - hold) / fall));
  if (state === 'listening') {
    // leaning in a little while you talk; her nods come at your pauses (listenStep, listenNod), not on a clock
    return { chest: [0.025 * a * enter, 0, 0] };
  }
  if (state === 'thinking') {
    const phase = t % 9.3;
    const consider = pulse(phase - 0.8, 1.1, 1.3, 1.6) * enter;
    // Keep the chin hand in place; only a small shift of the head and free shoulder.
    return { head: [0.025 * consider, -0.055 * consider, 0.035 * consider],
      leftShoulder: [0, 0, 0.045 * consider],
      leftHand: [0.06 * consider, 0, 0] };
  }
  if (state === 'speaking') {
    const cycle = Math.floor(t / 6.8), phase = t % 6.8;
    const side = (cycle + v) % 2 ? 'left' : 'right', sign = side === 'right' ? 1 : -1;
    const offer = pulse(phase - 0.35, 0.65, 0.65, 1.25) * a * enter;
    const wrist = pulse(phase - 0.55, 0.65, 0.5, 1.25) * a * enter;
    const settle = pulse(phase - 3.9, 0.4, 0.12, 0.8) * a * enter;
    return { [side + 'UpperArm']: [-0.16 * offer, 0, -sign * 0.06 * offer],
      [side + 'LowerArm']: [0, sign * 0.5 * offer, 0],
      [side + 'Hand']: [-0.1 * wrist, sign * 0.16 * wrist, 0],
      [side + 'Shoulder']: [0, 0, -sign * 0.035 * offer],
      chest: [0.025 * offer, sign * 0.035 * offer, 0],
      head: [0.045 * settle, 0, -sign * 0.035 * offer] };
  }
  return {};
}


// ── listening: a nod when you pause, not on a clock ──

/** How loud the microphone has to be to count as your voice (`on`), and quiet enough to count as a pause (`off`):
 *  in between it stays what it was. A pause after at least `bout` seconds of talking that lasts `pause` seconds
 *  gets an acknowledgement, at most once in `gap` seconds; one lasts `length` s. A pause over `forget` s ends what
 *  you were saying without one. */
export const LISTEN = { on: 0.025, off: 0.012, bout: 1.2, pause: 0.45, gap: 7, length: 0.95, forget: 1.5 };

/** One step of following your voice (`level`: the microphone, `dt` seconds): { talking, bout (seconds of talking
 *  so far, short gaps between words included), quiet (seconds of quiet), sinceNod, nod (seconds into an
 *  acknowledgement, or null), count (how many so far) }. `prev` null starts afresh. */
export function listenStep(prev, level, dt) {
  const s = prev ? { ...prev } : { talking: false, bout: 0, quiet: 0, sinceNod: Infinity, nod: null, count: 0 };
  s.sinceNod += dt;
  if (s.nod != null && (s.nod += dt) >= LISTEN.length) s.nod = null;
  s.talking = level > (s.talking ? LISTEN.off : LISTEN.on);
  if (s.talking) [s.bout, s.quiet] = [s.bout + dt, 0];
  else {
    s.quiet += dt;
    if (s.bout >= LISTEN.bout && s.quiet >= LISTEN.pause) {
      if (s.sinceNod >= LISTEN.gap && s.nod == null) [s.nod, s.sinceNod, s.count] = [0, 0, s.count + 1];
      s.bout = 0;                                     // (too soon after the last one: this pause goes by quietly)
    } else if (s.quiet >= LISTEN.forget) s.bout = 0;
  }
  return s;
}

/** While she isn't listening (thinking, speaking, a duet): what you were saying and a nod under way are dropped,
 *  but how many she gave and how long ago the last one was go on, so a quick back-and-forth doesn't get a nod
 *  every turn and they keep taking turns between a dip and a tilt. */
export function listenAway(s, dt) {
  return s && { ...s, talking: false, bout: 0, quiet: 0, nod: null, sinceNod: s.sinceNod + dt };
}

/** The acknowledgement `listenStep` started, as angles added to her pose: a small dip of her head (the neck a
 *  moment behind it, her shoulders softening last), or every other time a small tilt of the head. {} when none. */
export function listenNod(s) {
  if (!s || s.nod == null) return {};
  const at = s.nod, pulse = (x, rise, fall) => smooth(x / rise) * (1 - smooth((x - rise) / fall));
  const soften = pulse(at - 0.25, 0.25, 0.45);
  if (s.count % 2) {
    const dip = pulse(at, 0.18, 0.47), neck = pulse(at - 0.05, 0.18, 0.47);
    return { head: [0.08 * dip, 0, 0], neck: [0.03 * neck, 0, 0],
             leftShoulder: [0, 0, -0.02 * soften], rightShoulder: [0, 0, 0.02 * soften] };
  }
  const side = s.count % 4 ? -1 : 1, tilt = pulse(at, 0.3, 0.6), neck = pulse(at - 0.06, 0.3, 0.55);
  return { head: [0.02 * tilt, 0, 0.06 * side * tilt], neck: [0, 0, 0.02 * side * neck],
           leftShoulder: [0, 0, -0.015 * soften], rightShoulder: [0, 0, 0.015 * soften] };
}

/** Brief body-language cues on actual state changes. These don't infer sentiment
 * or interrupt audio: the controller still decides when a speaking turn ends. */
export function turnCue(from, to, elapsed) {
  const empty = { bones: {}, attention: 0 };
  if (from === to || elapsed < 0 || elapsed >= 2.2) return empty;
  const envelope = smooth(elapsed / 0.22) * (1 - smooth((elapsed - 0.65) / 1.55));
  if (to === 'speaking') {
    return { bones: { chest: [-0.035 * envelope, 0, 0],
      neck: [-0.018 * envelope, 0, 0], head: [-0.025 * envelope, 0, 0] }, attention: 0 };
  }
  if (from === 'speaking' && (to === 'listening' || to === 'idle')) {
    // Give the floor back: shoulders soften and her attention returns promptly.
    // A tiny tilt is attentive without suggesting agreement with what was said.
    return { bones: { head: [0.018 * envelope, 0, 0.045 * envelope],
      chest: [0.02 * envelope, 0, 0],
      leftShoulder: [0, 0, -0.025 * envelope],
      rightShoulder: [0, 0, 0.025 * envelope] }, attention: envelope };
  }
  return empty;
}

export const WINDOW_VISIT = { distance: 0.23, duration: 4.8, maxWalk: 1.8 };

/** Visible window edges in model units, relative to her centre. Stop outside the
 * window, within the desktop's travel bounds. Prefer a different window next. */
export function planWindowVisit(edges, room, random = 0, lastId = null) {
  const candidates = (edges || []).filter(e => Number.isFinite(e?.x) && (e.out === -1 || e.out === 1))
    .map(e => ({ ...e, dx: e.x + e.out * WINDOW_VISIT.distance }))
    .filter(e => room && e.dx >= -room.left && e.dx <= room.right && Math.abs(e.dx) <= WINDOW_VISIT.maxWalk);
  const fresh = candidates.filter(e => e.id !== lastId);
  const choices = fresh.length ? fresh : candidates;
  if (!choices.length) return null;
  const weights = choices.map(e => 1 / (0.5 + Math.abs(e.dx)));
  let pick = Math.max(0, Math.min(1, random)) * weights.reduce((a, b) => a + b, 0);
  return choices.find((e, i) => (pick -= weights[i]) < 0) || choices.at(-1);
}

/** Settle, reach, rest a palm on the edge, look up, then release. The reach is
 * solved against the real rig by the renderer; these are small body offsets. */
export function windowVisitMotion(elapsed, out = 1, cutElapsed = null) {
  if (elapsed < 0 || elapsed >= WINDOW_VISIT.duration) return null;
  const w = smooth((elapsed - 0.35) / 1.0) * (1 - smooth((elapsed - 3.35) / 1.1));
  const release = cutElapsed == null ? 1 : 1 - smooth(cutElapsed / 0.55);
  if (release === 0) return null;
  const weight = w * release;
  const glance = smooth((elapsed - 1.4) / 0.7) * (1 - smooth((elapsed - 2.9) / 0.6));
  return { weight, side: out === 1 ? 'right' : 'left',
    look: [-out * 0.6 * weight, (0.12 + 0.3 * glance) * weight],
    bones: { chest: [0, -out * 0.045 * weight, out * 0.025 * weight],
      neck: [-0.025 * glance * weight, -out * 0.035 * weight, 0],
      head: [-0.045 * glance * weight, -out * 0.06 * weight, out * 0.055 * weight] } };
}

export const CHARACTER_MOODS = ['curious', 'uncertain', 'focused', 'amused'];
/** Expression and recurring mannerism share one envelope. No sentiment is
 * inferred from volume: moods come from a known gesture/state or explicit cue. */
export function characterAccent(mood, strength = 1) {
  const w = Math.max(0, Math.min(1, strength));
  const face = { curious: 0, uncertain: 0, focused: 0, amused: 0 };
  if (!CHARACTER_MOODS.includes(mood)) return { face, bones: {} };
  face[mood] = w;
  const bones = mood === 'curious' ? { head: [0, 0, 0.055 * w], neck: [0, 0, 0.018 * w] }
    : mood === 'uncertain' ? { head: [0.025 * w, -0.035 * w, -0.07 * w], leftShoulder: [0, 0, 0.045 * w] }
    : mood === 'amused' ? {}
    : { head: [0.018 * w, 0, 0] };
  return { face, bones };
}

export function characterMood(state, gestureName) {
  if (state === 'thinking') return 'focused';
  if (['curious', 'lookAround', 'quietGlance'].includes(gestureName)) return 'curious';
  if (['smile', 'wave'].includes(gestureName)) return 'amused';
  if (gestureName === 'think') return 'uncertain';
  return null;
}

/** Resolve character moods on imported avatars. Prefer a custom expression;
 * otherwise mix restrained standard VRM presets, resetting them every frame.
 * Some VRM0 exporters keep the custom Surprised name capitalized. */
export function vrmCharacterExpressions(values, available) {
  const out = {};
  const supported = new Set(available);
  const resolve = name => supported.has(name) ? name : supported.has(name[0].toUpperCase() + name.slice(1)) ? name[0].toUpperCase() + name.slice(1) : null;
  const put = (name, weight) => {
    const actual = resolve(name);
    if (actual) out[actual] = Math.max(out[actual] || 0, Math.max(0, Math.min(1, weight || 0)));
  };
  for (const name of ['happy', 'relaxed', 'surprised', 'angry', 'sad', ...CHARACTER_MOODS]) put(name, values[name]);
  const fallback = {
    curious: { surprised: 0.16, relaxed: 0.06 },
    uncertain: { sad: 0.18, relaxed: 0.05 },
    focused: { angry: 0.12 },
    amused: { happy: 0.5, relaxed: 0.12 },
  };
  for (const mood of CHARACTER_MOODS) if (!resolve(mood)) {
    for (const [name, weight] of Object.entries(fallback[mood])) put(name, (values[mood] || 0) * weight);
  }
  return out;
}

/** The chin pose travels much farther than a conversational beat. Give the arm
 * time to arrive and to lower again, while her attention can change promptly. */
export function poseTransitionTime(state, previous, bone) {
  return (state === 'thinking' || previous === 'thinking') && /Shoulder|Arm|Hand/.test(bone) ? 0.75 : 0.3;
}

/** A small routine, advanced only on completion of the current movement.
 * No future action is queued outside this state, so cancellation discards it all. */
export function windowRoutineStep(phase, elapsed, { walking = false, gesturing = false, seated = false,
  restFor = 12, sitDown = false } = {}) {
  if (phase === 'notice' && elapsed >= 0.85) return { phase: 'approach', action: 'walk' };
  if (phase === 'approach' && !walking) return { phase: 'touch' };
  if (phase === 'touch' && elapsed >= WINDOW_VISIT.duration) return { phase: 'settle' };
  if (phase === 'settle' && elapsed >= 0.8) return { phase: 'reflect', action: 'glance' };
  if (phase === 'reflect' && !gesturing && elapsed > 0) return { phase: 'rest', action: sitDown ? 'sit' : null };
  if (phase === 'rest' && elapsed >= Math.max(8, restFor)) return seated ? { phase: 'rise', action: 'stand' } : { phase: 'done', action: 'depart' };
  if (phase === 'rise' && !seated) return { phase: 'done', action: 'depart' };
  return null;
}

/** Eyes find the destination before her feet move. Fade out before the walk's
 * own head-leading turn takes over. */
export function destinationNotice(elapsed, direction) {
  const weight = smooth(elapsed / 0.25) * (1 - smooth((elapsed - 0.55) / 0.3));
  return { weight, x: Math.sign(direction) * 0.7, y: 0.12 };
}

// She reaches forward with her elbow low, pointing from her wrist toward the pointer.
export function pointerReach(shoulder, side) {
  return { forward: 0.2, pole: [shoulder[0] + (side === 'left' ? 0.12 : -0.12), shoulder[1] - 0.35, shoulder[2] + 0.12] };
}

export function pointerDirection(wrist, pointer) {
  const direction = pointer.map((x, i) => x - wrist[i]);
  const length = Math.hypot(...direction);
  return length > 1e-6 ? direction.map(x => x / length) : [0, 0, 1];
}
