// Aria's piano: the 3D parts. The model (a small white grand piano and its bench, made of simple shapes in her toon
// style), the IK that puts her hands on its keys, and the little notes that float up. What she plays, where she
// sits and when she comes and goes are decided in logic.mjs (pianoLayout, pianoStage, pianoPerformance, pianoBody);
// avatar.js puts it together each frame.
//
// The piano is built in her own frame (she faces +z, her left is +x) from her layout, and turned with PIANO.yaw.
// Her left hand plays the low notes, so the low end of the keyboard is on her left (+x): keyboard x = -1 is +x.

const LINE = 0x1a1426, CASE = 0xf6f2ff, CASE_SHADE = 0xd9d0f2, TRIM = 0x7a5ce0, BLACK = 0x231d33, WOOD = 0x6b4a8c;

export function buildPiano(THREE, layout, keyCount) {
  const steps = new THREE.DataTexture(new Uint8Array([120, 120, 120, 255, 200, 200, 200, 255, 255, 255, 255, 255]), 3, 1);
  steps.minFilter = steps.magFilter = THREE.NearestFilter;
  steps.needsUpdate = true;
  const toon = color => new THREE.MeshToonMaterial({ color, gradientMap: steps });
  const line = new THREE.MeshBasicMaterial({ color: LINE, side: THREE.BackSide });
  const add = (parent, geometry, material, at = [0, 0, 0], { rot = [0, 0, 0], outline = 0.03 } = {}) => {
    const m = new THREE.Mesh(geometry, material);
    m.position.set(...at);
    m.rotation.set(...rot);
    if (outline) {
      const shell = new THREE.Mesh(geometry, line);
      shell.scale.setScalar(1 + outline);
      m.add(shell);
    }
    parent.add(m);
    return m;
  };

  const { keyY, keyZ, keyWidth: W, benchY, benchZ } = layout;
  const group = new THREE.Group();
  const kw = W / keyCount, keyDepth = W * 0.2;

  // ── the keys: white ones that go down when pressed, black ones in twos and threes ──
  const whiteMat = toon(0xfdfcff), blackMat = toon(BLACK);
  const keys = [];
  for (let i = 0; i < keyCount; i++) {
    const x = W / 2 - kw * (i + 0.5);                          // key 0, the lowest, on her left
    keys.push(add(group, new THREE.BoxGeometry(kw * 0.92, kw * 0.5, keyDepth), whiteMat, [x, keyY - kw * 0.25, keyZ + keyDepth / 2], { outline: 0 }));
    if (i % 7 !== 2 && i % 7 !== 6 && i < keyCount - 1) {
      add(group, new THREE.BoxGeometry(kw * 0.55, kw * 0.5, keyDepth * 0.6), blackMat, [x - kw / 2, keyY + kw * 0.12, keyZ + keyDepth * 0.7], { outline: 0 });
    }
  }
  for (const k of keys) k.userData.y = k.position.y;
  // the key bed under them, cheek blocks at both ends, and the fallboard behind
  add(group, new THREE.BoxGeometry(W + kw * 2, kw * 0.9, keyDepth + 0.01), toon(CASE_SHADE), [0, keyY - kw * 0.95, keyZ + keyDepth / 2]);
  for (const sign of [1, -1]) add(group, new THREE.BoxGeometry(kw, kw * 1.8, keyDepth + 0.01), toon(CASE), [sign * (W / 2 + kw / 2), keyY - kw * 0.35, keyZ + keyDepth / 2]);
  add(group, new THREE.BoxGeometry(W + kw * 2, kw * 1.6, kw * 0.6), toon(CASE), [0, keyY + kw * 0.3, keyZ + keyDepth + kw * 0.3]);

  // ── the case: a grand piano's outline (straight on the bass side, curving in on the treble side), seen from
  // above, as a thick slab behind the keys; the lid on top, propped open on the treble side ──
  const back = keyZ + keyDepth + kw * 0.6, length = W * 0.7, half = W / 2 + kw;
  const outline = new THREE.Shape();
  outline.moveTo(half, 0);                                     // bass corner (her left), at the keys
  outline.lineTo(half, length);                                // the straight bass side, away from her
  outline.quadraticCurveTo(half * 0.2, length * 1.08, -half * 0.25, length * 0.72);   // the tail
  outline.quadraticCurveTo(-half * 0.75, length * 0.4, -half, length * 0.3);         // the treble side curves in
  outline.lineTo(-half, 0);
  outline.lineTo(half, 0);
  const slab = kw * 3.2;
  const body = new THREE.ExtrudeGeometry(outline, { depth: slab, bevelEnabled: true, bevelThickness: kw * 0.3, bevelSize: kw * 0.3, bevelSegments: 2 });
  // the shape is drawn in x/y; lying flat, y becomes the distance away from her (+z) and the slab goes down
  const caseTop = keyY + kw * 0.5;                            // only a little above the keys: from your side it hid her hands
  add(group, body, toon(CASE), [0, caseTop, back], { rot: [Math.PI / 2, 0, 0], outline: 0.012 });
  add(group, new THREE.BoxGeometry(W + kw * 2.4, kw * 0.5, kw * 0.6), toon(TRIM), [0, caseTop - slab - kw * 0.2, back + kw * 0.2], { outline: 0 });
  // the lid, closed (opened, its edge ran across her as you see her), and a music stand with a sheet of music on it
  const lid = new THREE.ExtrudeGeometry(outline, { depth: kw * 0.3, bevelEnabled: false });
  add(group, lid, toon(CASE), [0, caseTop + kw * 0.62, back], { rot: [Math.PI / 2, 0, 0], outline: 0.01 });
  const stand = new THREE.Group();
  stand.position.set(0, caseTop + kw * 0.6, back + kw * 0.4);
  stand.rotation.x = -0.3;                                     // leaning back, toward her eyes
  group.add(stand);
  const desk = { w: W * 0.5, h: kw * 4.2 };
  // an open frame (a solid board, seen from behind, looked like a laptop): a ledge, a top rail and two posts, with
  // the sheets showing through, their staves seen from both sides
  add(stand, new THREE.BoxGeometry(desk.w, kw * 0.5, kw * 0.9), toon(CASE), [0, kw * 0.25, -kw * 0.45]);
  add(stand, new THREE.BoxGeometry(desk.w, kw * 0.3, kw * 0.3), toon(CASE), [0, desk.h, 0]);
  for (const sx of [-1, 1]) add(stand, new THREE.BoxGeometry(kw * 0.3, desk.h, kw * 0.3), toon(CASE), [sx * desk.w / 2, desk.h / 2, 0]);
  const sheet = new THREE.MeshBasicMaterial({ color: 0xfffdf6, side: THREE.DoubleSide }),
        ink = new THREE.MeshBasicMaterial({ color: 0x8c84a8, side: THREE.DoubleSide });
  for (const sx of [-1, 1]) {                                  // two pages, each with a few staves
    add(stand, new THREE.PlaneGeometry(desk.w * 0.44, desk.h * 0.8), sheet, [sx * desk.w * 0.23, desk.h * 0.55, 0], { outline: 0 });
    for (let r = 0; r < 4; r++) {
      for (const z of [-kw * 0.04, kw * 0.04]) {
        add(stand, new THREE.PlaneGeometry(desk.w * 0.36, kw * 0.07), ink, [sx * desk.w * 0.23, desk.h * (0.3 + 0.15 * r), z], { outline: 0 });
      }
    }
  }

  // ── three legs with castors, and the pedals ──
  for (const [x, z] of [[half * 0.85, back + kw], [-half * 0.85, back + kw], [half * 0.4, back + length * 0.92]]) {
    const h = caseTop - slab;
    add(group, new THREE.CylinderGeometry(kw * 0.55, kw * 0.4, h, 10), toon(CASE), [x, h / 2, z]);
    add(group, new THREE.SphereGeometry(kw * 0.5, 10, 8), toon(TRIM), [x, kw * 0.4, z], { outline: 0 });
  }
  add(group, new THREE.BoxGeometry(kw * 0.6, keyY * 0.75, kw * 0.6), toon(CASE), [0, keyY * 0.375, back + kw * 0.5]);
  for (const x of [-kw * 1.2, 0, kw * 1.2]) add(group, new THREE.BoxGeometry(kw * 0.5, kw * 0.2, kw * 1.4), toon(0xe2b65c), [x, kw * 0.25, back - kw * 0.3], { outline: 0 });

  // ── her bench: a cushioned top on four legs ──
  const bench = { w: W * 0.62, d: W * 0.3 };
  add(group, new THREE.BoxGeometry(bench.w, kw * 1.1, bench.d), toon(TRIM), [0, benchY - kw * 0.55, benchZ]);
  add(group, new THREE.BoxGeometry(bench.w * 1.02, kw * 0.6, bench.d * 1.02), toon(WOOD), [0, benchY - kw * 1.35, benchZ]);
  for (const sx of [1, -1]) for (const sz of [1, -1]) {
    add(group, new THREE.CylinderGeometry(kw * 0.25, kw * 0.2, benchY - kw * 1.5, 6), toon(WOOD),
        [sx * bench.w * 0.42, (benchY - kw * 1.5) / 2, benchZ + sz * bench.d * 0.38], { outline: 0.05 });
  }

  return {
    group, keys, kw,
    /** The point on the keyboard for a hand at x (-1 low … 1 high), in the piano's frame: on the key, a little in
     *  from its front edge, lifted by `up`. */
    keyPoint(x, up, out) { return out.set(-x * W / 2, keyY + up, keyZ + keyDepth * 0.35); },
    /** Put every key back up, then press the ones under her hands: [[index, depth 0…1], …]. */
    press(pressed) {
      for (const k of keys) k.position.y = k.userData.y;
      for (const [i, d] of pressed) if (keys[i]) keys[i].position.y = keys[i].userData.y - kw * 0.35 * d;
    },
  };
}

