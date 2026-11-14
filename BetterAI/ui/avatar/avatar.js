// Aria's avatar page. The overlay (ui/avatar_view.py, AvatarLink) talks to it through window.aria; what she does
// with her body is decided in logic.mjs; her shape is figure.mjs, or a VRM file when one is given (vrmrig.mjs).
// It reports once through window.ariaStatus: "ready" after the first frame, or "failed: <why>".
import * as THREE from 'three';
import { BONES, GESTURES, FIDGETS, avatarState, poseFor, idleMotion, gesture, walkCycle, stroll, trip, planTrip, cutLeg, legLength, perchPose, dangle, jump, edgeSit, planPerch, LEDGE_Y, PERCH_YAW, PERCH_HEADROOM, PEEK, planHide, peekOut, talkMotion, visemes,
         saccade, lookBlink, chooseIdle, sitting, sitPose, spring, gazeWander, withinLimits, ease, nextBlink, blinkWeight,
         mouthWeight, ringPosition } from './logic.mjs';
import { buildFigure } from './figure.mjs';

const FPS = 30, RING_Y = 0.52;
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
let tuning = null;           // bones pinned to fixed angles while fitting a pose (window.aria.tune)
const told = { state: 'idle', mic: 0, out: 0, lookX: 0, lookY: 0, props: [] };
let running = false, raf = 0, last = 0, t = 0, reported = false;
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
// Peeking out from behind an app: the overlay says which side edges of windows she could go behind ({ id, x
// (pixels from the middle of her box), out }); she walks to just behind one, peeks out and walks back out. While
// she is behind a window, ariaBehind is its id and the overlay sends its rectangle (setCover): that part of her
// isn't drawn.
let hideoutsPx = [];
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
const now = { bones: poseFor('idle').bones, look: [0, 0], eyes: [0, 0], mouth: 0, surprised: 0, relaxed: 0, happy: 0,
              nod: 0, lift: 0, talk: 0, wander: 0, hair: 0, ledge: 0 };
