// Aria's avatar page. The overlay (ui/avatar_view.py, AvatarLink) talks to it through window.aria; what she does
// with her body is decided in logic.mjs; her shape is figure.mjs, or a VRM file when one is given (vrmrig.mjs).
// It reports once through window.ariaStatus: "ready" after the first frame, or "failed: <why>".
import * as THREE from 'three';
import { BONES, GESTURES, thoughtStep, detailFits, TAP, tapMotion, settles, settleBreath, CATCH, inReach, reachPoint, catchStep, cutShort, mayStartle, typingAttention, typingEyeStep, typingKeyCount, FIDGETS, tiredness, TIRED, crossFits, avatarState, poseFor, idleMotion, gesture, walkCycle, stroll, trip, planTrip, cutLeg, legLength, perchPose, dangle, carryInput, carrySwing, carryPose, setDown, jump, edgeSit, planPerch, LEDGE_Y, PERCH_YAW, PERCH_HEADROOM, PEEK, planHide, peekOut, talkMotion, visemes, reactionFor, cardText, bobMotion, phrasePlan, phraseGesture, grooveStep, afterMusic, beatClock, beatsAt,
         saccade, lookBlink, BLINK, chooseIdle, sitting, sitPose, spring, gazeWander, withinLimits, ease, nextBlink, blinkWeight,
         mouthWeight, speechShapes, speechBeat, laughMotion, ringPosition, handPose, mixHand, HANDS, SIT_HANDS, LEDGE_HANDS, breeze, PIANO, pianoLayout, pianoStage, pianoPerformance, pianoBody, keyUnder } from './logic.mjs';
import { buildPiano, makeIK, makeNotes } from './piano.mjs';
import { buildFigure } from './figure.mjs';
import { listenStep, listenAway, listenNod, ACKNOWLEDGEMENTS, acknowledgement, focusStage, focusBody, conversationMotion, activeBody, turnCue, planWindowVisit, windowVisitMotion, CHARACTER_MOODS, characterAccent, characterMood, poseTransitionTime, windowRoutineStep, destinationNotice, pointerReach, pointerDirection } from './presence.mjs';
import { buildFocusDesk } from './focusdesk.mjs';

import { resting, sleepAction, wakeAction, sleepAllowsActivity } from './sleep.mjs';

let wasAsleep = false, waking = false, restSince = 0;
const FPS = 60, RING_Y = 0.52;                     // a frame's length when there is no real one to go by (advance, the first pose)
// how often she draws: the screen's own refresh rate, from the overlay (ui/avatar_view.screen_hz; 60 without it)
const HZ = Math.max(60, +new URLSearchParams(location.search).get('hz') || 60);
let ringRadius = 0.4;                               // set from what the camera can see (a tall box is narrow)
let strollReach = 0.2;                              // how far to each side she has room to walk
let pxPerUnit = 400;                                // screen pixels per unit of her world, where she stands
const canvas = document.getElementById('stage'), captionEl = document.getElementById('caption');

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, premultipliedAlpha: true });
} catch (e) {
  window.ariaStatus = 'failed: no WebGL';
  throw e;
}
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(22, 0.75, 0.1, 20);
camera.position.set(0, 0.54, 3.15);
camera.lookAt(0, 0.54, 0);
// Cel-shaded characters want one clear light from the front and above (it draws the shade line under the chin
// and on the far cheek) and only enough fill that the shaded side keeps its colour. Too much fill washes the face out.
scene.add(new THREE.HemisphereLight(0xffffff, 0x9a8fc0, 1.25));
const sun = new THREE.DirectionalLight(0xffffff, 2.0);
sun.position.set(0.9, 1.6, 2.6);
scene.add(sun);

function resize() {
  const w = window.innerWidth || 300, h = window.innerHeight || 400;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  const halfWidth = Math.tan(camera.fov * Math.PI / 360) * camera.position.z * camera.aspect;
  ringRadius = Math.max(0.2, Math.min(0.4, halfWidth - 0.075));
  strollReach = Math.max(0, Math.min(0.3, halfWidth - 0.21));    // room for her hair swinging out at the edge
  pxPerUnit = h / (2 * Math.tan(camera.fov * Math.PI / 360) * camera.position.z);
}
window.addEventListener('resize', resize);
resize();

// ── who she is: a VRM when the overlay names one and it loads, the built-in figure otherwise ──
let rig = buildFigure(THREE);
scene.add(rig.root);
const modelUrl = new URLSearchParams(location.search).get('model');
let waitingForModel = !!modelUrl;                   // not "ready" until we know who she is: no flash of the other figure
if (modelUrl) {
  import('./vrmrig.mjs').then(m => m.loadVrm(THREE, modelUrl)).then(loaded => {
    scene.remove(rig.root);
    rig = loaded;
    scene.add(rig.root);
    window.ariaModel = 'loaded';
  }).catch(e => {                                   // she keeps her built-in figure; the overlay reports why
    window.ariaModel = 'failed: ' + (e?.message || e);
  }).finally(() => {
    waitingForModel = false;
    firstFrame();
  });
}

// ── what the overlay told her ──
let closeUp = null;         // [x, y, height, yaw]: what snapshot() shows instead of all of her (window.aria.closeUp)
let tuning = null;           // bones pinned to fixed angles while fitting a pose (window.aria.tune)
const told = { state: 'idle', mic: 0, out: 0, lookX: 0, lookY: 0, props: [], piano: false };
let focusPhase = 'off', focus = null, atDesk = false, focusSince = -99, focusFrom = null;
let conversation = { speaker: 'off', side: 1 }, conversationSince = 0;
let acknowledgementNow = null;
let breakStretchAt = null;
let running = false, raf = 0, last = 0, t = 0, reported = false;
let thought = null;                                // a long thought, waiting only for the end of its answer
let doing = null;                                   // { name, start, side, cut } of a gesture under way (a wave, a fidget)
let walk = null;                                    // { start, side, peek } of a stroll under way; a trip across
                                                    // the screen also has { trip: true, leg, base, id, cut }
// Walking across the screen she really moves through her world, and the camera (and her ring of props) go along,
// so she stays in the middle of her box while the overlay moves its window by the same distance (ariaTravel).
// Her hair feels the walk that way. The offset is never reset: that would jolt her hair.
let stageX = 0, stageY = 0;
// Sitting on top of a window: the overlay says where she could sit ({ x, half, y } in pixels from the middle of the
// bottom of her box) and how far below her the floor is; she walks under a seat, jumps up onto it and sits there
// (perched) until she hops down or the window goes. The overlay keeps her window on the seat while it moves.
let seatsPx = [], floorPx = 0;
let jumping = null;                                 // { start, dy (units), base, id } of a jump under way
let perched = null;                                 // { since } while she sits on top of a window
let perchSide = 1;                                  // which way she turns a little, sitting there
// carried: her window dragged ({ at: [x, y] screen pixels, input (carryInput) }), how far she is picked up (0…1),
// her swing (carrySwing) and when she was put down
let carry = null, held = 0, sway = { a: 0, v: 0 }, setDownAt = null;
// Peeking out from behind an app: the overlay says which side edges of windows she could go behind ({ id, x
// (pixels from the middle of her box), out }); she walks to just behind one, peeks out and walks back out. While
// she is behind a window, ariaBehind is its id and the overlay sends its rectangle (setCover): that part of her
// isn't drawn.
let hideoutsPx = [];
let visit = null, lastVisitedWindow = null;
const visitIK = makeIK(THREE), visitTarget = new THREE.Vector3(), visitPole = new THREE.Vector3();
let hide = null;                                    // { id, out, edge (stage x of the edge), phase, start, r, early }
window.ariaBehind = null;
let idleNow = true;                                 // nothing is going on (she may do things of her own)
let room = null;                                    // { left, right }: how far she may walk each way (units)
let tripId = 0;
window.ariaTravel = null;                           // [trip id, pixels walked, still walking]: read by the overlay
let sit = null;                                     // { start, standAt, side } while she sits on the floor (or gets up)
let idleAt = 6 + Math.random() * 6;                 // when she next does something of her own while idle
let idleSince = 0;                                  // since when nothing has been going on (she gets bored and sits)
let recent = [];                                    // what she did last, so she doesn't do it again straight away
let lookMovedAt = 0, lastLook = [0, 0];             // when the mouse last moved: left alone, her gaze wanders
let lean = [0, 0];                                  // the spring of her forward lean as she walks and stops [angle, speed]
// she starts standing relaxed, not in the T-pose her model is built in (her arms used to drop from straight out)
const now = { bones: poseFor('idle').bones, look: [0, 0], lookV: [0, 0], eyes: [0, 0], mouth: 0, surprised: 0, relaxed: 0, happy: 0,
              lift: 0, talk: 0, wander: 0, ledge: 0, bob: 0, typing: 0,
              hands: handPose(0), posed: 0, poseHands: {}, say: { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 } };
const BREATHING = new Set(['spine', 'chest', 'neck', 'head']);   // where her idle breath is (forward and back: x)
const LEGS = new Set(['leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot']);
const SEAT_YAW = 1.15;      // how far she turns to sit (radians)
const FOLLOW_S = 0.045;     // every joint follows what it is told this closely: a new action can never make one pop
let blinkAt = nextBlink(0, Math.random()), lastBlink = -9;
// how tired she is (logic.mjs tiredness: late at night), read from the clock once a minute; her idle movement runs
// on its own clock, slower when she is tired; when she last nodded off
// her motion clips (motions.mjs): how much they show, how much of that is the talking one, and their clock
let sitClipW = 0, walkClipW = 0, talkW = 0, clipClock = 0;
let tired = 0, tiredRead = -99, idleClock = 0, dozeAt = -1e9, startledAt = -1e9;
// the text box: open, and when you last typed in it (null: nothing yet since it opened); how far she leans in
let typingOpen = false, typedAt = null, typingSide = 1, typingKeys = 0;
let listen = null;
let settledAt = null;
let tappedAt = -1e9, tapSide = 1;                  // when you last clicked her (a little reaction)                               // when she stopped after a longer walk (a settling breath)
// the mouse pointer beside her ({ x, y } pixels from the middle of the bottom of her box), when it last moved, and
// her trying to catch it (logic.mjs catchStep) with which hand
let pointerPx = null, pointerMovedAt = -1e9, catching = null, catchSide = 'right';
const catchPoint = new THREE.Vector3(), catchPointer = new THREE.Vector3();
const catchTarget = new THREE.Vector3(), catchPole = new THREE.Vector3(), catchAt = new THREE.Vector3();
const selfTarget = new THREE.Vector3(), selfPole = new THREE.Vector3(), selfAt = new THREE.Vector3();   // a hand on her own body                                  // following your voice while she listens (presence.mjs listenStep)
const doneAt = {};                                 // when she last did each thing of her own (for the rare ones)
let moodCue = null;
const expressionNow = Object.fromEntries(CHARACTER_MOODS.map(name => [name, 0]));
let activeState = 'idle', previousState = 'idle', activeSince = 0, voiceActivity = 0, turnNumber = 0;
const activeBones = Object.fromEntries(BONES.map(name => [name, [0, 0, 0, 0]]));
let speech = null;
let phrasing = null;                                // { plan, start, stopAt }: her arms' gestures for what she says (phrasePlan)                                  // { segments, start (performance.now() s) }: what she says now

