// Claude's page, shown beside Aria while the two of them talk (Engines/Duet.py). The overlay (ui/claude_view.py)
// drives it through window.claude; what he does is decided in claudelogic.mjs and Aria's logic.mjs, his shape is
// claude.mjs. Reports once through window.claudeStatus: "ready" after the first frame, or "failed: <why>".
// window.claudeGone turns true when he has finished leaving (the overlay then hides the window).
import * as THREE from 'three';
import { BONES, poseFor, idleMotion, talkMotion, gesture, GESTURES, withinLimits, ease, nextBlink, blinkWeight,
         BLINK, mouthWeight } from './logic.mjs';
import { gestureFor, facing, visibility, boneFollow, voiceLevel, expressionFor, listeningNod } from './claudelogic.mjs';
import { buildClaude } from './claude.mjs';

const FPS = 60;                                     // a frame's length when there is no real one yet
const HZ = Math.max(60, +new URLSearchParams(location.search).get('hz') || 60);
const canvas = document.getElementById('stage');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, premultipliedAlpha: true });
} catch (e) {
  window.claudeStatus = 'failed: no WebGL';
  throw e;
}
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(22, 0.75, 0.1, 20);
camera.position.set(0, 0.54, 3.15);
camera.lookAt(0, 0.54, 0);
scene.add(new THREE.HemisphereLight(0xffffff, 0xb09a8a, 1.25));    // a warmer fill than hers
const sun = new THREE.DirectionalLight(0xffffff, 2.0);
sun.position.set(0.9, 1.6, 2.6);
scene.add(sun);

