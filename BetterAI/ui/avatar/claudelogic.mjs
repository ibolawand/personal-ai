// What Claude does with his body while he talks with Aria (claude.js applies it to claude.mjs): which way he turns,
// which gesture goes with the feeling of what he says, and how he pops in and out. His idle life, talking motion,
// blinks and the gestures themselves come from Aria's logic.mjs (same bones, same convention).

/** The gesture for the feeling of a line (Engines/VoiceStyle.emotion), or null to just talk. */
export const FEELING_GESTURES = {
  happy: 'smile', excited: 'hop', laugh: 'hop', teasing: 'curious', curious: 'curious',
  thinking: 'think', soft: 'sigh', sad: 'sigh', neutral: null,
};

export function gestureFor(feeling) {
  return FEELING_GESTURES[feeling] ?? null;
}

/** How far he turns toward Aria (radians about y, spread over his body), for what he's doing. `side` is +1 when she
 *  is to his right on the screen, -1 to his left. Listening he faces her; talking he talks to Lala (the viewer) with
 *  his head half turned to Aria; idle he stands a little turned toward her. */
const TURN = { listening: 0.75, talking: 0.3, idle: 0.35 };
export function facing(state, side) {
  const total = (TURN[state] ?? TURN.idle) * (side >= 0 ? 1 : -1);
  return { hips: 0.2 * total, chest: 0.25 * total, neck: 0.2 * total, head: 0.35 * total, eyes: Math.sign(total) * Math.min(1, Math.abs(total) * 1.1) };
}

/** Coming in and going out: his size (0…1) and how high he is off the ground, `t` seconds in. He pops up with a
 *  little overshoot and a hop, and goes the opposite way: a small dip, then he shrinks away. */
export const ENTER_S = 0.55, LEAVE_S = 0.4;

export function entrance(t) {
  if (t <= 0) return { scale: 0, lift: 0 };
  if (t >= ENTER_S) return { scale: 1, lift: 0 };
  const x = t / ENTER_S;
  const back = 1 + 2.2 * (x - 1) ** 3 + 1.2 * (x - 1) ** 2;          // easeOutBack: a touch too big, then settled
  return { scale: Math.max(0, back), lift: 0.08 * Math.sin(Math.PI * x) };
}

export function exit(t) {
  if (t <= 0) return { scale: 1, lift: 0 };
  if (t >= LEAVE_S) return { scale: 0, lift: 0 };
  const x = t / LEAVE_S;
  const dip = x < 0.3 ? 1 + 0.06 * Math.sin(Math.PI * x / 0.3) : 1;
  return { scale: Math.max(0, dip * (1 - Math.max(0, x - 0.3) / 0.7) ** 2), lift: -0.02 * Math.sin(Math.PI * x) };
}

/** Continue a visibility transition from the exact pose on screen, including when interrupted. */
export function visibility(t, entering, from = { scale: entering ? 0 : 1, lift: 0 }) {
  const duration = entering ? ENTER_S : LEAVE_S;
  const x = Math.max(0, Math.min(1, t / duration));
  const blend = x * x * (3 - 2 * x);
  const pose = entering ? entrance(t) : exit(t);
  return {
    scale: entering ? from.scale + (1 - from.scale) * pose.scale : from.scale * pose.scale,
    lift: pose.lift + from.lift * (1 - blend),
  };
}

/** Match the original 30 fps bone smoothing at every render rate. */
export function boneFollow(dt) {
  return 1 - Math.exp(-Math.max(0, dt) * 30 * Math.LN2);
}

/** Reject invalid audio samples before they can propagate into bones and facial geometry. */
export function voiceLevel(value) {
  const level = Number(value);
  return Number.isFinite(level) ? Math.max(0, Math.min(1, level)) : 0;
}

/** His expression for a feeling: weights for the face. */
export function expressionFor(feeling) {
  const happy = ['happy', 'excited', 'laugh', 'teasing'].includes(feeling) ? 1 : 0;
  return { happy, surprised: feeling === 'excited' ? 0.5 : 0, relaxed: ['soft', 'sad', 'thinking'].includes(feeling) ? 0.6 : 0 };
}

/** A listener occasionally acknowledges a line; silence between lines stays quiet. */
export function listeningNod(elapsed, state) {
  return state === 'listening' ? 0.05 * Math.max(0, Math.sin(elapsed * 1.45)) ** 8 : 0;
}