// ── the things in orbit ──
const propMat = color => new THREE.MeshBasicMaterial({ color, transparent: true });
const makers = {
  clock() {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.012, 28), propMat(0xf6f3ff)).rotateX(Math.PI / 2));
    g.add(new THREE.Mesh(new THREE.TorusGeometry(0.05, 0.008, 8, 28), propMat(0xb9a3ff)));
    const hour = new THREE.Mesh(new THREE.BoxGeometry(0.008, 0.028, 0.004), propMat(0x2b2740));
    hour.position.set(0, 0.012, 0.009);
    const minute = new THREE.Mesh(new THREE.BoxGeometry(0.006, 0.036, 0.004), propMat(0x2b2740));
    minute.position.set(0.013, 0.008, 0.009);
    minute.rotation.z = -1.0;
    g.add(hour, minute);
    return g;
  },
  note() {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.BoxGeometry(0.085, 0.085, 0.008), propMat(0xffd866)));
    for (const y of [0.018, 0, -0.018]) {
      const line = new THREE.Mesh(new THREE.BoxGeometry(0.052, 0.006, 0.002), propMat(0x9a7412));
      line.position.set(-0.004, y, 0.006);
      g.add(line);
    }
    g.rotation.z = 0.12;
    return g;
  },
  mic() {
    const g = new THREE.Group();
    const head = new THREE.Mesh(new THREE.CapsuleGeometry(0.024, 0.035, 6, 14), propMat(0x45bdf5));
    head.position.y = 0.022;
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.005, 0.04, 8), propMat(0xf6f3ff));
    stem.position.y = -0.04;
    const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.006, 16), propMat(0xf6f3ff));
    foot.position.y = -0.06;
    g.add(head, stem, foot, new THREE.Mesh(new THREE.TorusGeometry(0.036, 0.004, 6, 20, Math.PI), propMat(0xf6f3ff)).rotateZ(Math.PI));
    return g;
  },
  dots() {
    const g = new THREE.Group();
    [-0.045, 0, 0.045].forEach((x, i) => {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.017, 14, 10), propMat(0xb9a3ff));
      dot.position.x = x;
      dot.userData.phase = i;
      g.add(dot);
    });
    return g;
  },
};
const ring = new THREE.Group();
ring.position.y = RING_Y;
scene.add(ring);
const props = new Map();                            // kind -> { group, caption, shown (0…1), wanted, scale }

function setProps(list) {
  const wanted = new Map((Array.isArray(list) ? list : []).filter(p => makers[p?.kind]).map(p => [p.kind, String(p.caption ?? '')]));
  for (const [kind, caption] of wanted) {
    if (!props.has(kind)) {
      const g = makers[kind]();
      ring.add(g);
      props.set(kind, { group: g, shown: 0, scale: 1 });
    }
    Object.assign(props.get(kind), { caption, wanted: true });
  }
  for (const [kind, prop] of props) if (!wanted.has(kind)) prop.wanted = false;
}

// ── the test card she holds up now and then (Engines/Companion.py sends the next test) ──
const CARD_W = 0.2, CARD_H = 0.13;           // her hands hold its bottom edge, a little in from the corners
let testCard = null;                                // { big, small } while a test is coming up
let cardAt = -Infinity;                             // when she last held it up (once an hour at most)
const cardCanvas = document.createElement('canvas');
cardCanvas.width = 512; cardCanvas.height = 360;
const cardTexture = new THREE.CanvasTexture(cardCanvas);
cardTexture.colorSpace = THREE.SRGBColorSpace;
cardTexture.anisotropy = 4;
function cardShape(w, h, r) {
  const s = new THREE.Shape();
  s.moveTo(-w / 2 + r, -h / 2);
  s.lineTo(w / 2 - r, -h / 2); s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
  s.lineTo(w / 2, h / 2 - r); s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
  s.lineTo(-w / 2 + r, h / 2); s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
  s.lineTo(-w / 2, -h / 2 + r); s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
  return s;
}
function bentCard(w, h, r) {
  // a paper card bowed a little toward her (the middle further back than the edges she holds)
  const g = new THREE.ShapeGeometry(cardShape(w, h, r), 10);
  const pos = g.attributes.position, uv = g.attributes.uv;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i);
    pos.setZ(i, -0.012 * Math.cos(Math.PI * x / w));
    uv.setXY(i, x / w + 0.5, y / h + 0.5);
  }
  g.computeVertexNormals();
  return g;
}
const cardGroup = new THREE.Group();
const cardFace = new THREE.Mesh(bentCard(CARD_W, CARD_H, 0.014),
  new THREE.MeshBasicMaterial({ map: cardTexture, transparent: true, side: THREE.DoubleSide }));
// her outline: the same card a little bigger, dark, drawn behind (like the line round her body)
const cardLine = new THREE.Mesh(bentCard(CARD_W + 0.008, CARD_H + 0.008, 0.017),
  new THREE.MeshBasicMaterial({ color: 0x3a2a4a, transparent: true, side: THREE.DoubleSide }));
cardLine.position.z = -0.002;
cardGroup.add(cardLine, cardFace);
cardGroup.visible = false;
scene.add(cardGroup);

/** Sets the font for `text` (as big as fits, down to a size that can still be read from her box) and returns the
 *  text, cut short with "…" when even that size doesn't fit. */
function fitText(ctx, text, weight, size, maxW, least = 50) {
  const font = px => { ctx.font = `${weight} ${px}px "Nunito", "Segoe UI", "Noto Sans", sans-serif`; };
  for (; size > least; size -= 4) {
    font(size);
    if (ctx.measureText(text).width <= maxW) return text;
  }
  font(least);
  let cut = text;
  while (cut.length > 1 && ctx.measureText(cut + '…').width > maxW) cut = cut.slice(0, -1);
  return cut === text ? text : cut.trimEnd() + '…';
}
function drawCard() {
  const c = cardCanvas.getContext('2d'), W = cardCanvas.width, H = cardCanvas.height;
  c.clearRect(0, 0, W, H);
  c.fillStyle = '#fff6e8';                          // paper
  c.fillRect(0, 0, W, H);
  c.fillStyle = 'rgba(185, 163, 255, 0.35)';        // a pale stripe across the top, like an index card
  c.fillRect(0, 34, W, 10);
  if (!testCard) return;
  c.textAlign = 'center';
  c.textBaseline = 'middle';
  c.fillStyle = '#5b3fa0';                          // above her fingers (they hold the bottom edge)
  c.fillText(fitText(c, testCard.big, 800, 100, W - 70, 62), W / 2, H * 0.35);   // text only, never markup
  if (testCard.small) {
    c.fillStyle = '#2b2740';
    c.fillText(fitText(c, testCard.small, 700, 58, W - 140, 44), W / 2, H * 0.58);
  }
  // a little star doodle in the corner
  c.save();
  c.translate(W - 58, 78);
  c.rotate(0.2);
  c.fillStyle = '#ffb3d1';
  c.beginPath();
  for (let i = 0; i < 10; i++) {
    const r = i % 2 ? 11 : 26, a = -Math.PI / 2 + i * Math.PI / 5;
    c.lineTo(r * Math.cos(a), r * Math.sin(a));
  }
  c.closePath();
  c.fill();
  c.restore();
  cardTexture.needsUpdate = true;
}
drawCard();

const handL = new THREE.Vector3(), handR = new THREE.Vector3(), cardMid = new THREE.Vector3();
/** The card goes where her hands are, every frame: it stays in her grip whatever her arms do. */
function placeCard(up) {
  const both = up > 0.01 ? rig.where?.('leftHand') && rig.where?.('rightHand') : null;
  if (!both) { cardGroup.visible = false; return; }
  handL.fromArray(rig.where('leftHand'));
  handR.fromArray(rig.where('rightHand'));
  cardMid.addVectors(handL, handR).multiplyScalar(0.5);
  cardGroup.position.copy(cardMid);
  cardGroup.position.z += 0.02;                     // in front of her fingers, not through them
  cardGroup.quaternion.copy(camera.quaternion);
  cardGroup.rotateZ(Math.atan2(handL.y - handR.y, handL.x - handR.x) * 0.6);   // tilted as her hands are
  cardGroup.translateY(CARD_H / 2 - 0.022);         // her fingers on its bottom edge: the card stands up above them
  cardGroup.scale.setScalar(0.6 + 0.4 * up);
  cardFace.material.opacity = cardLine.material.opacity = up;
  cardGroup.visible = true;
}

// ── her piano, while piano music plays (logic.mjs decides, piano.mjs builds and reaches; ui.set_piano) ──
// The piano is built the first time she plays, measured to her body. `atPiano` is whether she is at it now (told
// to, and standing on the floor); every change of it starts the stage over from where it was, so music stopping
// halfway through her sitting down makes her stand up from there, not jump.
let piano = null, pianoLook = null;                 // { model, layout } once built
const pianoIK = makeIK(THREE), notes = makeNotes(THREE, scene);
let atPiano = false, pianoSince = -99, pianoFrom = null;
const pianoV = { a: new THREE.Vector3(), b: new THREE.Vector3(), c: new THREE.Vector3(), d: new THREE.Vector3(),
                 e: new THREE.Vector3(), f: new THREE.Vector3(), x: new THREE.Vector3(1, 0, 0), q: new THREE.Quaternion() };
const pianoHands = {};                              // each hand's spring: { p (where the wrist is), v }
let lastPress = { L: 0, R: 0 };
function measureForPiano() {
  const at = name => new THREE.Vector3(...(rig.where(name) || [0, 0, 0]));
  const y0 = rig.root.position.y;
  const hip = at('leftUpperLeg'), knee = at('leftLowerLeg'), shoulder = at('leftUpperArm'), elbow = at('leftLowerArm');
  return { hip: hip.y - y0, thigh: hip.distanceTo(knee), shin: knee.y - y0, shoulder: shoulder.y - hip.y,
           upperArm: shoulder.distanceTo(elbow) };
}
function pianoStageNow() {
  const stage = pianoStage(t - pianoSince, atPiano);
  // started over halfway through: each part carries on from where it was
  if (pianoFrom) for (const k of Object.keys(stage)) stage[k] = atPiano ? pianoFrom[k] + (1 - pianoFrom[k]) * stage[k] : pianoFrom[k] * stage[k];
  return stage;
}

function deskStageNow() { return focusStage(t - focusSince, atDesk, focusFrom); }

// Reuse the same small icon meshes as her orbiting props; only one acknowledgement lives at a time.
const successIcons = new Map();
function showAcknowledgement(name) {
  if (!ACKNOWLEDGEMENTS.includes(name)) return;
  if (!successIcons.has(name)) {
    const group = new THREE.Group();
    if (name === 'timerSaved') group.add(makers.clock());
    else if (name === 'noteSaved') {
      const cover = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.12, 0.018), propMat(0x8871c9));
      const sheet = makers.note();
      sheet.scale.setScalar(0.85); sheet.position.z = 0.018;
      group.add(cover, sheet);
      group.userData.sheet = sheet;
    } else {
      group.add(new THREE.Mesh(new THREE.BoxGeometry(0.075, 0.075, 0.01), propMat(0xf6f3ff)));
    }
    const check = new THREE.Line(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-0.025, 0, 0.02), new THREE.Vector3(-0.008, -0.018, 0.02), new THREE.Vector3(0.03, 0.026, 0.02),
    ]), new THREE.LineBasicMaterial({ color: 0x83efb4, transparent: true }));
    check.position.set(0.045, -0.04, 0.02);
    group.add(check); group.visible = false; scene.add(group);
    successIcons.set(name, group);
  }
  acknowledgementNow = { name, start: t };
}

function moveAcknowledgement() {
  for (const group of successIcons.values()) group.visible = false;
  if (!acknowledgementNow) return;
  const a = acknowledgement(acknowledgementNow.name, t - acknowledgementNow.start);
  if (!a) { acknowledgementNow = null; return; }
  const group = successIcons.get(acknowledgementNow.name);
  group.visible = true;
  group.position.set(rig.root.position.x - 0.16, stageY + 0.88 + a.lift, 0.18);
  group.scale.setScalar(0.6 + 0.4 * a.shown);
  group.rotation.z = acknowledgementNow.name === 'noteSaved' ? 0.18 * (1 - a.shown) : 0;
  if (group.userData.sheet) group.userData.sheet.position.y = 0.045 * (1 - a.shown);
  group.traverse(obj => { if (obj.material) { obj.material.transparent = true; obj.material.opacity = a.shown; } });
}