function resize() {
  const w = window.innerWidth || 300, h = window.innerHeight || 400;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

const rig = buildClaude(THREE);
scene.add(rig.root);

const told = { state: 'idle', out: 0, side: 1, feeling: 'neutral', pinned: null };
let t = 0, last = 0, raf = 0, running = true, reported = false;
let transition = { start: 0, entering: true, from: { scale: 0, lift: 0 } };
let pop = { scale: 0, lift: 0 }, previousLift = 0;
let doing = null;                                   // { name, start } of a gesture under way
let stateSince = 0, gestureAfter = 0;
let blinkAt = nextBlink(0, Math.random());
const now = { mouth: 0, talk: 0, turn: { hips: 0, chest: 0, neck: 0, head: 0, eyes: 0 }, happy: 0, surprised: 0, relaxed: 0 };
window.claudeGone = false;

// at the screen's own rate, paced the same way as Aria (avatar.js nextFrame)
let timer = 0, due = 0;
function nextFrame() {
  // each frame is due one screen period after the last one was DUE (not after it came): a timer that fires a little
  // early only moves that one frame, and on average she draws exactly at the screen's rate (measured: 161 fps on a
  // 144 Hz screen when timed from when frames came)
  const now = performance.now();
  due = Math.max(due + 1000 / HZ, now - 1000 / HZ);
  timer = setTimeout(() => { timer = 0; if (running) raf = requestAnimationFrame(frame); }, Math.max(0, due - now));
}

function frame() {
  if (!running) return;
  const ms = performance.now();
  const dt = Math.min(0.1, last ? (ms - last) / 1000 : 1 / FPS);
  last = ms;
  nextFrame();
  t += dt;
  const follow = boneFollow(dt);

  // which way he faces and how much he talks with his body
  const want = facing(told.state, told.side);
  for (const k of Object.keys(now.turn)) now.turn[k] = ease(now.turn[k], want[k], dt, k === 'eyes' ? 0.08 : 0.35);
  now.talk = ease(now.talk, told.state === 'talking' ? Math.min(1, told.out * 6) : 0, dt, 0.15);
  const face = expressionFor(told.state === 'talking' ? told.feeling : 'neutral');
  for (const k of ['happy', 'surprised', 'relaxed']) now[k] = ease(now[k], face[k], dt, 0.4);

  const pose = poseFor('idle').bones, idle = idleMotion(t + 3.7), talking = now.talk > 0.01 ? talkMotion(t, now.talk) : null;
  let act = doing ? gesture(doing.name, t - doing.start, -told.side) : null;
  if (doing && t - doing.start >= GESTURES[doing.name]) doing = null;     // (one that starts in a moment is kept)
  for (const name of BONES) {
    const out = [...pose[name]];
    for (const add of [idle[name], talking?.[name]]) if (add) for (let i = 0; i < 3; i++) out[i] += add[i];
    if (name in now.turn) out[1] += now.turn[name];
    if (name === 'head') out[0] += listeningNod(t - stateSince, told.state);
    if (told.pinned?.[name]) { rig.setBone(name, withinLimits(name, told.pinned[name]), null, 0, 1); continue; }
    const target = act?.bones[name];
    if (target) rig.setBone(name, withinLimits(name, out), withinLimits(name, target), Math.max(-0.08, Math.min(1.1, act.weight)), follow);
    else rig.setBone(name, withinLimits(name, out), null, 0, follow);
  }

  // coming in, going out, and a hop's lift
  pop = visibility(t - transition.start, transition.entering, transition.from);
  rig.root.scale.setScalar(Math.max(0.0001, pop.scale));
  rig.root.position.y = pop.lift + (act?.lift || 0);
  if (!transition.entering && pop.scale === 0) window.claudeGone = true;

  if (t >= blinkAt + BLINK.length) blinkAt = nextBlink(t, Math.random());
  rig.setBlink(blinkWeight(t, blinkAt));
  now.mouth = mouthWeight(now.mouth, told.state === 'talking' ? told.out : 0, dt);
  rig.setMouth(now.mouth);
  for (const k of ['happy', 'surprised', 'relaxed']) rig.setExpression(k, now[k]);
  rig.look(now.turn.eyes, 0);
  rig.update(dt, (rig.root.position.y - previousLift) / dt);
  previousLift = rig.root.position.y;
  renderer.render(scene, camera);
  if (!reported) {
    reported = true;
    canvas.style.opacity = 1;
    window.claudeStatus = 'ready';
  }
}

window.claude = {
  setState(state) {
    const next = ['talking', 'listening', 'idle'].includes(state) ? state : 'idle';
    if (next !== told.state) stateSince = t;
    told.state = next;
    if (told.state !== 'talking') told.out = 0;
  },
  setLevel(out) { told.out = voiceLevel(out); },
  setSide(side) { told.side = side >= 0 ? 1 : -1; },
  /** The feeling of the line he's about to say: his face, and its gesture if it has one. */
  setFeeling(feeling) {
    told.feeling = feeling || 'neutral';
    const g = gestureFor(told.feeling);
    // a new line's gesture takes over unless the one under way is still in its first half
    if (g && g in GESTURES && !doing && t >= gestureAfter) {
      doing = { name: g, start: t + 0.15 };
      gestureAfter = t + GESTURES[g] + 4;
    }
  },
  enter() {
    transition = { start: t, entering: true, from: { ...pop } };
    window.claudeGone = false;
    told.out = 0;
    told.feeling = 'neutral';
    doing = { name: 'wave', start: t + ENTER_DELAY };
    gestureAfter = t + ENTER_DELAY + GESTURES.wave;
  },
  leave() {
    if (!transition.entering) return;
    transition = { start: t, entering: false, from: { ...pop } };
    told.state = 'idle';
    told.out = 0;
    doing = null;
  },
  pause() { running = false; cancelAnimationFrame(raf); clearTimeout(timer); raf = 0; },
  resume() { if (!running) { running = true; last = 0; raf = requestAnimationFrame(frame); } },
  /** for fitting a pose by eye (tools/avatar_look.py): bones pinned to fixed angles; tune() lets go */
  tune(bones) { told.pinned = bones || null; },
  act(name) { if (name in GESTURES) doing = { name, start: t }; },
  /** a picture of him as a PNG data URL (for checking his looks: no window grab needed) */
  snapshot() { renderer.render(scene, camera); return canvas.toDataURL('image/png'); },
};
const ENTER_DELAY = 0.45;
raf = requestAnimationFrame(frame);
