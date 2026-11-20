// Claude's figure, for when he talks with Aria and Lala (Engines/Duet.py): an original character in the same toon
// style as hers (figure.mjs), made of simple shapes so he needs no model file. A calm, bookish young man: messy
// chestnut hair, round glasses, a cream knit sweater and a terracotta scarf (his bubbles are orange too). No logo.
// Same bones, same angle convention and same methods as her figure (see figure.mjs), so logic.mjs moves him too.
// About 1.0 units tall with his feet at y = 0: a little taller than her.

const SKIN = 0xffe2d0, HAIR = 0x7a4a32, HAIR_DARK = 0x5c3523, EYE = 0xd98a3a, EYE_DARK = 0x7a3f12, LINE = 0x2a1a14;
const SWEATER = 0xf2e4cf, SWEATER_DARK = 0xd9c6aa, SCARF = 0xd9774b, SCARF_DARK = 0xb85a33, PANTS = 0x4a3b36,
      SHOE = 0xc8643c, SOLE = 0xf6efe4, FRAME = 0x3b2a22;

export function buildClaude(THREE) {
  const steps = new THREE.DataTexture(new Uint8Array([120, 120, 120, 255, 200, 200, 200, 255, 255, 255, 255, 255]), 3, 1);
  steps.minFilter = steps.magFilter = THREE.NearestFilter;
  steps.needsUpdate = true;
  const toon = color => new THREE.MeshToonMaterial({ color, gradientMap: steps });
  const flat = (color, opacity = 1) => new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity });
  const outlineMat = new THREE.MeshBasicMaterial({ color: LINE, side: THREE.BackSide });

  const group = (parent, x = 0, y = 0, z = 0) => {
    const g = new THREE.Group();
    g.position.set(x, y, z);
    parent.add(g);
    return g;
  };
  // every solid part gets a dark shell behind it: the drawn outline
  const mesh = (parent, geometry, material, { at = [0, 0, 0], scale = [1, 1, 1], rot = [0, 0, 0], outline = 0.035 } = {}) => {
    const m = new THREE.Mesh(geometry, material);
    m.position.set(...at);
    m.scale.set(...scale);
    m.rotation.set(...rot);
    if (outline) {
      const shell = new THREE.Mesh(geometry, outlineMat);
      shell.scale.setScalar(1 + outline);
      m.add(shell);
    }
    parent.add(m);
    return m;
  };
  const sphere = r => new THREE.SphereGeometry(r, 28, 20);
  const capsule = (r, length) => new THREE.CapsuleGeometry(r, length, 6, 14);

  const root = new THREE.Group();
  const bones = {};

  // ── body: trousers, a loose knit sweater with a ribbed hem ──
  bones.hips = group(root, 0, 0.38, 0);
  mesh(bones.hips, sphere(0.078), toon(PANTS), { scale: [1.1, 0.8, 0.9] });
  mesh(bones.hips, new THREE.CylinderGeometry(0.098, 0.1, 0.035, 24), toon(SWEATER_DARK), { at: [0, 0.03, 0] });

  bones.spine = group(bones.hips, 0, 0.04, 0);
  bones.chest = group(bones.spine, 0, 0.075, 0);
  mesh(bones.chest, capsule(0.088, 0.08), toon(SWEATER), { at: [0, 0.0, 0], scale: [1, 1, 0.82] });
  for (const x of [-0.045, -0.015, 0.015, 0.045]) {        // knit cables down the front
    mesh(bones.chest, new THREE.CapsuleGeometry(0.004, 0.09, 4, 6), flat(SWEATER_DARK), { at: [x, -0.01, 0.073], outline: 0 });
  }

  for (const [side, sign] of [['left', 1], ['right', -1]]) {
    const shoulder = bones[`${side}Shoulder`] = group(bones.chest, sign * 0.03, 0.07, 0);
    const upper = bones[`${side}UpperArm`] = group(shoulder, sign * 0.062, 0, 0);
    mesh(upper, capsule(0.035, 0.08), toon(SWEATER), { at: [sign * 0.062, 0, 0], rot: [0, 0, Math.PI / 2] });
    const lower = bones[`${side}LowerArm`] = group(upper, sign * 0.13, 0, 0);
    mesh(lower, capsule(0.032, 0.062), toon(SWEATER), { at: [sign * 0.045, 0, 0], rot: [0, 0, Math.PI / 2] });
    mesh(lower, new THREE.TorusGeometry(0.031, 0.009, 6, 16), toon(SWEATER_DARK), { at: [sign * 0.09, 0, 0], rot: [0, Math.PI / 2, 0], outline: 0 });
    mesh(lower, sphere(0.033), toon(SKIN), { at: [sign * 0.125, 0, 0] });

    const thigh = bones[`${side}UpperLeg`] = group(bones.hips, sign * 0.05, -0.03, 0);
    mesh(thigh, capsule(0.042, 0.09), toon(PANTS), { at: [0, -0.075, 0] });
    const shin = bones[`${side}LowerLeg`] = group(thigh, 0, -0.16, 0);
    mesh(shin, capsule(0.038, 0.085), toon(PANTS), { at: [0, -0.07, 0] });
    mesh(shin, sphere(0.047), toon(SHOE), { at: [0, -0.155, 0.024], scale: [0.95, 0.6, 1.5] });
    mesh(shin, new THREE.CylinderGeometry(0.045, 0.047, 0.012, 20), flat(SOLE), { at: [0, -0.178, 0.024], scale: [0.95, 1, 1.5], outline: 0.06 });
  }

  // ── the scarf: wrapped round his neck, one end hanging down his front ──
  mesh(bones.chest, new THREE.TorusGeometry(0.062, 0.03, 10, 24), toon(SCARF), { at: [0, 0.098, 0], rot: [Math.PI / 2 - 0.15, 0, 0] });
  const scarfEnd = group(bones.chest, 0.04, 0.085, 0.07);
  mesh(scarfEnd, new THREE.BoxGeometry(0.045, 0.12, 0.016), toon(SCARF), { at: [0, -0.06, 0], rot: [0, 0, 0.12] });
  for (const x of [-0.014, 0, 0.014]) {                     // fringe at its tip
    mesh(scarfEnd, new THREE.CapsuleGeometry(0.004, 0.018, 4, 6), flat(SCARF_DARK), { at: [x + 0.012, -0.13, 0], outline: 0 });
  }
  mesh(scarfEnd, new THREE.BoxGeometry(0.047, 0.01, 0.018), flat(SCARF_DARK), { at: [0.004, -0.04, 0], rot: [0, 0, 0.12], outline: 0 });

  // ── head ──
  bones.neck = group(bones.chest, 0, 0.125, 0);
  mesh(bones.neck, capsule(0.027, 0.03), toon(SKIN), { at: [0, 0.01, 0], outline: 0 });
  bones.head = group(bones.neck, 0, 0.03, 0);
  const skull = group(bones.head, 0, 0.165, 0);
  mesh(skull, sphere(0.185), toon(SKIN), { scale: [0.97, 0.98, 0.95], outline: 0.03 });
  for (const sign of [1, -1]) mesh(skull, sphere(0.03), toon(SKIN), { at: [sign * 0.18, -0.02, 0], scale: [0.5, 1, 0.8], outline: 0 });

  // hair: a full cap, fuller at the back, and short messy tufts on top and over the forehead, swept to one side
  mesh(skull, new THREE.SphereGeometry(0.197, 32, 18, 0, Math.PI * 2, 0, 1.68), toon(HAIR), { at: [0, 0.018, -0.012], rot: [-0.5, 0, 0], outline: 0.03 });
  mesh(skull, sphere(0.19), toon(HAIR_DARK), { at: [0, 0.01, -0.06], scale: [0.98, 0.9, 0.72], outline: 0.03 });
  for (const [x, y, z, r, tilt] of [[-0.11, 0.12, 0.08, 0.06, 0.5], [-0.03, 0.15, 0.09, 0.065, 0.25], [0.06, 0.14, 0.08, 0.06, -0.1],
                                    [0.13, 0.1, 0.06, 0.055, -0.45], [0.0, 0.17, -0.02, 0.07, 0.1], [-0.12, 0.13, -0.06, 0.06, 0.6],
                                    [0.12, 0.13, -0.05, 0.06, -0.6]]) {
    mesh(skull, new THREE.ConeGeometry(r, 0.11, 10), toon(HAIR), { at: [x, y, z], rot: [0.5, 0, tilt], outline: 0.06 });
  }
  // the fringe: swept from his left to his right across the forehead
  for (const [x, len, rz] of [[-0.11, 0.07, 0.5], [-0.05, 0.08, 0.6], [0.02, 0.075, 0.7], [0.09, 0.06, 0.8]]) {
    const z = Math.sqrt(Math.max(0, 0.19 * 0.19 - x * x - 0.07 * 0.07));
    mesh(skull, sphere(0.03), toon(HAIR), { at: [x, 0.1 - len / 3, z - 0.004], scale: [0.9, len / 0.03, 0.25],
                                             rot: [-0.25, x * 4, rz], outline: 0.05 });
  }
  for (const sign of [1, -1]) {                               // sideburns
    mesh(skull, capsule(0.022, 0.05), toon(HAIR), { at: [sign * 0.17, 0.0, 0.07], rot: [0.1, 0, sign * 0.1], outline: 0.06 });
  }
  const tuft = group(skull, -0.02, 0.19, -0.01);              // one tuft that bounces when he moves
  mesh(tuft, new THREE.ConeGeometry(0.018, 0.08, 10), toon(HAIR), { at: [0, 0.03, 0], rot: [0.3, 0, 0.4], outline: 0.1 });

  // face: calm amber eyes behind round glasses, brows, a mouth that opens
  const eyes = [1, -1].map(sign => {
    const socket = group(skull, sign * 0.075, -0.03, 0.16);
    socket.rotation.y = sign * 0.4;
    const open = group(socket);
    mesh(open, sphere(0.044), flat(0xffffff), { scale: [0.95, 1.05, 0.3], outline: 0 });
    const iris = group(open, 0, -0.004, 0.012);
    mesh(iris, sphere(0.035), flat(EYE), { scale: [0.9, 1.05, 0.3], outline: 0 });
    mesh(iris, sphere(0.026), flat(EYE_DARK), { at: [0, 0.01, 0.004], scale: [0.95, 0.95, 0.3], outline: 0 });
    mesh(iris, sphere(0.012), flat(0x1a0d06), { at: [0, 0.002, 0.009], scale: [1, 1.2, 0.3], outline: 0 });
    mesh(iris, sphere(0.011), flat(0xffffff), { at: [sign * 0.01 + 0.005, 0.02, 0.014], scale: [1, 1, 0.3], outline: 0 });
    const lash = mesh(socket, new THREE.TorusGeometry(0.044, 0.005, 6, 18, Math.PI), flat(LINE), { at: [0, 0.008, 0.012], scale: [1, 0.85, 1], outline: 0 });
    const brow = mesh(skull, new THREE.CapsuleGeometry(0.005, 0.048, 4, 8), flat(HAIR_DARK),
                      { at: [sign * 0.078, 0.05, 0.172], rot: [0, 0, Math.PI / 2 - sign * 0.05], outline: 0 });
    // glasses: a round rim in front of each eye
    mesh(skull, new THREE.TorusGeometry(0.056, 0.006, 8, 28), flat(FRAME), { at: [sign * 0.075, -0.03, 0.188], rot: [0, sign * 0.3, 0], outline: 0 });
    mesh(skull, new THREE.CircleGeometry(0.054, 28), flat(0xcfe6ff, 0.12), { at: [sign * 0.075, -0.03, 0.19], rot: [0, sign * 0.3, 0], outline: 0 });
    mesh(skull, new THREE.CapsuleGeometry(0.004, 0.07, 4, 6), flat(FRAME), { at: [sign * 0.155, -0.02, 0.1], rot: [Math.PI / 2, 0, 0], outline: 0 });
    return { open, iris, lash, brow, browY: 0.05 };
  });
  mesh(skull, new THREE.CapsuleGeometry(0.004, 0.022, 4, 6), flat(FRAME), { at: [0, -0.02, 0.2], rot: [0, 0, Math.PI / 2], outline: 0 });
  const mouth = mesh(skull, sphere(0.02), flat(0x8e3a3a), { at: [0, -0.11, 0.17], scale: [1, 0.2, 0.3], outline: 0 });

  const state = { blink: 0, mouth: 0, round: 0, surprised: 0, relaxed: 0, happy: 0 };
  const euler = new THREE.Euler(), turn = new THREE.Quaternion(), aim = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0);
  const last = new Map();
  const face = () => {
    const wide = 1 + 0.14 * state.surprised - 0.12 * state.relaxed - 0.12 * state.happy;
    for (const eye of eyes) {
      eye.open.scale.set(wide, Math.max(0.06, wide * (1 - 0.94 * state.blink)), 1);
      eye.lash.position.y = 0.008 - 0.04 * state.blink;
      eye.lash.scale.y = 0.85 - 1.6 * state.blink;
      eye.brow.position.y = eye.browY + 0.02 * state.surprised + 0.006 * state.happy;
    }
    const open = Math.max(state.mouth, 0.5 * state.surprised);
    const across = 1 - 0.35 * open - 0.4 * state.round + 0.3 * Math.max(state.relaxed, state.happy) * (1 - open);
    mouth.scale.set(Math.max(0.35, across), 0.2 + 1.0 * open, 0.3);
  };
  face();

  const sum = axis => ['hips', 'spine', 'chest', 'neck', 'head'].reduce((total, name) => total + bones[name].rotation[axis], 0);
  let swing = { z: 0, vz: 0, x: 0, vx: 0 };

  return {
    root, bones,
    setBone(name, angles, toward, weight = 0, follow = 1) {
      const bone = bones[name];
      if (!bone) return;
      const set = (q, [x, y, z, twist = 0]) => {
        q.setFromEuler(euler.set(x, y, z));
        if (twist) q.multiply(turn.setFromAxisAngle(X, twist));
        return q;
      };
      set(bone.quaternion, angles);
      if (toward && weight) bone.quaternion.slerp(set(aim, toward), weight);
      const before = last.get(name);
      if (before && follow < 1) bone.quaternion.copy(before.slerp(bone.quaternion, follow));
      last.set(name, (before || new bone.quaternion.constructor()).copy(bone.quaternion));
    },
    setBlink(w) { state.blink = w; },
    setMouth(w) { state.mouth = w; state.round = 0; },
    setVisemes(v) {
      state.mouth = Math.max(v.aa || 0, v.ih || 0, v.ou || 0, v.ee || 0, v.oh || 0) * (0.75 + 0.25 * (v.aa || 0));
      state.round = Math.max(v.ou || 0, v.oh || 0);
    },
    reset() { last.clear(); },
    setExpression(name, w) { if (name in state) state[name] = w; },
    look(x, y) {
      for (const eye of eyes) eye.iris.position.set(0.012 * x, -0.004 + 0.01 * y, 0.012);
    },
    /** Once a frame: the face, and the scarf end and the tuft swinging to hang under whatever he does. */
    update(dt, liftSpeed = 0) {
      face();
      const hangZ = -sum('z'), hangX = -sum('x') + Math.max(-0.5, Math.min(0.5, liftSpeed * 0.9));
      // Small integration steps keep the cloth soft when the embedded page drops frames.
      const steps = Math.max(1, Math.ceil(dt * 120)), step = dt / steps;
      for (let i = 0; i < steps; i++) {
        swing.vz += ((hangZ - swing.z) * 60 - swing.vz * 6) * step;
        swing.z += swing.vz * step;
        swing.vx += ((hangX - swing.x) * 60 - swing.vx * 6) * step;
        swing.x += swing.vx * step;
      }
      scarfEnd.rotation.z = 0.6 * swing.z;
      scarfEnd.rotation.x = 0.4 * Math.max(-0.2, swing.x);
      tuft.rotation.z = 0.8 * swing.z;
      tuft.rotation.x = 0.8 * swing.x;
    },
  };
}