// ── her umbrella, when rain is coming (Engines/Companion.py sends it; logic.mjs moves it) ──
let rainComing = false;
let beat = null, beatTold = -1e9, groove = null;      // the music's beat clock (bob to music), and when it was last reported
let umbrellaAt = -Infinity;                         // when she last brought it out (every 20 min at most)
const RIBS = 8, RIB_R = 0.2, APEX_Y = 0.31;      // a parasol for her size, and it stays inside her box
const umbrella = new THREE.Group();
const umbMats = [];
const umbMat = (o) => { const m = new THREE.MeshBasicMaterial({ transparent: true, ...o }); umbMats.push(m); return m; };
const canopyGeo = new THREE.BufferGeometry();
const canopyPos = new Float32Array(RIBS * 6 * 3 * 3);        // per panel: 6 triangles
const canopyCol = new Float32Array(canopyPos.length);
canopyGeo.setAttribute('position', new THREE.BufferAttribute(canopyPos, 3));
canopyGeo.setAttribute('color', new THREE.BufferAttribute(canopyCol, 3));
const PANEL = [new THREE.Color(0xffb3d1), new THREE.Color(0xc9a8ff)];
for (let i = 0; i < RIBS; i++) for (let v = 0; v < 18; v++) PANEL[i % 2].toArray(canopyCol, (i * 18 + v) * 3);
const canopyOut = new THREE.Mesh(canopyGeo, umbMat({ vertexColors: true, side: THREE.FrontSide }));
const canopyIn = new THREE.Mesh(canopyGeo, umbMat({ vertexColors: true, side: THREE.BackSide, color: 0x9d8cb0 }));
const linesGeo = new THREE.BufferGeometry();
const linesPos = new Float32Array(RIBS * 4 * 2 * 3);          // per rib: apex-half, half-tip, tip-scallop, scallop-next tip
linesGeo.setAttribute('position', new THREE.BufferAttribute(linesPos, 3));
const lines = new THREE.LineSegments(linesGeo, new THREE.LineBasicMaterial({ color: 0x3a2a4a, transparent: true }));
umbMats.push(lines.material);
const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 0.42, 8), umbMat({ color: 0x6b4fa0 }));
shaft.position.y = 0.14;
const tip = new THREE.Mesh(new THREE.ConeGeometry(0.006, 0.03, 8), umbMat({ color: 0xf6f3ff }));
tip.position.y = APEX_Y + 0.025;
const handle = new THREE.Mesh(new THREE.TorusGeometry(0.02, 0.0055, 8, 16, Math.PI), umbMat({ color: 0x6b4fa0 }));
handle.rotation.z = Math.PI;                        // the lower half of a ring: a J under her hand
handle.position.set(0.02, -0.07, 0);
umbrella.add(shaft, tip, handle, canopyOut, canopyIn, lines);
umbrella.visible = false;
scene.add(umbrella);

/** The canopy at `open` (0 closed against the shaft … 1 open, a little more as it snaps): ribs from the apex, a
 *  half-way ring bulging out a touch (a dome, not a cone), and a rim that dips between the rib tips (scallops). */
function shapeCanopy(open) {
  const a = 0.1 + 1.12 * Math.max(0, open);         // each rib's angle from hanging straight down
  const at = (r, ang, phi) => [r * Math.sin(ang) * Math.cos(phi), APEX_Y - r * Math.cos(ang), r * Math.sin(ang) * Math.sin(phi)];
  const apex = [0, APEX_Y, 0];
  let p = 0, l = 0;
  const put = (...vs) => { for (const v of vs) { canopyPos.set(v, p); p += 3; } };
  const line = (u, v) => { linesPos.set(u, l); linesPos.set(v, l + 3); l += 6; };
  for (let i = 0; i < RIBS; i++) {
    const f0 = 2 * Math.PI * i / RIBS, f1 = 2 * Math.PI * (i + 1) / RIBS, fm = (f0 + f1) / 2;
    const h0 = at(RIB_R / 2, a * 1.3, f0), h1 = at(RIB_R / 2, a * 1.3, f1), hm = at(RIB_R / 2 * 0.96, a * 1.27, fm);   // the dome
    const t0 = at(RIB_R, a, f0), t1 = at(RIB_R, a, f1), tm = at(RIB_R * 0.9, a * 0.94, fm);
    put(apex, h1, hm, apex, hm, h0);                // the top of the panel
    put(h0, hm, tm, h0, tm, t0, hm, h1, t1, hm, t1, tm);
    line(apex, h0); line(h0, t0); line(t0, tm); line(tm, t1);
  }
  canopyGeo.attributes.position.needsUpdate = true;
  linesGeo.attributes.position.needsUpdate = true;
  canopyGeo.computeBoundingSphere();
}
shapeCanopy(0);

const UP_Y = new THREE.Vector3(0, 1, 0), umbDir = new THREE.Vector3(), bodyTurn = new THREE.Quaternion(),
  spinQ = new THREE.Quaternion(), umbHand = new THREE.Vector3();
/** The umbrella in her right hand: the grip at her hand, the shaft along `dir` (in her body's frame, so it turns
 *  with her), turned `spin` about itself. */
function placeUmbrella(u) {
  const hand = u && u.shown > 0.01 ? rig.where?.('rightHand') : null;
  if (!hand) { umbrella.visible = false; return; }
  umbHand.fromArray(hand);
  rig.root.getWorldQuaternion(bodyTurn);
  umbDir.fromArray(u.dir).applyQuaternion(bodyTurn).normalize();
  umbrella.position.copy(umbHand);
  umbrella.quaternion.setFromUnitVectors(UP_Y, umbDir).multiply(spinQ.setFromAxisAngle(UP_Y, u.spin));
  umbrella.scale.setScalar(0.7 + 0.3 * u.shown);
  shapeCanopy(u.open);
  for (const m of umbMats) m.opacity = u.shown;
  umbrella.visible = true;
}

const ray = new THREE.Raycaster(), pointer = new THREE.Vector2(), spot = new THREE.Vector3();

function moveProps(dt) {
  const kinds = [...props.keys()];
  let hovered = null;
  pointer.set(told.lookX, told.lookY);
  ray.setFromCamera(pointer, camera);
  kinds.forEach((kind, i) => {
    const prop = props.get(kind);
    prop.shown = ease(prop.shown, prop.wanted ? 1 : 0, dt);
    if (!prop.wanted && prop.shown < 0.02) {
      ring.remove(prop.group);
      props.delete(kind);
      return;
    }
    const [x, y, z] = ringPosition(i, kinds.length, t, ringRadius);
    prop.group.position.set(x, y + 0.012 * Math.sin(t * 1.7 + i), z);
    prop.group.traverse(o => { if (o.material) o.material.opacity = prop.shown; });
    if (kind === 'dots') prop.group.children.forEach(d => { d.position.y = 0.014 * Math.sin(t * 5 - d.userData.phase * 0.9); });
    if (kind === 'clock') prop.group.children[3].rotation.z = -t * 1.2;
    prop.group.getWorldPosition(spot);
    const near = ray.ray.distanceToPoint(spot) < 0.075 && prop.wanted;
    if (near && (!hovered || spot.z > hovered.z)) hovered = { prop, z: spot.z };
    prop.near = near;
  });
  for (const prop of props.values()) {
    prop.scale = ease(prop.scale, hovered?.prop === prop ? 1.4 : 1, dt, 0.15);
    prop.group.scale.setScalar(prop.scale * (0.6 + 0.4 * prop.shown));
  }
  if (hovered && hovered.prop.caption) {
    hovered.prop.group.getWorldPosition(spot).project(camera);
    captionEl.textContent = hovered.prop.caption;         // text only, never markup
    captionEl.style.left = `${(spot.x + 1) / 2 * window.innerWidth}px`;
    captionEl.style.top = `${(1 - spot.y) / 2 * window.innerHeight}px`;
    captionEl.style.display = 'block';
  } else {
    captionEl.style.display = 'none';
  }
}

// ── one frame of her ──
const smooth01 = x => x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x);