// ── two-bone IK: her arm reaches a point, the elbow toward a pole ──

/** Turn `node` (a joint) by the world-space rotation `q`, blended in by `w`: its local rotation is worked out from
 *  its parent's. */
function turnWorld(THREE, node, q, w, tmp) {
  const parentQ = node.parent.getWorldQuaternion(tmp.q1);
  const worldQ = node.getWorldQuaternion(tmp.q2);
  const wanted = tmp.q3.copy(q).multiply(worldQ);
  const local = parentQ.invert().multiply(wanted);
  node.quaternion.slerp(local, w);
  node.updateMatrixWorld(true);
}

export function makeIK(THREE) {
  const v = () => new THREE.Vector3();
  const tmp = { q1: new THREE.Quaternion(), q2: new THREE.Quaternion(), q3: new THREE.Quaternion() };
  const S = v(), E = v(), Wr = v(), dir = v(), poleDir = v(), elbow = v(), a1 = v(), a2 = v(), tip = v();
  const turn = new THREE.Quaternion();
  return {
    /** Put `side`'s wrist at `target` (world), the elbow bending toward `pole`, weight `w` (0 = leave the arm as
     *  it is). With `point` and a rig that knows its fingers, the hand is turned so its fingers point that way. */
    reach(rig, side, target, pole, w, point = null, weights = null, pointTarget = null) {
      if (w <= 0.001) return;
      const upper = rig.node(`${side}UpperArm`), lower = rig.node(`${side}LowerArm`);
      if (!upper || !lower) return;
      const original = weights && [upper, lower, rig.node(`${side}Hand`)].map(bone => bone?.quaternion.clone());
      const strength = w;
      if (weights) w = 1;
      rig.root.updateMatrixWorld(true);
      upper.getWorldPosition(S);
      lower.getWorldPosition(E);
      rig.wrist(side, Wr);
      const a = S.distanceTo(E), b = E.distanceTo(Wr);
      const d = Math.max(Math.abs(a - b) + 1e-3, Math.min(a + b - 1e-3, S.distanceTo(target)));
      dir.subVectors(target, S).normalize();
      poleDir.subVectors(pole, S);
      poleDir.addScaledVector(dir, -poleDir.dot(dir)).normalize();
      const along = (a * a - b * b + d * d) / (2 * d), out = Math.sqrt(Math.max(0, a * a - along * along));
      elbow.copy(S).addScaledVector(dir, along).addScaledVector(poleDir, out);
      // the upper arm swings from where its elbow is to where it should be
      turn.setFromUnitVectors(a1.subVectors(E, S).normalize(), a2.subVectors(elbow, S).normalize());
      turnWorld(THREE, upper, turn, w, tmp);
      // then the forearm, from where its wrist is now to the target
      lower.getWorldPosition(E);
      rig.wrist(side, Wr);
      turn.setFromUnitVectors(a1.subVectors(Wr, E).normalize(), a2.subVectors(target, E).normalize());
      turnWorld(THREE, lower, turn, w, tmp);
      // and the hand, its fingers pointing along `point` (to the keys and a little down)
      const hand = rig.node(`${side}Hand`);
      if (point && hand && rig.fingerTip && rig.fingerTip(side, tip)) {
        rig.wrist(side, Wr);
        // A moving wrist changes the direction to a fixed pointer; measure again after the arm reaches.
        if (pointTarget) {
          point.copy(pointTarget).sub(Wr);
          if (point.lengthSq() < 1e-12) point.set(0, 0, 1);
          else point.normalize();
        }
        turn.setFromUnitVectors(a1.subVectors(tip, Wr).normalize(), point);
        turnWorld(THREE, hand, turn, w, tmp);
      }
      if (weights) {
        [upper, lower, hand].forEach((bone, i) => {
          if (!bone) return;
          const solved = bone.quaternion.clone();
          bone.quaternion.copy(original[i]).slerp(solved, strength * weights[['UpperArm', 'LowerArm', 'Hand'][i]]);
        });
        rig.root.updateMatrixWorld(true);
      }
    },
  };
}