let hairUntil = 0;                                  // her hair stays tucked behind her ear until then
const LEGS = new Set(['leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg']);
const SEAT_YAW = 1.15;      // how far she turns to sit (radians)
const FOLLOW_S = 0.045;     // every joint follows what it is told this closely: a new action can never make one pop
let blinkAt = nextBlink(0, Math.random()), lastBlink = -9;

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
  const micOpen = props.get('mic')?.wanted === true;
  const state = avatarState(told.state, micOpen);
  const pose = poseFor(state), idle = idleMotion(t);
  // with nothing going on she now and then does something of her own: while idle, and also while she is listening
  // but nobody is talking (an open microphone can mean a long wait). Never while thinking or speaking.
  // (and not while you're dealing with her: the text box open or a card up)
  const waiting = !told.engaged && (state === 'idle' || (state === 'listening' && told.mic < 0.012));
  if (!waiting) idleSince = t;

  // a fidget gives way quickly when something happens (a wave or a hop is meant, and plays out)
  if (doing && !waiting && FIDGETS.includes(doing.name) && doing.cut == null) doing.cut = t;
  let act = doing ? gesture(doing.name, t - doing.start, doing.side) : null;
  if (act && doing.cut != null) {
    act.weight *= 1 - smooth01((t - doing.cut) / 0.45);
    if (t - doing.cut >= 0.45) act = null;
  }
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
  if (!waiting || doing || walk || settling || jumping || hide) idleAt = Math.max(idleAt, t + 3 + Math.random() * 5);
  else if (t >= idleAt) begin(chooseIdle({ recent, idleFor: t - idleSince, seated: !!sit && sit.standAt == null,
                                          seatedFor: sit ? t - sit.start : 0, perched: !!perched,
                                          perchedFor: perched ? t - perched.since : 0,
                                          canPerch: rig.canSit && seatsPx.length > 0,
                                          canHide: rig.canSit && hideoutsPx.length > 0 && !hide },
                                Math.random(), Math.random()));
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
    if (walk.then != null) leap(walk.then);         // arrived under the seat: up she goes
    const was = walk;
    walk = null;
    if (hide && was.hide === 'in') [hide.phase, hide.start] = hide.early ? ['peek', t - PEEK.length] : ['peek', t];
    else if (hide && was.hide === 'out') endHide();
  }
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
      perched = (jumping.low ? jumping.dy < 0 : jumping.dy > 0) ? { since: t, low: jumping.low } : null;
      jumping = null;
    }
  }
  now.ledge = air ? air.ledge : ease(now.ledge, perched ? 1 : 0, dt, 0.4);
  const crouch = air ? air.crouch : 0;
  const onEdge = now.ledge > 0.001 || crouch > 0.001;
  const perchLift = onEdge ? (base = perchPose(now.ledge, crouch, base)).lift : 0;
  const steps = going && going.amount > 0 ? walkCycle(going.phase) : null;
  rig.root.position.x = stageX + (going && !walk?.trip ? going.x : 0);
  camera.position.x = ring.position.x = stageX;
  camera.position.y = 0.54 + stageY;
  ring.position.y = RING_Y + stageY;
  // sitting, she turns side-on (so her skirt stays put) and her head and eyes turn back to you
  const seatYaw = seat ? sit.side * SEAT_YAW * seat.turn : perchSide * PERCH_YAW * now.ledge;
  rig.root.rotation.y = going ? going.yaw : seatYaw;
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
  // walking she leans a little into her speed; slowing down, her body carries on a moment and settles back (a spring)
  lean = spring(lean[0], lean[1], going ? 0.035 * going.speed - 0.022 * going.accel : 0, dt, 1.6, 0.35);

  // where she looks: the mouse; when it has been still a while, wherever her eyes wander; during some fidgets, there
  if (Math.abs(told.lookX - lastLook[0]) + Math.abs(told.lookY - lastLook[1]) > 0.03) {
    lastLook = [told.lookX, told.lookY];
    lookMovedAt = t;
  }
  const drifting = waiting && !walk && t - lookMovedAt > 5;
  now.wander = ease(now.wander, drifting ? 1 : 0, dt, drifting ? 1.2 : 0.25);
  const away = gazeWander(t);
  let lookX = told.lookX + (away[0] - told.lookX) * now.wander, lookY = told.lookY + (away[1] - told.lookY) * now.wander;
  if (act?.look) {
    const w = Math.min(1, act.weight);
    lookX += (act.look[0] - lookX) * w;
    lookY += (act.look[1] - lookY) * w;
  }

  // her eyes get there first, in small darts; her head turns after them and more slowly. A big jump of her gaze
  // comes with a blink, as in people (it hides the eyes snapping across)
  if (t < blinkAt && lookBlink(now.eyes, [lookX, lookY], t - lastBlink)) blinkAt = t;
  const dart = saccade(t);
  now.eyes[0] = ease(now.eyes[0], lookX + dart[0], dt, 0.07);
  now.eyes[1] = ease(now.eyes[1], lookY + dart[1], dt, 0.07);
  now.look[0] = ease(now.look[0], lookX, dt, now.wander > 0.5 ? 0.7 : 0.45);
  now.look[1] = ease(now.look[1], lookY, dt, now.wander > 0.5 ? 0.7 : 0.45);
  now.nod = ease(now.nod, state === 'listening' ? Math.min(0.1, told.mic * 1.6) : 0, dt, 0.12);

  const follow = 1 - Math.exp(-dt / FOLLOW_S);
  const dangled = perched ? dangle(t) : {};
  for (const name of BONES) {
    const cur = now.bones[name], want = base.bones[name], out = [0, 0, 0, 0];
    // sitting is a smooth curve already, and how far her body drops is worked out from exactly this fold of her
    // legs: easing them on top would leave her feet floating or sinking while she sits down or gets up
    const exact = (seat || onEdge) && LEGS.has(name);
    for (let i = 0; i < 4; i++) {
      cur[i] = exact ? want[i] : ease(cur[i], want[i], dt);
      out[i] = cur[i] + (exact && onEdge ? 0 : idle[name]?.[i] || 0) + (talking?.[name]?.[i] || 0);
      if (perched && !air && LEGS.has(name)) out[i] += (dangled[name]?.[i] || 0) * now.ledge;
      if (steps?.bones[name]) out[i] += steps.bones[name][i] * going.amount;
    }
    if (name === 'head') {                            // her head follows her eyes a third of the way, and nods
      out[1] += now.look[0] * 0.32 * facing - 0.55 * seatYaw;
      out[0] += -now.look[1] * 0.2 * facing + now.nod;
      if (going) {                                    // walking: it turns before her body does, and at the edge it
        out[1] += 0.45 * going.ahead;                  // looks out past it, then back over her shoulder at you
        out[1] += Math.sign(going.yaw) * (0.25 * going.peek - 0.75 * going.glance);
        out[0] += 0.06 * going.peek;
      }
    } else if (name === 'neck') {
      out[1] += now.look[0] * 0.12 * facing - 0.25 * seatYaw;
      if (going) out[1] += 0.2 * going.ahead - Math.sign(going.yaw) * 0.3 * going.glance;
    } else if (name === 'chest') {                    // a big look takes her chest along a little
      out[1] += now.look[0] * 0.06 * facing - 0.1 * seatYaw;
      if (going) out[1] -= Math.sign(going.yaw) * 0.15 * going.glance;
    } else if (name === 'spine') {
      out[0] += lean[0] + (seat ? seat.lean : 0) + (air ? air.lean : 0);
      out[1] += now.look[0] * 0.03 * facing;
    }
    // Her pose, the idle movement, walking and talking are small angles that add up. A gesture is different: it
    // says where a bone should BE, so it is blended in as a rotation (the short way round, by its weight) and not
    // by mixing the angle numbers, which swings a turned arm through places no arm goes.
    if (peeking?.bones[name]) for (let i = 0; i < 3; i++) out[i] += peeking.bones[name][i];
    if (tuning?.[name]) { rig.setBone(name, withinLimits(name, tuning[name]), null, 0, 1); continue; }
    // peeking, a wave is her arm only: the rest of her keeps leaning out past the edge
    const target = peeking && !/Shoulder|Arm|Hand/.test(name) ? null : act?.bones[name];
    if (target) rig.setBone(name, withinLimits(name, out), withinLimits(name, target), Math.min(1, act.weight), follow);
    else rig.setBone(name, withinLimits(name, out), null, 0, follow);
  }

  const lift = (act?.lift || 0) + (steps ? steps.lift * going.amount : 0) + (seat ? seat.lift : 0) + perchLift;
  const liftSpeed = (lift - now.lift) / dt;
  now.lift = lift;
  rig.root.position.y = stageY + lift;

  if (t >= blinkAt + 0.15) [lastBlink, blinkAt] = [blinkAt, nextBlink(t, Math.random())];
  rig.setBlink(blinkWeight(t, blinkAt));
  now.mouth = mouthWeight(now.mouth, state === 'speaking' ? told.out : 0, dt);
  rig.setVisemes(visemes(t, now.mouth));
  now.surprised = ease(now.surprised, doing?.name === 'hop' ? 1 : 0, dt, 0.12);
  now.relaxed = ease(now.relaxed, Math.max(pose.expressions.relaxed || 0, act?.face?.relaxed || 0), dt);
  // a flicker of a smile on the louder moments, a small one for the wave, and whatever a fidget brings
  const smile = doing?.name === 'wave' ? 0.5 : Math.max(act?.face?.happy || 0, peeking?.face.happy || 0,
                                                       0.35 * now.talk * Math.max(0, Math.sin(t * 1.7)));
  now.happy = ease(now.happy, smile, dt, 0.2);
  // her hair, tucked behind her ear, stays there a while and then slips forward again (sooner once she walks off)
  if (act?.hair != null) {
    now.hair = Math.max(act.hair, now.hair);
    if (act.hair > 0.9) hairUntil = t + 6;
  } else if (t > hairUntil || (going && going.amount > 0.5)) now.hair = ease(now.hair, 0, dt, 1.2);
  rig.tuckHair?.(now.hair);
  rig.setExpression('surprised', now.surprised);
  rig.setExpression('relaxed', now.relaxed * (1 - now.happy));
  rig.setExpression('happy', now.happy);
  // her eyes follow the look while she faces you; side-on they look where she goes, except when she glances back
  let eyeX = now.eyes[0] * facing, eyeY = now.eyes[1] * facing;
  eyeX -= 2 * Math.tan(0.1 * seatYaw);              // what her head doesn't turn back, her eyes do
  if (going && going.glance > 0) eyeX += (-Math.max(-4, Math.min(4, 2 * Math.tan(going.yaw))) - eyeX) * going.glance;
  rig.look(eyeX, eyeY);
  rig.update(dt, liftSpeed);
  moveProps(dt);
}