function move(dt) {
  const asleep = resting(told.state, focusPhase);
  const pianoWanted = told.piano && sleepAllowsActivity(told.state);
  if (asleep && !wasAsleep) {
    restSince = t;
    if (doing && doing.cut == null) doing.cut = t;
    if (visit) visit.cut = t;
    if (hide) hide.early = true;
  }
  if (!asleep && wasAsleep) waking = true;
  if (asleep) waking = false;
  wasAsleep = asleep;
  const getUp = wakeAction({ waking, seated: !!sit, perched: !!perched, jumping: !!jumping });
  if (getUp) begin(getUp);
  if (waking && !sit && !perched && !jumping && !walk && now.ledge < 0.01) waking = false;
  const micOpen = props.get('mic')?.wanted === true;
  const state = avatarState(told.state, micOpen);
  if (state !== activeState) {
    previousState = activeState;
    activeState = state;
    activeSince = t;
    voiceActivity = 0;  // her outgoing voice mustn't become the listener's nod
    if (state === 'speaking') turnNumber++;
  }
  const cue = turnCue(previousState, state, t - activeSince);
  if (t - tiredRead > 60) {
    const d = new Date();
    [tired, tiredRead] = [tiredness(d.getHours() + d.getMinutes() / 60), t];
  }
  idleClock += dt * (1 - TIRED.idleSlow * tired);                    // tired: slower drift and breath
  const pose = poseFor(state), idle = idleMotion(idleClock);
  // after a longer walk, one fuller breath (over as soon as something happens)
  if (settledAt != null && (t - settledAt >= 2.8 || state !== 'idle' || told.engaged || carry || doing || walk || jumping || sit ||
                            perched || hide || visit || atPiano || atDesk)) settledAt = null;
  const settle = settleBreath(settledAt == null ? null : t - settledAt);
  const tap = carry ? {} : tapMotion(t - tappedAt, tapSide);   // you clicked her
  // with nothing going on she now and then does something of her own: while idle, and also while she is listening
  // but nobody is talking (an open microphone can mean a long wait). Never while thinking or speaking.
  // (and not while you're dealing with her: the text box open or a card up)
  // (the piano counts as busy: no walks or fidgets, and a walk under way stops)
  const waiting = !waking && !carry && conversation.speaker === 'off' && !told.engaged && focusPhase !== 'work' && !(focus && deskStageNow().show > 0) && !pianoWanted && !(piano && pianoStageNow().show > 0) &&
                  (state === 'idle' || (state === 'listening' && told.mic < 0.012));
  thought = thoughtStep(thought, { state, free: waiting && !doing && !walk && !sit && !perched && !jumping && !hide && !visit }, dt);
  if (thought.fire) begin({ gesture: 'thoughtRelease', side: turnNumber % 2 ? 1 : -1 });
  // piano music: once she stands on the floor she goes to the piano (from a window she hops down first)
  const canWork = focusPhase === 'work' && conversation.speaker === 'off' && !told.engaged && state === 'idle' &&
                  !walk && !jumping && !hide && !visit && !sit && !perched && now.ledge < 0.01 && !(piano && pianoStageNow().show > 0.001);
  if (focusPhase === 'work' && perched && !jumping) begin({ hopDown: true });
  if (canWork !== atDesk) {
    if (canWork && !focus) {
      const layout = pianoLayout(measureForPiano());
      focus = { layout, model: buildFocusDesk(THREE, layout) };
      scene.add(focus.model.group);
    }
    focusFrom = focus ? deskStageNow() : null;
    [atDesk, focusSince] = [canWork, t];
  }
  const desk = focus ? deskStageNow() : { show: 0, turn: 0, sit: 0, hands: 0 };
  if (breakStretchAt !== null && t >= breakStretchAt) {
    if (t > breakStretchAt + 8 || focusPhase !== 'break') breakStretchAt = null;
    else if (desk.show < 0.001 && !atPiano && state === 'idle' && !told.engaged && !walk && !jumping && !hide && !visit && !doing) {
      start('shoulderRoll');
      breakStretchAt = null;
    }
  }
  const canPlay = pianoWanted && focusPhase !== 'work' && desk.show < 0.001 && !walk && !jumping && !hide && !visit && !sit && !perched && now.ledge < 0.01;
  if (pianoWanted && perched && !jumping) begin({ hopDown: true });
  if (canPlay !== atPiano) {
    if (canPlay && !piano) {
      const layout = pianoLayout(window.ariaPianoFit = measureForPiano());
      window.ariaPianoLayout = layout;
      piano = { layout, model: buildPiano(THREE, layout, PIANO.keys) };
      scene.add(piano.model.group);
    }
    pianoFrom = piano ? pianoStageNow() : null;
    [atPiano, pianoSince] = [canPlay, t];
  }
  const stage = piano ? pianoStageNow() : { show: 0, turn: 0, sit: 0, hands: 0 };
  const perf = stage.show > 0 ? pianoPerformance(t, beat?.bpm && t - beatTold < 2 ? beatsAt(beat, t) : null) : null;
  if (!waiting) idleSince = t;

  // a fidget gives way quickly when something happens (a wave or a hop is meant, and plays out)
  if (doing && !waiting && FIDGETS.includes(doing.name) && doing.cut == null) doing.cut = t;
  if (doing && doing.cut == null && !detailFits(doing.name, { waiting, walk, sit, perched, jumping, hide, visit, carried: !!carry })) doing.cut = t;
  // crossed ankles fade out as soon as she isn't sitting on a window edge any more (hopping down, the seat gone,
  // picked up)
  if (['crossAnkles', 'ankleEase'].includes(doing?.name) && doing.cut == null && !crossFits({ perched, jumping: !!jumping, carried: !!carry })) doing.cut = t;
  // (broken off, it stays where it was then: she lets go of that, not of a gesture still going on)
  let act = doing ? gesture(doing.name, (doing.cut ?? t) - doing.start, doing.side) : null;
  // broken off, she lets go in order: eyes and head first, hands last (logic.mjs cutShort)
  if (act && doing.cut != null) act = cutShort(act, doing.name, t - doing.cut);
  if (doing && !act) doing = null;

  // sitting on the floor: she gets up as soon as something happens
  if (sit && !waiting && sit.standAt == null) sit.standAt = t - sit.start;
  const seat = sit ? sitting(t - sit.start, sit.standAt) : null;
  if (sit && !seat) {
    window.ariaTravel = [sit.id, 0, false];         // up again: her box is back where it was
    sit = null;
  }
  const settling = seat && seat.w > 0.001 && seat.w < 0.999;
  let base = seat ? sitPose(seat.w, pose) : pose;

  idleNow = waiting;
  if (!waiting || doing || walk || settling || jumping || hide || visit || (catching && catching.phase !== 'off')) idleAt = Math.max(idleAt, t + 2 + Math.random() * 3);
  else if (asleep && t - restSince > 1) {
    const action = sleepAction({ asleep, busy: !!(carry || told.engaged || !waiting || doing || walk || jumping || hide || visit || settling),
      seated: !!sit, perched: !!perched, canPerch: !!planPerch(seatsPx, 0.5, 60, 0.5),
      sinceRest: t - restSince, sinceDoze: t - dozeAt });
    if (action) begin(action);
  }
  else if (!asleep && t >= idleAt) begin(chooseIdle({ recent, idleFor: t - idleSince, seated: !!sit && sit.standAt == null,
                                          seatedFor: sit ? t - sit.start : 0, perched: !!perched,
                                          perchedFor: perched ? t - perched.since : 0,
                                          canPerch: rig.canSit && seatsPx.length > 0,
                                          canHide: rig.canSit && hideoutsPx.length > 0 && !hide,
                                          canVisit: !!rig.node && !!planWindowVisit(hideoutsPx.map(e => ({ ...e, x: e.x / pxPerUnit })), room),
                                          canCard: !!testCard && t - cardAt > 3600 && !!rig.where?.('leftHand'),
                                          canUmbrella: rainComing && t - umbrellaAt > 1200 && !!rig.where?.('rightHand'),
                                          tired, sinceDoze: t - dozeAt,
                                          since: Object.fromEntries(Object.entries(doneAt).map(([k, at]) => [k, t - at])),
                                          canCross: crossFits({ perched, jumping: !!jumping, carried: !!carry }) },
                                Math.random(), Math.random()));
  if (visit && !waiting && visit.cut == null) visit.cut = t;
  if (visit?.cut != null && visit.phase !== 'touch') visit = null;
  // spoken to while she is behind a window: she comes out (straight away from the peek, or once she has stopped)
  if (hide && !waiting && !hide.early) {
    hide.early = true;
    if (hide.phase === 'peek') hide.start = Math.min(hide.start, t - (PEEK.length - 0.7));
  }
  // spoken to on her way somewhere, she slows to a stop where she is (a stroll in her box just plays out)
  if (walk?.trip && !waiting && !walk.cut && !walk.keep) {
    const leg = cutLeg(walk.leg, t - walk.start);
    if (leg !== walk.leg) [walk.leg, walk.peek] = [leg, false];
    walk.cut = true;
    walk.then = null;                               // and doesn't go on to jump up anywhere
  }
  const going = !walk ? null
    : walk.trip ? trip(t - walk.start, walk.leg, walk.side, walk.peek)
    : stroll(t - walk.start, strollReach, walk.side, walk.peek);
  if (walk?.trip) {
    if (going) stageX = walk.base + going.x;
    window.ariaTravel = [walk.id, (stageX - walk.base) * pxPerUnit, !!going];
  }
  if (walk && !going) {
    if (walk.then != null) leap(walk.then, false, walk.corner);         // arrived under the seat: up she goes
    const was = walk;
    walk = null;
    if (settles(was, t - was.start)) settledAt = t;
    // The routine advances after the walk has completely turned back and settled.
    if (hide && was.hide === 'in') [hide.phase, hide.start] = hide.early ? ['peek', t - PEEK.length] : ['peek', t];
    else if (hide && was.hide === 'out') endHide();
  }
  if (visit && visit.cut == null) {
    const next = windowRoutineStep(visit.phase, t - visit.start, {
      walking: !!walk, gesturing: !!doing, seated: !!sit, restFor: visit.restFor, sitDown: visit.sitDown,
    });
    if (next) {
      visit.phase = next.phase; visit.start = t;
      if (next.action === 'walk') {
        const destination = visit.edge + visit.out * 0.23;
        if (Math.abs(destination - stageX) >= 0.025) { walkTo(destination, null); walk.visit = true; }
      } else if (next.action === 'glance') start('quietGlance', -visit.out);
      else if (next.action === 'sit') begin({ sit: true, side: -visit.out });
      else if (next.action === 'stand') begin({ stand: true });
      else if (next.action === 'depart') { visit = null; begin({ stroll: Math.random() < 0.5 ? -1 : 1 }); }
    }
  }
  const noticing = visit?.phase === 'notice' ? destinationNotice(t - visit.start, visit.edge - stageX) : null;
  const visiting = visit?.phase === 'touch' ? windowVisitMotion(t - visit.start, visit.out, visit.cut == null ? null : t - visit.cut) : null;
  if (visit?.phase === 'touch' && visit.cut != null && !visiting) visit = null;
  // the peek, and then out again: she steps out well past the edge she peeked from
  const peeking = hide?.phase === 'peek' ? peekOut(t - hide.start, hide.out, hide.r) : null;
  if (hide?.phase === 'peek' && !peeking) {
    hide.phase = 'out';
    walkTo(hide.edge + hide.out * 0.35, 'out');
  } else if (peeking?.wave && !hide.waved && t - hide.start > 1.3) {
    hide.waved = true;
    start('wave', -hide.out);                        // the hand on the side she peeks out of
  }
  // a jump up onto a window or down from one: her whole world (and the overlay's window) goes up or down with her
  // (onto the bottom panel, `low`, she sits down over its edge and later gets up again: no jump)
  const air = !jumping ? null : jumping.low ? edgeSit(t - jumping.start, jumping.dy) : jump(t - jumping.start, jumping.dy);
  if (jumping) {
    if (air) stageY = jumping.base + air.y;
    window.ariaTravel = [jumping.id, 0, !!air, -(stageY - jumping.base) * pxPerUnit];
    if (!air) {
      perched = (jumping.low ? jumping.dy < 0 : jumping.dy > 0) ? { since: t, low: jumping.low, corner: jumping.corner || 0 } : null;
      jumping = null;
    }
  }
  now.ledge = air ? air.ledge : ease(now.ledge, perched ? 1 : 0, dt, 0.4);
  // carried: she swings on the way and her knees give as she is put down (standing free only)
  if (carry) carry.input = carryInput(carry.input, carry.at[0] / pxPerUnit, -carry.at[1] / pxPerUnit, t);
  held = ease(held, carry && !sit ? 1 : 0, dt, 0.15);
  sway = carrySwing(sway, carry ? carry.input.ax : 0, dt);
  const landing = !carry && !air && !perched && !sit && setDownAt != null ? setDown(t - setDownAt) : 0;
  const crouch = air ? air.crouch : landing;
  const onEdge = now.ledge > 0.001 || crouch > 0.001;
  const perchLift = onEdge ? (base = perchPose(now.ledge, crouch, base)).lift : 0;
  const steps = going && going.amount > 0 ? walkCycle(going.phase) : null;
  rig.root.position.x = stageX + (going && !walk?.trip ? going.x : 0);
  camera.position.x = ring.position.x = stageX;
  camera.position.y = 0.54 + stageY;
  // at the piano the camera rises a little and looks down, so the keys show (it circles the middle of her box, so
  // she stays where she is on the screen)
  const view = PIANO.view * Math.max(stage.turn, desk.turn);
  camera.position.y += 3.15 * Math.sin(view);
  camera.position.z = 3.15 * Math.cos(view);
  camera.lookAt(camera.position.x, 0.54 + stageY, 0);
  ring.position.y = RING_Y + stageY;
  // sitting, she turns side-on (so her skirt stays put) and her head and eyes turn back to you
  const seatYaw = seat ? sit.side * SEAT_YAW * seat.turn : perchSide * PERCH_YAW * now.ledge;
  rig.root.rotation.y = (going ? going.yaw : seatYaw) + PIANO.yaw * Math.max(stage.turn, desk.turn);
  rig.root.position.x += pianoShift(stage) - 0.08 * desk.turn;
  // her body moves back (along the way she faces) as far as her folding legs reach forward, so her feet stay put
  if (seat) {
    rig.root.position.x += seat.back * Math.sin(seatYaw);
    // sitting down she moves back over her planted feet; her box (the camera and the overlay's window together,
    // so nothing moves on the screen) follows most of that, keeping all of her (hair included) in it
    const centre = 0.65 * seat.back * Math.sin(seatYaw);
    camera.position.x = ring.position.x = stageX + centre;
    window.ariaTravel = [sit.id, centre * pxPerUnit, true];
  }
  if (peeking) rig.root.position.x += peeking.shift;
  rig.root.position.z = seat ? seat.back * Math.cos(seatYaw) : 0;
  const facing = going ? Math.max(0, 1 - Math.abs(going.yaw)) : 1;    // side-on, her head stops following the mouse
  now.talk = ease(now.talk, state === 'speaking' ? Math.min(1, told.out * 5) : 0, dt, 0.18);
  const talking = now.talk > 0.01 ? talkMotion(t, now.talk) : null;
  // what she is saying right now, from her voice's timeline of sounds (Engines/LipSync.py): her mouth takes its
  // shapes from it, and her head dips on the stressed syllables instead of nodding on a sine
  const saying = speech && state === 'speaking' ? performance.now() / 1000 - speech.start : null;
  const said = saying != null ? speechShapes(speech.segments, saying) : null;
  const laughing = laughMotion(saying != null && !walk && !jumping && !carry && !hide && !visit &&
    held < 0.01 && stage.show < 0.01 && desk.show < 0.01 ? speech.segments : null, saying);
  const spokenBeat = said ? speechBeat(speech.segments, saying) : 0;
  if (said && talking) talking.head = [0.3 * talking.head[0], talking.head[1], talking.head[2]];
  // music with a clear beat: she bobs along, standing, sitting or perched, but not on the move, mid-gesture,
  // behind a window or while she speaks; no report for 2 s (the music stopped, Aria quit) and it fades out
  const grooving = told.state !== 'sleeping' && beat && beat.bpm > 0 && t - beatTold < 2 && state !== 'speaking' && !going && !jumping &&
                   !hide && desk.show < 0.001 && stage.show < 0.001 && !(act && !FIDGETS.includes(doing?.name));
  // she gets into it bit by bit (head, then shoulders, then body), and a song she was into stopping gets a "huh?"
  const free = !going && !jumping && !carry && !hide && !visit && !(act && doing?.cut == null) && conversation.speaker === 'off' &&
               desk.show < 0.001 && stage.show < 0.001 && (state === 'idle' || state === 'listening');
  groove = grooveStep(groove, grooving, dt, !(beat && beat.bpm > 0 && t - beatTold < 2), free);
  now.bob = ease(now.bob, grooving ? Math.min(1, 0.4 + beat.conf) * groove.depth : 0, dt, grooving ? 0.6 : 0.3);
  const bobbing = now.bob > 0.01 && beat?.bpm ? bobMotion(beatsAt(beat, t), now.bob, beat.bpm, groove) : null;
  const huh = afterMusic(groove.after);
  // walking she leans a little into her speed; slowing down, her body carries on a moment and settles back (a spring)
  lean = spring(lean[0], lean[1], going ? 0.035 * going.speed - 0.022 * going.accel : 0, dt, 1.6, 0.35);

  // where she looks: the mouse; when it has been still a while, wherever her eyes wander; during some fidgets, there
  if (Math.abs(told.lookX - lastLook[0]) + Math.abs(told.lookY - lastLook[1]) > 0.03) {
    lastLook = [told.lookX, told.lookY];
    lookMovedAt = t;
  }
  const drifting = waiting && !walk && t - lookMovedAt > 5 && cue.attention === 0 && !(catching?.look > 0);
  now.wander = ease(now.wander, drifting ? 1 : 0, dt, drifting ? 1.2 : 0.25);
  const away = gazeWander(t);
  let lookX = told.lookX + (away[0] - told.lookX) * now.wander, lookY = told.lookY + (away[1] - told.lookY) * now.wander;
  if (noticing) { lookX += (noticing.x - lookX) * noticing.weight; lookY += (noticing.y - lookY) * noticing.weight; }
  if (visiting) { lookX += (visiting.look[0] - lookX) * visiting.weight; lookY += (visiting.look[1] - lookY) * visiting.weight; }
  if (huh.look) [lookX, lookY] = [lookX + huh.look[0], lookY + huh.look[1]];   // the music stopped: a glance up and aside
  // you're typing to her: she watches the box under her, looks back at you in a pause, glances aside in a long one
  const typing = typingAttention(typedAt == null ? null : t - typedAt, typingOpen && (state === 'idle' || state === 'listening'));
  now.typing = ease(now.typing, typing.lean, dt, typing.lean > now.typing ? 0.35 : 0.6);
  if (typing.down > 0) { lookX += (0 - lookX) * typing.down; lookY += (-0.85 - lookY) * typing.down; }
  if (typing.aside > 0) { lookX += (0.45 * typingSide - lookX) * typing.aside; lookY += (0.2 - lookY) * typing.aside; }
  const partner = conversationMotion(t - conversationSince, conversation.speaker, conversation.side);
  if (conversation.speaker !== 'off') { lookX = partner.gaze; lookY = 0.05; }
  if (desk.hands > 0.01) { lookX *= 1 - desk.hands; lookY += (-0.7 - lookY) * desk.hands; }
  if (stage.hands > 0.01) {                          // at the piano she looks down at her hands, or over at you
    const g = perf.glance;
    lookX += (0 - lookX) * stage.hands;
    lookY += (-0.8 * (1 - g) - lookY) * stage.hands;
  }
  if (act?.look) {
    const w = Math.min(1, act.weights?.head ?? act.weight);     // (her eyes go with her head when that leads)
    lookX += (act.look[0] - lookX) * w;
    lookY += (act.look[1] - lookY) * w;
  }

  // her eyes get there first, in small darts; her head turns after them and more slowly. A big jump of her gaze
  // comes with a blink, as in people (it hides the eyes snapping across)
  if (t < blinkAt && lookBlink(now.eyes, [lookX, lookY], t - lastBlink)) blinkAt = t;
  const dart = saccade(t);
  now.eyes[0] = ease(now.eyes[0], lookX + dart[0], dt, 0.07);
  now.eyes[1] = ease(now.eyes[1], lookY + dart[1], dt, 0.07);
  // (her head is on a spring, a little under-damped: it arrives a touch past where she looks and settles back.
  // Easing straight to the spot, it stopped like a camera on a motor)
  const headHz = now.wander > 0.5 ? 0.75 : 1.15;
  for (const i of [0, 1]) [now.look[i], now.lookV[i]] = spring(now.look[i], now.lookV[i], i ? lookY : lookX, dt, headHz, 0.62);
  // Hold through short gaps between syllables; let the whole gesture settle in silence.
  const voice = state === 'listening' ? told.mic * 10 : state === 'speaking' ? told.out * 5 : 0;
  voiceActivity = ease(voiceActivity, Math.max(0, Math.min(1, voice)), dt, voice > voiceActivity ? 0.18 : 0.8);
  const bodyFree = !walk && !sit && !perched && !jumping && !hide && !visit && !doing && !carry && held < 0.01 && stage.show < 0.01 && desk.show < 0.01;
  // listening, she nods (or tilts her head) when you pause after saying something (not in a duet: Claude talks then)
  listen = state === 'listening' && conversation.speaker === 'off' ? listenStep(listen, told.mic, dt) : listenAway(listen, dt);
  // speaking with her voice's timeline, her arm moves with her phrases (phraseGesture) instead of on a clock
  const timed = !!speech && state === 'speaking';
  const active = bodyFree && !timed ? activeBody(state, t - activeSince, voiceActivity, turnNumber) : {};
  if (phrasing && state !== 'speaking' && phrasing.stopAt === Infinity) phrasing.stopAt = performance.now() / 1000 - phrasing.start;
  const phrase = bodyFree && phrasing ? phraseGesture(phrasing.plan, performance.now() / 1000 - phrasing.start, phrasing.stopAt) : {};
  for (const [bone, v] of Object.entries(bodyFree ? listenNod(listen) : {}))
    active[bone] = (active[bone] || [0, 0, 0]).map((x, i) => x + (v[i] || 0));
  const turnBones = bodyFree ? cue.bones : {};

  // at the piano: only standing on the floor (perched, sitting, walking or behind a window she comes to it later)
  const pianoBody_ = piano && stage.show > 0.001 ? pianoBody(stage, perf) : null;
  const deskBody = desk.show > 0.001 ? focusBody(desk, t) : null;
  const ack = acknowledgementNow ? acknowledgement(acknowledgementNow.name, t - acknowledgementNow.start) : null;

  if (moodCue && t - moodCue.start >= 3.2) moodCue = null;
  const moodAge = moodCue ? t - moodCue.start : 0;
  const mood = moodCue?.name || characterMood(state, doing?.name);
  const strength = moodCue ? smooth01(moodAge / 0.45) * (1 - smooth01((moodAge - 2.1) / 1.1))
    : state === 'thinking' ? 0.55 : Math.max(0, Math.min(0.75, act?.weight || 0));
  const accent = characterAccent(mood, strength);
  for (const name of CHARACTER_MOODS) expressionNow[name] = ease(expressionNow[name], accent.face[name], dt, 0.45);

  // Under all of it, motion clips (motions.mjs, vrmrig.mjs setMotion), each where it fits:
  // - sitting still on a window's edge or on the floor: the sitting clips on her body above the hips (her legs keep
  //   the pose fitted to the seat, and their swing).
  // - walking: the walk clip (Mixamo's female walk), run by her own steps (going.phase), so its stride keeps pace
  //   with how fast she moves; her coded walk cycle gives way to it (and is all there is without the clip);
  // Standing is her own coded motion (the idle clips tried, mannequin and Mixamo, looked worse). Jumping, sitting
  // down or getting up, being carried, peeking, the piano and the desk are poses fitted to where she is: no clip.
  // A clip fades in slowly and gives way fast.
  const ready = rig.clipsReady && !tuning;
  const unheld = !jumping && !carry && held < 0.001 && !hide && !visit && !peeking && stage.show < 0.001 && desk.show < 0.001;
  const seated = unheld && !walk && ((perched && !air && now.ledge > 0.99) || (seat && seat.w > 0.999 && seat.standAt == null));
  sitClipW = ease(sitClipW, ready && seated ? 1 : 0, dt, seated ? 0.8 : 0.12);
  const walkKey = window.ariaWalkAs || 'walk';      // (another walk clip to try: window.ariaWalkAs = 'catwalk')
  walkClipW = ready && rig.hasClip?.(walkKey) && unheld && going ? going.amount : 0;     // (eased already: she speeds up and slows down)
  talkW = ease(talkW, state === 'speaking' ? 1 : 0, dt, 0.5);
  clipClock += dt * (1 - TIRED.idleSlow * tired);
  rig.setMotion?.([
    [walkKey, { phase: going?.phase ?? 0 }, walkClipW, 'full'],
    ['sit', clipClock, sitClipW * (1 - talkW), 'sit'], ['sitTalk', clipClock, sitClipW * talkW, 'sit'],
  ]);

  const follow = 1 - Math.exp(-dt / FOLLOW_S);
  const dangled = perched ? dangle(t, perched.corner) : held > 0.001 ? carryPose(held, sway.a * held) : {};
  for (const name of BONES) {
    const cur = now.bones[name], want = base.bones[name], out = [0, 0, 0, 0];
    // sitting is a smooth curve already, and how far her body drops is worked out from exactly this fold of her
    // legs: easing them on top would leave her feet floating or sinking while she sits down or gets up
    const exact = (seat || onEdge) && LEGS.has(name);
    for (let i = 0; i < 4; i++) {
      cur[i] = exact ? want[i] : ease(cur[i], want[i], dt, poseTransitionTime(state, previousState, name));
      activeBones[name][i] = ease(activeBones[name][i], (active[name]?.[i] || 0) + (turnBones[name]?.[i] || 0) + (bodyFree ? accent.bones[name]?.[i] || 0 : 0), dt, state === 'listening' ? 0.2 : 0.3);
      out[i] = cur[i] + activeBones[name][i] + (visiting?.bones[name]?.[i] || 0) + (exact && (onEdge || i === 0) ? 0 : (idle[name]?.[i] || 0) * (i === 0 && BREATHING.has(name) ? settle.idle : 1)) + (talking?.[name]?.[i] || 0) +
               (exact ? 0 : bobbing?.[name]?.[i] || 0) + (huh[name]?.[i] || 0) + (phrase.bones?.[name]?.[i] || 0) + (settle.bones[name]?.[i] || 0) + (tap.bones?.[name]?.[i] || 0);
      if (act?.adds?.[name]) out[i] += (act.adds[name][i] || 0) * Math.max(0, act.addWeight ?? act.weight);   // a gesture added on top of her pose
      if (perched && !air) out[i] += (dangled[name]?.[i] || 0) * now.ledge * (1 - Math.min(1, (act?.calm || 0) * Math.max(0, act?.weight || 0)));
      else if (!perched) out[i] += dangled[name]?.[i] || 0;          // carried (already weighted by how far she's held)
      if (steps?.bones[name]) out[i] += steps.bones[name][i] * going.amount * (1 - walkClipW);
    }
    if (name === 'head') {                            // her head follows her eyes a third of the way, and nods
      out[1] += now.look[0] * 0.32 * facing - 0.55 * seatYaw;
      out[0] += -now.look[1] * 0.2 * facing + 0.055 * spokenBeat;
      out[0] += partner.nod + (ack?.nod || 0);
      if (going) {                                    // walking: it turns before her body does, and at the edge it
        out[1] += 0.45 * going.ahead;                  // looks out past it, then back over her shoulder at you
        out[1] += Math.sign(going.yaw) * (0.25 * going.peek - 0.75 * going.glance);
        out[0] += 0.06 * going.peek;
      }
    } else if (name === 'neck') {
      out[0] += 0.02 * spokenBeat;
      out[1] += now.look[0] * 0.12 * facing - 0.25 * seatYaw;
      if (going) out[1] += 0.2 * going.ahead - Math.sign(going.yaw) * 0.3 * going.glance;
    } else if (name === 'chest') {                    // a big look takes her chest along a little
      out[0] += 0.02 * spokenBeat + 0.045 * now.typing;    // (and she leans in to what you type)
      out[1] += now.look[0] * 0.06 * facing - 0.1 * seatYaw;
      if (going) out[1] -= Math.sign(going.yaw) * 0.15 * going.glance;
    } else if (name === 'spine') {
      out[0] += lean[0] + (seat ? seat.lean : 0) + (air ? air.lean : 0);
      out[1] += now.look[0] * 0.03 * facing;
    }
    // Her pose, the idle movement, walking and talking are small angles that add up. A gesture is different: it
    // says where a bone should BE, so it is blended in as a rotation (the short way round, by its weight) and not
    // by mixing the angle numbers, which swings a turned arm through places no arm goes.
    for (let i = 0; i < 3; i++) out[i] += laughing.bones[name]?.[i] || 0;
    if (peeking?.bones[name]) for (let i = 0; i < 3; i++) out[i] += peeking.bones[name][i];
    if (tuning?.[name]) { rig.setBone(name, withinLimits(name, tuning[name]), null, 0, 1); continue; }
    // peeking, a wave is her arm only: the rest of her keeps leaning out past the edge
    let target = peeking && !/Shoulder|Arm|Hand/.test(name) ? null : act?.bones[name];
    let weight = act?.weights?.[name] ?? act?.weight ?? 0;       // (a gesture may lead with some bones: their own weight)
    if (pianoBody_?.[name]) [target, weight] = [pianoBody_[name], Math.min(1, stage.show * 1.5)];
    if (deskBody?.[name]) [target, weight] = [deskBody[name], Math.min(1, desk.show * 1.5)];
    // (a little under 0 and over 1 is meant: a gesture winds up the other way first, and goes a touch too far)
    if (target) rig.setBone(name, withinLimits(name, out), withinLimits(name, target), Math.max(-0.08, Math.min(1.1, weight)), follow, dt, cur);
    else rig.setBone(name, withinLimits(name, out), null, 0, follow, dt, cur);
  }

  const lift = (act?.lift || 0) + (steps ? steps.lift * going.amount * (1 - walkClipW) : 0) + (seat ? seat.lift : 0) + perchLift +
               (piano ? piano.layout.lift * stage.sit : 0) +
               (focus ? focus.layout.lift * desk.sit : 0) +
               (bobbing && !seat && !onEdge ? bobbing.lift : 0);
  const liftSpeed = (lift - now.lift) / dt;
  now.lift = lift;
  rig.root.position.y = stageY + lift;

  const blinkSlow = 1 + TIRED.blinkSlow * tired;                      // tired: heavier, slower blinks
  // a gesture that decides her eyes (nodding off) has them to itself: no blink of her own until it is over
  if (act?.ownBlinks && doing) blinkAt = Math.max(blinkAt, doing.start + GESTURES[doing.name] + 0.4);
  if (t >= blinkAt + BLINK.length * blinkSlow) [lastBlink, blinkAt] = [blinkAt, nextBlink(t, Math.random())];
  const shut = act?.eyes ? Math.max(0, Math.min(1, act.eyes * act.weight)) : 0;       // a yawn shuts her eyes
  // (at the piano she closes her eyes now and then, feeling the music)
  // her upper lids follow her eyes down (looking down with the lids wide open reads as a stare)
  const lids = 0.32 * Math.max(0, Math.min(1, -now.eyes[1] * facing));
  rig.setBlink(Math.max(laughing.eyes, blinkWeight(t, blinkAt, blinkSlow), shut, perf ? 0.85 * perf.dreamy * stage.hands : 0, lids,
                        TIRED.lids * tired * (1 - Math.min(1, (act?.alert || 0) * (act?.weight || 0)))));   // tired: heavy lids
  now.mouth = mouthWeight(now.mouth, state === 'speaking' ? told.out : 0, dt);
  // the sound decides the shape and the loudness how far it opens (a quiet word stays small, silence shuts it);
  // without a timeline (another voice engine) the shapes take turns on their own
  const loud = Math.min(1, 0.45 + 0.8 * now.mouth) * smooth01(now.mouth / 0.08);
  for (const k of Object.keys(now.say)) {
    // (a little over the sound's own opening: at exactly that her vowels looked mumbled)
    const want = said ? Math.min(1, 1.35 * said[k] * loud) : 0;
    now.say[k] = ease(now.say[k], want, dt, want > now.say[k] ? 0.05 : 0.09);
  }
  const shapes = said ? { ...now.say } : visemes(t, now.mouth);
  if (act?.mouth) shapes.aa = Math.max(shapes.aa, Math.max(0, Math.min(1, act.mouth * act.weight)));   // a yawn
  rig.setVisemes(shapes);
  now.surprised = ease(now.surprised, doing?.name === 'hop' ? 1 : Math.max(0, (act?.face?.surprised || 0) * Math.min(1, act?.weight || 0),
                                                                         catching?.face.surprised || 0, tap.face?.surprised || 0), dt, 0.12);
  const expressionWeight = Math.max(0, Math.min(1, act?.weight || 0));
  now.relaxed = ease(now.relaxed, Math.max(pose.expressions.relaxed || 0, (act?.face?.relaxed || 0) * expressionWeight,
                                           perf ? 0.7 * perf.dreamy * stage.hands : 0), dt);
  // Smiles follow recognizable gestures, not the loudness of a potentially serious reply.
  const smile = doing?.name === 'wave' ? 0.5 : Math.max((act?.face?.happy || 0) * expressionWeight, peeking?.face.happy || 0,
                                                       catching?.face.happy || 0, tap.face?.happy || 0);
  now.happy = ease(now.happy, Math.max(smile, laughing.happy, perf ? perf.glance * stage.hands : 0), dt, 0.2);
  rig.setExpression('surprised', now.surprised);
  rig.setExpression('relaxed', Math.max(now.relaxed * (1 - now.happy), 0.12 * expressionNow.focused));
  rig.setExpression('happy', Math.max(now.happy, 0.4 * expressionNow.amused));
  for (const name of CHARACTER_MOODS) rig.setExpression(name, expressionNow[name]);
  // her eyes follow the look while she faces you; side-on they look where she goes, except when she glances back
  let eyeX = now.eyes[0] * facing, eyeY = now.eyes[1] * facing;
  eyeX -= 2 * Math.tan(0.1 * seatYaw);              // what her head doesn't turn back, her eyes do
  if (going && going.glance > 0) eyeX += (-Math.max(-4, Math.min(4, 2 * Math.tan(going.yaw))) - eyeX) * going.glance;
  // at the piano her eyes are on her hands; glancing over, on you (turned away by the piano's angle)
  if (perf && stage.turn > 0.01) eyeX += perf.glance * stage.hands * 2 * Math.tan(-PIANO.yaw * stage.turn * 0.8);
  eyeX += typingEyeStep(typingKeys, typedAt == null ? null : t - typedAt) * typing.down;
  rig.look(eyeX, eyeY);
  // her hands: what her pose, her seat and a gesture each want of them, laid over hands hanging relaxed. They get
  // there a little after her arms do (her arms follow within a few frames): fingers are the last thing to settle
  if (Object.keys(pose.hands).length) now.poseHands = pose.hands;
  now.posed = ease(now.posed, Object.keys(pose.hands).length ? 1 : 0, dt, 0.4);
  const hands = handPose(t, [[now.poseHands, now.posed], [SIT_HANDS, seat ? seat.w : 0], [LEDGE_HANDS, now.ledge],
                             [phrase.hands, 1], [act?.hands, act?.handWeight ?? act?.weight ?? 0],
                             [visiting ? { [visiting.side]: HANDS.flat } : null, visiting?.weight || 0],
                             [catching ? { [catchSide]: HANDS.point } : null, catching?.point || 0]],
                         { talk: now.talk, swing: steps ? { left: steps.swing.left * going.amount, right: steps.swing.right * going.amount } : null });
  for (const side of ['left', 'right']) {
    const h = now.hands[side], want = tuning?.hands?.[side] || hands[side];
    h.curl = h.curl.map((c, i) => ease(c, want.curl[i], dt, 0.22 + 0.03 * i));     // index first, little finger last
    h.spread = ease(h.spread, want.spread, dt, 0.25);
    h.thumb = ease(h.thumb, want.thumb, dt, 0.25);
  }
  rig.setFingers?.(now.hands);
  if (visiting && rig.node && rig.wrist) {
    // Anchor the wrist to the actual window edge. The elbow stays below the
    // shoulder, and the body settles before the hand starts to reach.
    rig.root.updateMatrixWorld(true);
    const shoulder = rig.node(visiting.side + 'UpperArm');
    if (shoulder) {
      shoulder.getWorldPosition(visitPole);
      visitTarget.set(visit.edge + visit.out * 0.012, visitPole.y - 0.07, visitPole.z + 0.035);
      visitPole.x += visit.out * 0.08; visitPole.y -= 0.22; visitPole.z += 0.12;
      visitIK.reach(rig, visiting.side, visitTarget, visitPole, visiting.weight);
    }
  }
  // a gesture with a hand put somewhere on her own body (brushing her sleeve): that hand goes there by IK
  if (act?.ik && act.ik.weight > 0.001 && rig.node && rig.wrist) {
    rig.root.updateMatrixWorld(true);
    const elbow = rig.node(act.ik.sleeve + 'LowerArm'), shoulder = rig.node(act.ik.hand + 'UpperArm');
    if (elbow && shoulder) {
      elbow.getWorldPosition(selfAt);
      rig.wrist(act.ik.sleeve, selfTarget);
      selfTarget.sub(selfAt).multiplyScalar(act.ik.along).add(selfAt);   // that far along the forearm
      selfTarget.y += act.ik.above;
      selfTarget.z += 0.03;                                           // on the sleeve's front, not inside it
      shoulder.getWorldPosition(selfPole);
      selfPole.x += (act.ik.hand === 'left' ? 1 : -1) * 0.12; selfPole.y -= 0.25; selfPole.z += 0.02;   // elbow out and down
      visitIK.reach(rig, act.ik.hand, selfTarget, selfPole, Math.min(1, act.ik.weight), null, act.ik.weights);
    }
  }
  // the mouse pointer still beside her: now and then she reaches for it (logic.mjs catchStep), her hand put there by IK
  if (rig.node && rig.wrist) {
    rig.root.updateMatrixWorld(true);
    const at = pointerPx && [stageX + pointerPx.x / pxPerUnit, stageY + boxBottom() + pointerPx.y / pxPerUnit];
    const hips = rig.node('hips');
    if (at && hips && (!catching || catching.phase === 'off' || catching.phase === 'dwell')) {
      hips.getWorldPosition(catchAt);
      catchSide = at[0] > catchAt.x ? 'left' : 'right';           // (her left arm is on your right)
    }
    const upper = rig.node(catchSide + 'UpperArm'), lower = rig.node(catchSide + 'LowerArm');
    let near = false, arm = 0;
    if (at && upper && lower) {
      upper.getWorldPosition(catchPole);
      lower.getWorldPosition(catchAt);
      arm = catchPole.distanceTo(catchAt) + catchAt.distanceTo(rig.wrist(catchSide, selfAt));   // (catchTarget keeps where her hand went)
      const out = catchSide === 'left' ? 1 : -1;
      near = inReach([(at[0] - catchPole.x) * out, at[1] - catchPole.y], arm);
    }
    const free = !asleep && idleNow && !doing && !walk && !sit && !perched && !jumping && !hide && !visit && !carry && held < 0.01 &&
                 desk.show < 0.001 && stage.show < 0.001 && state === 'idle';
    catching = catchStep(catching, { near, free, moved: t - pointerMovedAt < 0.12 }, dt);
    if (catching.track && at && arm) {
      const [x, y] = reachPoint([catchPole.x, catchPole.y], at, arm);
      catchTarget.set(x, y, catchPole.z + pointerReach(catchPole.toArray(), catchSide).forward);                   // (a little in front of her, toward you)
    }
    if (catching.weight > 0.001 && upper) {
      upper.getWorldPosition(catchPole);
      catchPole.fromArray(pointerReach(catchPole.toArray(), catchSide).pole);
      const pointer = at ? [at[0], at[1], catchTarget.z] : catchTarget.toArray();
      catchPoint.fromArray(pointerDirection(rig.wrist(catchSide, selfAt).toArray(), pointer));
      catchPointer.fromArray(pointer);
      visitIK.reach(rig, catchSide, catchTarget, catchPole, catching.weight, catchPoint, catching.weights, catchPointer);
    }
  }
  rig.setBreeze?.(breeze(t));
  playPiano(stage, perf, dt);                       // (before update: a VRM takes its pose from the bones there)
  focus?.model.update(rig, desk, t, stageY, now.hands);
  rig.update(dt, liftSpeed);
  placeCard(doing?.name === 'showCard' && act ? Math.min(act.card ?? 0, act.weight) : 0);   // cut short: it goes down with her hands
  // cut short: it folds as it fades, going down with her arm
  placeUmbrella(doing?.name === 'umbrella' && act ? { ...act.umbrella, shown: Math.min(act.umbrella.shown, act.weight),
                                                        open: act.umbrella.open * act.weight ** 2 } : null);
  moveProps(dt);
  moveAcknowledgement();
}