// ── little notes that float up as she plays ──

export function makeNotes(THREE, scene, count = 8) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const g = canvas.getContext('2d');
  g.font = 'bold 50px "Noto Sans Symbols", "DejaVu Sans", sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.lineWidth = 6;
  g.strokeStyle = '#1a1426';
  g.strokeText('♪', 32, 34);
  g.fillStyle = '#b9a3ff';
  g.fillText('♪', 32, 34);
  const texture = new THREE.CanvasTexture(canvas);
  const pool = Array.from({ length: count }, () => {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
    s.visible = false;
    s.userData = { age: 9, life: 1.8, drift: 0 };
    scene.add(s);
    return s;
  });
  return {
    /** A note rises from `at` (world). */
    spawn(at, size) {
      const s = pool.find(p => p.userData.age >= p.userData.life);
      if (!s) return;
      s.position.copy(at);
      s.userData = { age: 0, life: 1.6 + Math.random() * 0.6, drift: (Math.random() - 0.5) * 0.12, size, from: at.clone() };
      // sized and see-through from the start: drawn once at a sprite's own size (1 unit), it filled the picture
      s.scale.setScalar(size * 0.6);
      s.material.opacity = 0;
      s.visible = true;
    },
    update(dt) {
      for (const s of pool) {
        const u = s.userData;
        if (u.age >= u.life) { s.visible = false; continue; }
        u.age += dt;
        const k = u.age / u.life;
        s.position.set(u.from.x + u.drift * k + 0.015 * Math.sin(u.age * 5), u.from.y + 0.22 * k, u.from.z);
        s.material.opacity = Math.min(1, u.age / 0.15) * (1 - k * k);
        s.scale.setScalar(u.size * (0.6 + 0.4 * Math.min(1, u.age / 0.2)));
      }
    },
    hide() { for (const s of pool) { s.visible = false; s.userData.age = 9; } },
  };
}
