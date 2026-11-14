// Aria's built-in figure: a small anime-style character made entirely of simple shapes, so she needs no model
// file. She faces the viewer (+z) in a T-pose with her left arm along +x; logic.mjs describes her poses in that
// convention, and avatar.js drives her through the same few methods a loaded VRM offers (vrmrig.mjs):
//   root, setBone(name, [x, y, z, twist], toward?, weight?), setBlink(w), setMouth(w), setVisemes({aa, ih, ou, ee, oh}),
//   setExpression(name, w), look(x, y), reset(), update(dt, liftSpeed)
// About 0.95 units tall with her feet at y = 0.

const SKIN = 0xffe6d8, HAIR = 0x9a7bf0, HAIR_DARK = 0x7a5ce0, EYE = 0x45bdf5, EYE_DARK = 0x1d3f8a;
const HOODIE = 0x2b2740, TRIM = 0xb9a3ff, SKIRT = 0x40396b, SOCK = 0xf6f3ff, SHOE = 0x7a5ce0, LINE = 0x1a1426;

export function buildFigure(THREE) {
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
  // every solid part gets a dark shell behind it: the drawn outline of an anime figure
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

  // ── body ──
  bones.hips = group(root, 0, 0.36, 0);
  mesh(bones.hips, sphere(0.075), toon(SKIRT), { scale: [1.05, 0.75, 0.9] });
  mesh(bones.hips, new THREE.CylinderGeometry(0.07, 0.155, 0.13, 28, 1, true),
       new THREE.MeshToonMaterial({ color: SKIRT, gradientMap: steps, side: THREE.DoubleSide }), { at: [0, -0.045, 0], outline: 0.04 });
  mesh(bones.hips, new THREE.TorusGeometry(0.153, 0.006, 6, 28), flat(TRIM), { at: [0, -0.105, 0], rot: [Math.PI / 2, 0, 0], outline: 0 });

  bones.spine = group(bones.hips, 0, 0.04, 0);
  bones.chest = group(bones.spine, 0, 0.07, 0);
  mesh(bones.chest, capsule(0.078, 0.07), toon(HOODIE), { at: [0, 0.015, 0], scale: [1, 1, 0.85] });
  mesh(bones.chest, new THREE.TorusGeometry(0.058, 0.028, 10, 24), toon(HOODIE), { at: [0, 0.105, -0.01], rot: [Math.PI / 2 - 0.25, 0, 0] });
  mesh(bones.chest, new THREE.CapsuleGeometry(0.006, 0.05, 4, 8), flat(TRIM), { at: [-0.022, 0.045, 0.068], outline: 0 });
  mesh(bones.chest, new THREE.CapsuleGeometry(0.006, 0.04, 4, 8), flat(TRIM), { at: [0.022, 0.05, 0.068], outline: 0 });

  for (const [side, sign] of [['left', 1], ['right', -1]]) {
    const upper = bones[`${side}UpperArm`] = group(bones.chest, sign * 0.085, 0.075, 0);
    mesh(upper, capsule(0.034, 0.075), toon(HOODIE), { at: [sign * 0.06, 0, 0], rot: [0, 0, Math.PI / 2] });
    const lower = bones[`${side}LowerArm`] = group(upper, sign * 0.125, 0, 0);
    mesh(lower, capsule(0.03, 0.06), toon(HOODIE), { at: [sign * 0.045, 0, 0], rot: [0, 0, Math.PI / 2] });
    mesh(lower, new THREE.TorusGeometry(0.031, 0.008, 6, 16), flat(TRIM), { at: [sign * 0.092, 0, 0], rot: [0, Math.PI / 2, 0], outline: 0 });
    mesh(lower, sphere(0.033), toon(SKIN), { at: [sign * 0.125, 0, 0] });

    const thigh = bones[`${side}UpperLeg`] = group(bones.hips, sign * 0.052, -0.03, 0);
    mesh(thigh, capsule(0.04, 0.08), toon(SKIN), { at: [0, -0.07, 0] });
    const shin = bones[`${side}LowerLeg`] = group(thigh, 0, -0.15, 0);
    mesh(shin, capsule(0.037, 0.075), toon(SOCK), { at: [0, -0.065, 0] });
    mesh(shin, sphere(0.045), toon(SHOE), { at: [0, -0.15, 0.022], scale: [0.95, 0.62, 1.45] });
  }

  // ── head ──
  bones.neck = group(bones.chest, 0, 0.12, 0);
  mesh(bones.neck, capsule(0.026, 0.03), toon(SKIN), { at: [0, 0.01, 0], outline: 0 });
  bones.head = group(bones.neck, 0, 0.03, 0);
  const skull = group(bones.head, 0, 0.165, 0);
  mesh(skull, sphere(0.19), toon(SKIN), { scale: [1, 0.95, 0.96], outline: 0.03 });
  for (const sign of [1, -1]) mesh(skull, sphere(0.03), toon(SKIN), { at: [sign * 0.185, -0.02, 0], scale: [0.5, 1, 0.8], outline: 0 });

  // hair: a cap tilted back off the face, fuller behind, a fringe, two tails and a strand that sticks up
  mesh(skull, new THREE.SphereGeometry(0.203, 32, 18, 0, Math.PI * 2, 0, 1.72), toon(HAIR), { at: [0, 0.012, -0.012], rot: [-0.42, 0, 0], outline: 0.03 });
  mesh(skull, sphere(0.2), toon(HAIR_DARK), { at: [0, 0.03, -0.07], scale: [0.97, 0.88, 0.7], outline: 0.03 });
  // the fringe: a smooth band of hair over the forehead that follows the head, cut straight above the brows,
  // with a few locks hanging past its edge
  mesh(skull, new THREE.SphereGeometry(0.2, 32, 14, Math.PI / 2 - 1.2, 2.4, 0, 1.2), toon(HAIR), { scale: [1, 0.97, 0.98], outline: 0.025 });
  for (const [x, length] of [[-0.118, 0.05], [-0.04, 0.062], [0.045, 0.055], [0.122, 0.048]]) {
    const z = Math.sqrt(Math.max(0, 0.2 * 0.2 - x * x - 0.06 * 0.06));
    mesh(skull, sphere(0.03), toon(HAIR), { at: [x, 0.078 - length / 2, z - 0.004], scale: [0.85, length / 0.03, 0.22],
                                             rot: [-0.15, x * 4.6, -x * 1.2], outline: 0.05 });
  }
  for (const sign of [1, -1]) {
    mesh(skull, capsule(0.03, 0.11), toon(HAIR), { at: [sign * 0.168, -0.045, 0.075], scale: [0.7, 1, 0.9], rot: [0.05, 0, sign * 0.12], outline: 0.06 });
  }
  const strand = group(skull, 0.01, 0.195, 0.01);
  mesh(strand, new THREE.ConeGeometry(0.014, 0.085, 10), toon(HAIR), { at: [0.012, 0.035, 0], rot: [0, 0, -0.5], outline: 0.1 });

  const tails = [1, -1].map(sign => {
    const base = group(skull, sign * 0.178, 0.045, -0.035);
    mesh(base, sphere(0.03), flat(TRIM), { outline: 0.08 });
    const segments = [];
    let parent = base;
    for (const [r, stretch, drop] of [[0.05, 1.9, -0.085], [0.036, 1.7, -0.05]]) {      // a long teardrop and its tip
      const seg = group(parent, 0, parent === base ? -0.01 : -0.165, 0);
      mesh(seg, sphere(r), toon(HAIR), { at: [0, drop, 0], scale: [0.85, stretch, 0.85], outline: 0.04 });
      segments.push(seg);
      parent = seg;
    }
    return { sign, segments, z: 0, vz: 0, x: 0, vx: 0 };
  });

  // face: big eyes that can close, look around and widen; brows; a mouth that opens; a little blush
  const eyes = [1, -1].map(sign => {
    const socket = group(skull, sign * 0.079, -0.03, 0.166);
    socket.rotation.y = sign * 0.4;
    const open = group(socket);
    mesh(open, sphere(0.05), flat(0xffffff), { scale: [0.92, 1.18, 0.3], outline: 0 });
    const iris = group(open, 0, -0.004, 0.012);
    mesh(iris, sphere(0.04), flat(EYE), { scale: [0.9, 1.15, 0.3], outline: 0 });
    mesh(iris, sphere(0.03), flat(EYE_DARK), { at: [0, 0.012, 0.004], scale: [0.95, 0.95, 0.3], outline: 0 });
    mesh(iris, sphere(0.014), flat(0x0b1024), { at: [0, 0.002, 0.009], scale: [1, 1.25, 0.3], outline: 0 });
    mesh(iris, sphere(0.013), flat(0xffffff), { at: [sign * 0.012 + 0.006, 0.024, 0.014], scale: [1, 1, 0.3], outline: 0 });
    mesh(iris, sphere(0.006), flat(0xffffff), { at: [-0.014, -0.022, 0.014], scale: [1, 1, 0.3], outline: 0 });
    const lash = mesh(socket, new THREE.TorusGeometry(0.05, 0.0065, 6, 18, Math.PI), flat(LINE), { at: [0, 0.012, 0.012], scale: [0.98, 1.0, 1], outline: 0 });
    const brow = mesh(skull, new THREE.CapsuleGeometry(0.0045, 0.045, 4, 8), flat(HAIR_DARK),
                      { at: [sign * 0.08, 0.052, 0.176], rot: [0, 0, Math.PI / 2 + sign * 0.12], outline: 0 });
    return { open, iris, lash, brow, browY: 0.052 };
  });
  for (const sign of [1, -1]) {
    mesh(skull, new THREE.CircleGeometry(0.026, 20), flat(0xff9bb0, 0.42), { at: [sign * 0.118, -0.085, 0.148], rot: [0.2, sign * 0.72, 0], scale: [1.25, 0.7, 1], outline: 0 });
  }
  const mouth = mesh(skull, sphere(0.02), flat(0x9c3348), { at: [0, -0.112, 0.176], scale: [1, 0.2, 0.3], outline: 0 });

  const state = { blink: 0, mouth: 0, round: 0, surprised: 0, relaxed: 0, happy: 0 };
  const euler = new THREE.Euler(), turn = new THREE.Quaternion(), aim = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0);
  const last = new Map();                           // where each joint was last frame (for the follow filter)
  const face = () => {
    const wide = 1 + 0.16 * state.surprised - 0.1 * state.relaxed;
    for (const eye of eyes) {
      eye.open.scale.set(wide, Math.max(0.06, wide * (1 - 0.94 * state.blink)), 1);
      eye.lash.position.y = 0.012 - 0.045 * state.blink;
      eye.lash.scale.y = 1 - 1.7 * state.blink;          // an arc above the open eye, a downward curve when shut
      eye.brow.position.y = eye.browY + 0.022 * state.surprised + 0.004 * state.relaxed;
    }
    const open = Math.max(state.mouth, 0.55 * state.surprised);
    const across = 1 - 0.35 * open - 0.4 * state.round + 0.25 * Math.max(state.relaxed, state.happy) * (1 - open);
    mouth.scale.set(Math.max(0.35, across), 0.2 + 1.1 * open, 0.3);
  };
  face();

  const sum = axis => ['hips', 'spine', 'chest', 'neck', 'head'].reduce((total, name) => total + bones[name].rotation[axis], 0);

  return {
    root, bones,
    /** Put a bone at `angles`; with `toward` and `weight`, that far along the short way round to `toward`. */
    setBone(name, angles, toward, weight = 0, follow = 1) {
      const bone = bones[name];
      if (!bone) return;
      const set = (q, [x, y, z, twist = 0]) => {
        q.setFromEuler(euler.set(x, y, z));
        if (twist) q.multiply(turn.setFromAxisAngle(X, twist));                   // about her own arm, before the rest
        return q;
      };
      set(bone.quaternion, angles);
      if (toward && weight) bone.quaternion.slerp(set(aim, toward), weight);
      // and it gets there by `follow` of the way from where it was (1: at once): a filter on every joint, so a new
      // action starting or one being cut short never makes a joint pop
      const before = last.get(name);
      if (before && follow < 1) bone.quaternion.copy(before.slerp(bone.quaternion, follow));
      last.set(name, (before || new bone.quaternion.constructor()).copy(bone.quaternion));
    },
    setBlink(w) { state.blink = w; },
    setMouth(w) { state.mouth = w; state.round = 0; },
    /** The vowel shapes: she has one mouth, so they open it, and "ou" / "oh" make it round. */
    setVisemes(v) {
      state.mouth = Math.max(v.aa || 0, v.ih || 0, v.ou || 0, v.ee || 0, v.oh || 0) * (0.75 + 0.25 * (v.aa || 0));
      state.round = Math.max(v.ou || 0, v.oh || 0);
    },
    reset() { last.clear(); },
    where(name) { return bones[name] ? bones[name].getWorldPosition(new THREE.Vector3()).toArray().map(n => +n.toFixed(3)) : null; },
    setExpression(name, w) { if (name in state) state[name] = w; },
    /** Where her eyes look: x and y from -1 to 1. */
    look(x, y) {
      for (const eye of eyes) eye.iris.position.set(0.013 * x, -0.004 + 0.011 * y, 0.012);
    },
    /** Once a frame, after the bones are set: the face, and the tails swinging to hang under whatever she does. */
    update(dt, liftSpeed = 0) {
      face();
      const hangZ = -sum('z'), hangX = -sum('x') + Math.max(-0.5, Math.min(0.5, liftSpeed * 0.9));
      for (const tail of tails) {
        tail.vz += ((hangZ - tail.z) * 70 - tail.vz * 7) * dt;
        tail.z += tail.vz * dt;
        tail.vx += ((hangX - tail.x) * 70 - tail.vx * 7) * dt;
        tail.x += tail.vx * dt;
        tail.segments.forEach((seg, i) => {
          seg.rotation.z = (i === 0 ? tail.sign * 0.3 : tail.sign * -0.06) + tail.z * (i === 0 ? 1 : 0.35);
          seg.rotation.x = (i === 0 ? -0.08 : 0.05) + tail.x * (i === 0 ? 1 : 0.4);
        });
      }
      strand.rotation.z = tails[0].z * 0.8;
      strand.rotation.x = tails[0].x * 0.8;
    },
  };
}