/** The piano and her hands on it, after the rest of her is posed: the piano grows in where she sits, her arms
 *  reach the keys the performance chooses (IK), the keys under her fingers go down and notes float up. */
function playPiano(stage, perf, dt) {
  notes.update(dt);
  if (!piano) return;
  const m = piano.model;
  m.group.visible = stage.show > 0.01;
  if (!m.group.visible) { notes.hide(); return; }
  const grow = stage.show < 1 ? 1 + 2.2 * (stage.show - 1) ** 3 + 1.2 * (stage.show - 1) ** 2 : 1;    // a small pop
  m.group.position.set(rig.root.position.x, stageY, 0);
  m.group.rotation.y = PIANO.yaw;
  m.group.scale.setScalar(Math.max(0.01, grow));
  m.group.updateMatrixWorld(true);
  const pressed = [];
  if (perf && stage.hands > 0.001) {
    const { a, b, c, f } = pianoV;
    f.set(Math.sin(PIANO.yaw), 0, Math.cos(PIANO.yaw));                    // the way she faces at the piano
    const kw = m.kw, fingers = !!rig.fingerTip;
    for (const [side, hand, sign] of [['left', perf.L, 1], ['right', perf.R, -1]]) {
      // where the wrist should be: over the note, behind the fingers, dipping into the note (the arm's weight),
      // lifted between notes and at a phrase's breath; on the way to the keys it comes down from above
      const up = kw * (1.3 + 3.2 * hand.lift - 1.1 * hand.dip) + 0.1 * (1 - stage.hands);
      m.keyPoint(hand.x, up, a);
      m.group.localToWorld(a);
      a.addScaledVector(f, -(fingers ? 0.045 : 0.012) - 0.035 * hand.lift);   // lifting, the hand comes up and back
      // the hand follows that point on a spring: it travels with a little lag and settles (follow-through); the
      // elbow is aimed at the raw point, so it leads and the hand comes after it
      const st = pianoHands[side] ??= { p: a.clone(), v: new THREE.Vector3() };
      for (const k of ['x', 'y', 'z']) [st.p[k], st.v[k]] = spring(st.p[k], st.v[k], a[k], dt, 6, 0.75);
      // elbows: out to the side, a little below the keys, a touch behind; drawn toward where the hand is heading
      rig.node(`${side}UpperArm`).getWorldPosition(b);
      c.set(sign * Math.cos(PIANO.yaw), 0, -sign * Math.sin(PIANO.yaw));    // her left (or right), at the piano
      b.addScaledVector(c, 0.28).add(pianoV.d.set(0, -0.2, 0)).addScaledVector(f, -0.04);
      b.addScaledVector(pianoV.d.subVectors(a, st.p), 2.5);
      // the fingers point into the keys: further down as the wrist drops into a note, and hanging from the wrist
      // when the hand lifts off (the wrist leads, the fingers trail)
      const tilt = 0.45 + 0.45 * hand.dip + 0.8 * Math.min(1, hand.lift);
      const point = pianoV.e.copy(f).multiplyScalar(Math.cos(tilt)).setY(-Math.sin(tilt)).normalize();
      pianoIK.reach(rig, side, st.p, b, stage.hands, point);
      // the forearm rolls a little from note to note (thumb side, little-finger side)
      const lower = rig.node(`${side}LowerArm`);
      if (lower) lower.quaternion.multiply(pianoV.q.setFromAxisAngle(pianoV.x, 0.3 * hand.roll * stage.hands * sign));
      pressed.push([keyUnder(hand.x), hand.press * stage.hands]);
    }
    // her fingers: curved over the keys; the one playing curls down into its key, the others lift a little
    if (rig.setFingers) {
      const curl = hand => [0, 1, 2, 3].map(i => 1.15 + (i === hand.finger ? 0.8 * hand.press : -0.2 * hand.press) - 0.5 * Math.min(1, hand.lift));
      const mix = (side, hand) => mixHand(now.hands[side], { curl: curl(hand), spread: 0.4, thumb: 0.7 }, stage.hands);
      rig.setFingers({ left: mix('left', perf.L), right: mix('right', perf.R) });
    }
    // a note floats up now and then as her right hand strikes, more of them when it's loud
    if (perf.R.press > 0.9 && lastPress.R <= 0.9 && Math.random() < 0.15 + 0.35 * perf.intensity && stage.hands > 0.9) {
      m.keyPoint(perf.R.x, 0.12, a);
      notes.spawn(m.group.localToWorld(a), 0.07);
    }
    lastPress = { L: perf.L.press, R: perf.R.press };
  } else {
    pianoHands.left = pianoHands.right = null;
  }
  m.press(pressed);
}