function frame(time) {
  if (!running) return;
  raf = requestAnimationFrame(frame);
  if (time - last < 1000 / FPS - 2) return;
  const dt = Math.min(0.1, last ? (time - last) / 1000 : 1 / FPS);
  last = time;
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
function leap(dy, low = false) {
  if (jumping || Math.abs(dy) < 0.05) return;
  jumping = { start: t, dy, base: stageY, id: ++tripId, low };
  if (low ? dy < 0 : dy > 0) perchSide = Math.random() < 0.5 ? -1 : 1;
}

/** Where the window's top edge has to be, in units above her feet, for her to sit on it: her box's bottom is
 *  this far below her feet (the camera sees a little below the floor). */
function boxBottom() { return 0.54 - Math.tan(camera.fov * Math.PI / 360) * camera.position.z; }

function start(name, side = 1) {
  if (name === 'hop' && (perched || jumping)) return;   // no hopping on top of a window
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
  else if (act.perch && !sit && !walk && !perched && !jumping && !hide && rig.canSit) {
    // the nearest window she can sit on: walk under the spot, then jump up onto it
    const plan = planPerch(seatsPx, Math.random());
    if (plan) {
      const rise = -plan.y / pxPerUnit - (LEDGE_Y - boxBottom());
      if (plan.y > 0) leap(rise, true);              // the bottom panel's edge, just below her feet
      else if (Math.abs(plan.dx) < 20) leap(rise);
      else walk = { start: t, side: Math.sign(plan.dx), leg: legLength(Math.abs(plan.dx) / pxPerUnit), peek: false,
                    trip: true, base: stageX, id: ++tripId, cut: false, then: rise };
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
  idleAt = t + (sit ? 9 + Math.random() * 10 : 6 + Math.random() * 10);
}

window.aria = {
  /** Pin bones to these angles ({ name: [x, y, z, twist] }) until called again without them: for fitting a pose. */
  tune(bones) { tuning = bones || null; },
  /** How many pixels of screen there are beside her box, to the left and to the right: room for walking about. */
  setRoom(left, right) { room = { left: Math.max(0, +left || 0) / pxPerUnit, right: Math.max(0, +right || 0) / pxPerUnit }; },
  /** Someone is dragging her window: a trip under way ends where she is. */
  stopTrip() {
    if (walk?.trip) { window.ariaTravel = [walk.id, (stageX - walk.base) * pxPerUnit, false]; walk = null; }
    if (jumping) window.ariaTravel = [jumping.id, 0, false, -(stageY - jumping.base) * pxPerUnit];
    [jumping, perched] = [null, null];              // picked up off a window: she stands where she's put
    if (hide) endHide();
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
  },
  /** A window was opened or raised over her ({ id, left, right }: its edges in pixels from the middle of her box):
   *  she is behind it, walks to the nearer edge and peeks out. */
  hiddenBy(win) {
    if (!win || !idleNow || hide || sit || perched || jumping || walk || !rig.canSit) return;
    const left = Math.abs(win.left) <= Math.abs(win.right);
    hideBehind(win.id, left ? win.left : win.right, left ? -1 : 1);
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
  setLevel(mic, out) { told.mic = +mic || 0; told.out = +out || 0; },
  lookAt(x, y) { told.lookX = Math.max(-1, Math.min(1, +x || 0)); told.lookY = Math.max(-1, Math.min(1, +y || 0)); },
  setProps,
  fade(visible) { canvas.style.opacity = visible ? '1' : '0'; },
  hop() { start('hop'); },
  wave() { start('wave'); },
  /** Where bones really are right now, for checking a movement with numbers: { name: [x, y, z] }. */
  where(...names) { scene.updateMatrixWorld(true); return Object.fromEntries(names.map(n => [n, rig.where?.(n) ?? null])); },
  /** Do one of her own movements now (used when trying them out): a gesture's name ("curious:-1" for its other
   *  side), "stroll", "strollPeek", "sit" or "stand". */
  act(name) {
    const [what, side] = String(name).split(':');
    const dir = side ? +side : Math.random() < 0.5 ? -1 : 1;
    if (what === 'stroll' || what === 'strollPeek') begin({ stroll: dir, peek: what === 'strollPeek', inBox: true });
    else if (what === 'trip') begin({ stroll: dir });
    else if (what === 'perch' || what === 'hopDown' || what === 'hide') begin({ [what]: true });
    else if (what === 'sit') begin({ sit: true, side: dir });
    else if (what === 'stand') begin({ stand: true });
    else begin({ gesture: what, side: dir });
  },
  pause() { running = false; cancelAnimationFrame(raf); },
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