/** How far she moves sideways while she plays: the piano reaches out to one side (the way she turns) and her box is
 *  narrow, so the two of them are centred together. */
function pianoShift(stage) { return -Math.sign(PIANO.yaw) * 0.14 * stage.turn; }

// She draws at the screen's own rate, awake or asleep. Chromium's own 60 fps pacing is off (ui/avatar_view
// unlock_frame_rate), so she paces herself: the next frame is asked for only when it is due. (Asking at once and
// skipping the early ones didn't work: a frame that draws nothing sends Chromium back to its 60 Hz timing, ~50 fps.)
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
  const time = performance.now();
  window.ariaFrames = (window.ariaFrames || 0) + 1;   // (frames drawn: tools/avatar_look.py can measure her frame rate)
  const dt = Math.min(0.1, last ? (time - last) / 1000 : 1 / FPS);
  last = time;
  nextFrame();                                      // (before drawing: an error in this frame doesn't stop her)
  t += dt;
  move(dt);
  renderer.render(scene, camera);
  if (!reported && !waitingForModel) {
    reported = true;
    window.ariaStatus = 'ready';
  }
}

/** Walk (across the screen, the overlay's window going along) until her middle is at stage x `x`; `tag` marks
 *  the walk as part of hiding ('in' or 'out'). A walk out is never cut short. */
function walkTo(x, tag) {
  const d = x - stageX;
  if (Math.abs(d) < 0.02) {
    walk = { start: t, side: 1, leg: 0, trip: true, base: stageX, id: ++tripId, cut: true, hide: tag, keep: true };
    return;
  }
  walk = { start: t, side: Math.sign(d), leg: legLength(Math.abs(d)), peek: false, trip: true, base: stageX,
           id: ++tripId, cut: false, hide: tag, keep: tag === 'out' };
}

/** Go behind a window and peek out from its edge at `x` pixels from her middle (`out`: -1 its left edge, 1 its
 *  right edge). */
function hideBehind(id, x, out) {
  const edge = stageX + x / pxPerUnit;
  hide = { id, out, edge, phase: 'in', start: t, r: Math.random(), early: false, waved: false };
  window.ariaBehind = id;
  walkTo(edge - out * PEEK.inset, 'in');
}

function endHide() {
  hide = null;
  window.ariaBehind = null;
  canvas.style.clipPath = '';
}

/** Jump `dy` units up onto a window (or down off it, negative). */
function leap(dy, low = false, corner = 0) {
  if (jumping || Math.abs(dy) < 0.05) return;
  jumping = { start: t, dy, base: stageY, id: ++tripId, low, corner };
  if (low ? dy < 0 : dy > 0) perchSide = Math.random() < 0.5 ? -1 : 1;
}

/** Where the window's top edge has to be, in units above her feet, for her to sit on it: her box's bottom is
 *  this far below her feet (the camera sees a little below the floor). */
function boxBottom() { return 0.54 - Math.tan(camera.fov * Math.PI / 360) * camera.position.z; }

function start(name, side = 1) {
  if (!detailFits(name, { walk, sit, perched, jumping, hide, visit, carried: !!carry })) return;
  if (name === 'hop' && (perched || jumping)) return;   // no hopping on top of a window
  if (name === 'crossAnkles' && !crossFits({ perched, jumping: !!jumping, carried: !!carry })) return;   // only on a window's edge
  if (name === 'hop' && sit) {                      // she can't hop sitting down: she gets up instead
    if (sit.standAt == null) sit.standAt = t - sit.start;
    return;
  }
  if (GESTURES[name]) doing = { name, start: t, side };
}

/** Something of her own (from chooseIdle): { gesture, side } | { stroll: ±1, peek } | { sit } | { stand }. */
function begin(act) {
  let name = act.gesture;
  if (act.gesture) start(act.gesture, act.side);
  if (act.gesture === 'showCard') cardAt = t;
  if (act.gesture === 'doze') dozeAt = t;
  if (act.gesture === 'umbrella') umbrellaAt = t;
  else if (act.windowVisit && !sit && !walk && !perched && !jumping && !hide && !visit && rig.node) {
    const plan = planWindowVisit(hideoutsPx.map(e => ({ ...e, x: e.x / pxPerUnit })), room, Math.random(), lastVisitedWindow);
    if (plan) {
      visit = { id: plan.id, out: plan.out, edge: stageX + plan.x, phase: 'notice', start: t, cut: null,
                restFor: 12 + Math.random() * 8, sitDown: rig.canSit && Math.random() < 0.4 };
      lastVisitedWindow = plan.id;
      name = 'windowVisit';
    }
  }
  else if (act.perch && !sit && !walk && !perched && !jumping && !hide && rig.canSit) {
    // the nearest window she can sit on: walk under the spot, then jump up onto it
    const plan = planPerch(seatsPx, Math.random(), 60, act.corner ? 0 : Math.random());
    if (plan) {
      const rise = -plan.y / pxPerUnit - (LEDGE_Y - boxBottom());
      if (plan.y > 0) leap(rise, true);              // the bottom panel's edge, just below her feet
      else if (Math.abs(plan.dx) < 20) leap(rise, false, plan.corner || 0);
      else walk = { start: t, side: Math.sign(plan.dx), leg: legLength(Math.abs(plan.dx) / pxPerUnit), peek: false,
                    trip: true, base: stageX, id: ++tripId, cut: false, then: rise, corner: plan.corner || 0 };
      name = 'perch';
    }
  } else if (act.hide && !sit && !walk && !perched && !jumping && !hide && rig.canSit) {
    const plan = planHide(hideoutsPx.map(e => ({ ...e, x: e.x / pxPerUnit })), Math.random());
    if (plan) {
      hideBehind(plan.id, (plan.dx + plan.out * PEEK.inset) * pxPerUnit, plan.out);
      name = 'hide';
    }
  } else if (act.hopDown && perched && !jumping) {
    if (perched.low) leap(-floorPx / pxPerUnit, true);   // up from the panel's edge (her floor is above her)
    else leap(-Math.max(0.06, floorPx / pxPerUnit));
    name = 'hopDown';
  } else if (act.stroll && !sit && !perched && !jumping && !hide) {
    // across the screen when the overlay has said how much room there is; otherwise a stroll in her box
    const plan = act.inBox ? null : planTrip(room, Math.random(), Math.random());
    if (plan) walk = { start: t, ...plan, trip: true, base: stageX, id: ++tripId, cut: false };
    else if (strollReach > 0.02) walk = { start: t, side: act.stroll, peek: !!act.peek };
    if (walk) name = 'stroll';
  }
  else if (act.sit && !sit && !walk && !hide && !perched && rig.canSit) [sit, name] = [{ start: t, standAt: null, side: act.side || 1, id: ++tripId }, 'sit'];
  else if (act.stand && sit && sit.standAt == null) [sit.standAt, name] = [t - sit.start, 'standUp'];
  if (name) recent = [name, ...recent].slice(0, 3);
  if (name && name in GESTURES || name === 'perch' || name === 'hide' || name === 'windowVisit') doneAt[name] = t;   // (only real moves: a made-up name from act() isn't kept)
  idleAt = t + (sit ? 9 + Math.random() * 10 : 5 + Math.random() * 7);
}

window.aria = {
  /** Pin bones to these angles ({ name: [x, y, z, twist] }) until called again without them: for fitting a pose.
   *  `hands: { left, right }` pins a hand's shape ({ curl: [4], spread, thumb }, logic.mjs HANDS) the same way. */
  tune(bones) { tuning = bones || null; },
  /** How many pixels of screen there are beside her box, to the left and to the right: room for walking about. */
  setRoom(left, right) { room = { left: Math.max(0, +left || 0) / pxPerUnit, right: Math.max(0, +right || 0) / pxPerUnit }; },
  /** Someone is dragging her window: a trip under way ends where she is. */
  /** Her window is being dragged and is now at screen pixels `x`, `y`; `carried(null)` when she is put down. */
  carried(x, y) {
    if (x == null || !Number.isFinite(+x) || !Number.isFinite(+y)) {
      if (carry && held > 0.3) setDownAt = t;        // (a short nudge is no landing)
      carry = null;
      return;
    }
    if (!carry) {
      carry = { at: [+x, +y], input: null };
      setDownAt = null;                             // picked up again straight away: no landing in the air
      if (walk && !walk.trip) walk = null;          // a stroll in her box ends: her feet are off the floor
    }
    carry.at = [+x, +y];
  },
  stopTrip() {
    if (walk?.trip) { window.ariaTravel = [walk.id, (stageX - walk.base) * pxPerUnit, false]; walk = null; }
    if (jumping) window.ariaTravel = [jumping.id, 0, false, -(stageY - jumping.base) * pxPerUnit];
    [jumping, perched] = [null, null];              // picked up off a window: she stands where she's put
    if (hide) endHide();
    if (visit) visit.cut = t;
  },
  /** Where she could sit on top of other windows ([{ x, half, y }] pixels from the middle of the bottom of her
   *  box) and how far below her box the floor is (pixels). */
  setSeats(list, floor) {
    seatsPx = Array.isArray(list) ? list.filter(s => [s?.x, s?.half, s?.y].every(Number.isFinite)) : [];
    floorPx = Number.isFinite(+floor) ? +floor : 0;   // (negative: her floor is above her, sitting on the panel)
  },
  /** The side edges of windows she could go behind: [{ id, x (pixels from the middle of her box), out }]. */
  setHideouts(list) {
    hideoutsPx = Array.isArray(list) ? list.filter(e => Number.isFinite(e?.x) && (e.out === 1 || e.out === -1)) : [];
    if (visit && visit.cut == null) {
      const edge = hideoutsPx.find(e => e.id === visit.id && e.out === visit.out);
      // A moved, closed or covered window is no longer a reliable hand target.
      if (!edge || Math.abs(stageX + edge.x / pxPerUnit - visit.edge) > 0.12) {
        visit.cut = t;
        if (walk?.visit && !walk.cut) { walk.leg = cutLeg(walk.leg, t - walk.start); walk.cut = true; }
      }
    }
  },
  /** A window was opened or raised over her ({ id, left, right }: its edges in pixels from the middle of her box):
   *  she is behind it, walks to the nearer edge and peeks out. */
  hiddenBy(win) {
    if (!sleepAllowsActivity(told.state) || !win || !idleNow || hide || sit || perched || jumping || walk || visit || !rig.canSit) return;
    const left = Math.abs(win.left) <= Math.abs(win.right);
    hideBehind(win.id, left ? win.left : win.right, left ? -1 : 1);
  },
  /** A window just came up right beside her (-1: on the left of the screen, 1: on the right): she flinches away
   *  from it and looks at it, standing about with nothing else going on. */
  startle(side) {
    const busy = !!(doing || walk || jumping || hide || visit || sit || perched || carry || atDesk || atPiano);
    if (!sleepAllowsActivity(told.state) || !mayStartle({ idle: idleNow, busy, sinceLast: t - startledAt })) return false;
    startledAt = t;
    start('brace', side < 0 ? 1 : -1);              // (on your left is on her right)
    return true;
  },
  /** The part of her box an app covers ({ left, top, right, bottom } in pixels of her box) is not drawn; null:
   *  all of her is. */
  setCover(rect) {
    if (!hide || !rect || ![rect.left, rect.top, rect.right, rect.bottom].every(Number.isFinite)) {
      canvas.style.clipPath = '';
      return;
    }
    const w = window.innerWidth, h = window.innerHeight;
    canvas.style.clipPath = `path(evenodd, "M0 0 H${w} V${h} H0 Z M${rect.left} ${rect.top} H${rect.right} V${rect.bottom} H${rect.left} Z")`;
  },
  /** The app she was behind went away (closed, minimized, moved off her): she stops where she is. */
  unhide() {
    if (!hide) return;
    if (walk?.hide) walk.hide = null;               // a walk under way just ends there
    endHide();
  },
  /** The window she sits on went away (closed, covered, made full-size): she hops down. */
  dropDown() { if (perched && !jumping) begin({ hopDown: true }); },
  /** How high above the bottom of her box the edge goes when she sits on one (pixels), for the overlay. */
  seatHeight() { return (LEDGE_Y - boxBottom()) * pxPerUnit; },
  /** How far above the edge she sits on her head reaches, ribbons included (pixels). */
  seatHeadroom() { return PERCH_HEADROOM * pxPerUnit; },
  setState(state) { told.state = String(state); },
  setEngaged(on) { told.engaged = !!on; },
  /** You clicked her: a quick blink and a little give, then she turns her attention to you. Not again while one is
   *  still going on (a few clicks in a row don't make her bounce). */
  tapped() {
    if (t - tappedAt < TAP.every) return;
    [tappedAt, tapSide, blinkAt] = [t, Math.random() < 0.5 ? -1 : 1, t];
  },
  /** Where the mouse pointer is: pixels from the middle of the bottom of her box (y up), and whether it moved
   *  (the pointer itself, not her box moving under it). */
  setPointer(x, y, moved) {
    pointerPx = Number.isFinite(+x) && Number.isFinite(+y) ? { x: +x, y: +y } : null;
    if (moved) pointerMovedAt = t;
  },
  /** The text box opened or closed (opening, nothing is typed yet). */
  setTyping(open) {
    if (!!open !== typingOpen) [typingOpen, typedAt, typingKeys] = [!!open, null, 0];
  },
  /** A key typed in the text box (what, she isn't told). */
  typed() {
    if (typedAt == null || t - typedAt > 3) typingSide = Math.random() < 0.5 ? -1 : 1;   // which way she glances, this pause
    typingKeys = typingKeyCount(typingKeys, typedAt == null ? null : t - typedAt);
    typedAt = t;
  },
  /** Piano music is playing (Spotify): she plays along on a keyboard while she stands on the floor. */
  setPiano(on) { told.piano = !!on; },
  setFocus(phase) {
    if (phase === 'break' && focusPhase === 'work') breakStretchAt = t + 1.9;
    focusPhase = ['work', 'break'].includes(phase) ? phase : 'off';
    if (focusPhase !== 'break') breakStretchAt = null;
  },
  setConversation(speaker, side) {
    if (speaker !== conversation.speaker) conversationSince = t;
    conversation = { speaker: ['aria', 'claude'].includes(speaker) ? speaker : 'off', side: side >= 0 ? 1 : -1 };
  },
  setLevel(mic, out) { told.mic = +mic || 0; told.out = +out || 0; },
  /** The sounds of the speech that started playing `elapsed` seconds ago ([start, end, shape, open, stress, optional laugh cue],
   *  seconds; Engines/LipSync.py), or null when nothing is being said. */
  setSpeech(segments, elapsed = 0) {
    speech = Array.isArray(segments) && segments.length ? { segments, start: performance.now() / 1000 - (+elapsed || 0) } : null;
    // her arms' gestures, planned once; kept after the speech is over so the last one is let go of properly
    if (speech) phrasing = { plan: phrasePlan(segments), start: speech.start, stopAt: Infinity };
  },
  lookAt(x, y) { told.lookX = Math.max(-1, Math.min(1, +x || 0)); told.lookY = Math.max(-1, Math.min(1, +y || 0)); },
  setProps,
  /** The next test for her card ({ subject, when }) or null. */
  setTest(test) { testCard = cardText(test); drawCard(); },
  /** Rain is coming: she brings out her umbrella now and then. */
  setRain(on) { rainComing = !!on; },
  setBeat(bpm, nextIn, conf) {
    beatTold = bpm > 0 ? t : -1e9;
    if (bpm > 0) beat = { ...beatClock(beat, +bpm, +nextIn, t), conf: +conf };   // stopped: the old clock fades out
  },
  /** Her picture as a PNG data URL, drawn now (for tools/avatar_look.py when the screen can't be grabbed). */
  snapshot() {
    if (!closeUp) renderer.render(scene, camera);
    else {                                            // a close look at one part of her (hands, hair): closeUp()
      const [x, y, height, yaw] = closeUp, cam = camera.clone();
      const at = new THREE.Vector3(rig.root.position.x + x, rig.root.position.y + y, rig.root.position.z);
      cam.fov = 2 * Math.atan(height / 2 / 3.15) * 180 / Math.PI;
      cam.position.set(at.x + 3.15 * Math.sin(yaw), at.y, at.z + 3.15 * Math.cos(yaw));
      cam.lookAt(at);
      cam.updateProjectionMatrix();
      renderer.render(scene, cam);
    }
    return canvas.toDataURL('image/png');
  },
  /** For tools/avatar_look.py: its shots show only the part of her `height` units high around (x, y) from her
   *  feet, seen from `yaw` radians round her (0: the front). Without arguments: all of her again. */
  closeUp(x, y, height, yaw = 0) { closeUp = height ? [+x, +y, +height, +yaw] : null; },
  /** Move her on by `seconds` without waiting for the screen (a locked screen pauses the page's frames): for
   *  tools/avatar_look.py, which then drives her itself. */
  debug() { return { asleep: wasAsleep, waking, seated: !!sit, perched: !!perched, t: +t.toFixed(3), doing: doing && { ...doing }, visit: visit && { ...visit },
                     catching: catching && { phase: catching.phase, t: +catching.t.toFixed(2), weight: +catching.weight.toFixed(2) } }; },    // for tools/avatar_look.py
  advance(seconds) {
    for (let left = +seconds || 0; left > 1e-6; left -= 1 / FPS) {
      const dt = Math.min(1 / FPS, left);
      t += dt;
      move(dt);
    }
    renderer.render(scene, camera);
  },
  fade(visible) { canvas.style.opacity = visible ? '1' : '0'; },
  hop() { start('hop'); },
  wave() { start('wave'); },
  /** Where bones really are right now, for checking a movement with numbers: { name: [x, y, z] }. */
  where(...names) { scene.updateMatrixWorld(true); return Object.fromEntries(names.map(n => [n, rig.where?.(n) ?? null])); },
  /** Do one of her own movements now (used when trying them out): a gesture's name ("curious:-1" for its other
   *  side), "stroll", "strollPeek", "sit", "stand", "perch" or "perchCorner" (sitting on a window's top corner). */
  act(name) {
    const [what, side] = String(name).split(':');
    const dir = side ? +side : Math.random() < 0.5 ? -1 : 1;
    if (what === 'stroll' || what === 'strollPeek') begin({ stroll: dir, peek: what === 'strollPeek', inBox: true });
    else if (what === 'trip') begin({ stroll: dir });
    else if (what === 'perchCorner') begin({ perch: true, corner: true });
    else if (what === 'perch' || what === 'hopDown' || what === 'hide' || what === 'windowVisit') begin({ [what]: true });
    else if (what === 'sit') begin({ sit: true, side: dir });
    else if (what === 'stand') begin({ stand: true });
    else begin({ gesture: what, side: dir });
  },
  // a reaction from the companion (Engines/Companion.py): only one that fits what she's doing right now
  emote(name) {
    if (!CHARACTER_MOODS.includes(name)) return false;
    moodCue = { name, start: t };
    return true;
  },
  react(name) {
    if (ACKNOWLEDGEMENTS.includes(name)) { showAcknowledgement(name); return; }
    if (atDesk || (focus && deskStageNow().show > 0.001) || atPiano) return;
    const g = reactionFor(String(name), { walking: !!walk, jumping: !!jumping, hiding: !!hide, gesturing: !!doing || !!visit,
                                          seated: !!sit, perched: !!perched });
    if (g) begin({ gesture: g, side: Math.random() < 0.5 ? -1 : 1 });
  },
  pause() { running = false; cancelAnimationFrame(raf); clearTimeout(timer); },
  resume() {
    if (running) return;
    running = true;
    last = 0;                                         // no jump after a pause
    rig.reset?.();                                    // and her hair hangs from where she is now, already settled
    raf = requestAnimationFrame(frame);
  },
};

// one frame as soon as we know who she is, so the overlay learns she is ready even while she waits hidden and paused
function firstFrame() {
  move(1 / FPS);                                    // her first pose, so her hair settles on it and not on a T-pose
  rig.reset?.();
  renderer.render(scene, camera);
  reported = true;
  window.ariaStatus = 'ready';
}
if (!waitingForModel) firstFrame();
