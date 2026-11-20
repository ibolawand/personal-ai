// Her motion clips: real animation under the movement logic.mjs decides. A clip has the weight shifts, overlap and
// follow-through that summed sine waves don't. Two kinds of file (motions/README.md):
// - Quaternius' Universal Animation Library (clips.glb, CC0): sitting; an Unreal-style mannequin;
// - Mixamo clips (*.fbx, one clip each, downloaded by Lala "in place" and "without skin"): her walk; Mixamo's
//   rig. (Standing stays her own coded motion: the idle clips tried looked worse.)
// Each clip is retargeted to her VRM's bones here, once, when it loads: every frame as a rotation of each of her
// (normalised) bones, measured from the clip's own T-pose, turned to face the way she faces. vrmrig.mjs plays them
// (setMotion) and avatar.js says which and how much.

/** Her bone ← each rig's bone. (The mannequin's spine_02 and Mixamo's Spine1 are left out: her chest takes both.) */
export const RIGS = {
  ual: {
    hips: 'pelvis', spine: 'spine_01', chest: 'spine_03', neck: 'neck_01', head: 'Head',
    leftShoulder: 'clavicle_l', leftUpperArm: 'upperarm_l', leftLowerArm: 'lowerarm_l', leftHand: 'hand_l',
    rightShoulder: 'clavicle_r', rightUpperArm: 'upperarm_r', rightLowerArm: 'lowerarm_r', rightHand: 'hand_r',
    leftUpperLeg: 'thigh_l', leftLowerLeg: 'calf_l', leftFoot: 'foot_l',
    rightUpperLeg: 'thigh_r', rightLowerLeg: 'calf_r', rightFoot: 'foot_r',
    toes: 'ball_l',
  },
  mixamo: {
    hips: 'Hips', spine: 'Spine', chest: 'Spine2', neck: 'Neck', head: 'Head',
    leftShoulder: 'LeftShoulder', leftUpperArm: 'LeftArm', leftLowerArm: 'LeftForeArm', leftHand: 'LeftHand',
    rightShoulder: 'RightShoulder', rightUpperArm: 'RightArm', rightLowerArm: 'RightForeArm', rightHand: 'RightHand',
    leftUpperLeg: 'LeftUpLeg', leftLowerLeg: 'LeftLeg', leftFoot: 'LeftFoot',
    rightUpperLeg: 'RightUpLeg', rightLowerLeg: 'RightLeg', rightFoot: 'RightFoot',
    toes: 'LeftToeBase',
  },
};
/** Each of her bones' parent among these (a bone between them, like upperChest, is left at rest: no turn). */
export const PARENT = {
  spine: 'hips', chest: 'spine', neck: 'chest', head: 'neck',
  leftShoulder: 'chest', leftUpperArm: 'leftShoulder', leftLowerArm: 'leftUpperArm', leftHand: 'leftLowerArm',
  rightShoulder: 'chest', rightUpperArm: 'rightShoulder', rightLowerArm: 'rightUpperArm', rightHand: 'rightLowerArm',
  leftUpperLeg: 'hips', leftLowerLeg: 'leftUpperLeg', leftFoot: 'leftLowerLeg',
  rightUpperLeg: 'hips', rightLowerLeg: 'rightUpperLeg', rightFoot: 'rightLowerLeg',
};
/** Her bones a clip can move (the rigs' `toes` only tells which way the clip faces). */
export const MOVED = Object.keys(PARENT).concat('hips');
/** The files and what she plays from each, by what it's for: the clip's name in the file (a Mixamo file has one). */
export const SOURCES = [
  { file: 'clips.glb', rig: 'ual', clips: { sit: 'Sitting_Idle_Loop', sitTalk: 'Sitting_Talking_Loop' } },
  { file: 'walk.fbx', rig: 'mixamo', clips: { walk: 0 } },
  { file: 'catwalk.fbx', rig: 'mixamo', clips: { catwalk: 0 } },
];

/** Which of her bones a clip moves, and how much (0…1; `hips` also moves her hips' position). Walking (`full`): all of it (a shorter stride would slide her feet). Sitting (on a window's edge or the
 *  floor): only her body above the hips; her legs keep the pose fitted to the seat and their swing. */
const LEGS = ['leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot'];
const UPPER = ['spine', 'chest', 'neck', 'head', 'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm',
               'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand'];
const only = (names, w = 1) => Object.fromEntries(names.map(n => [n, w]));
export const MASKS = {
  full: { hips: 1, ...only(UPPER), ...only(LEGS) },
  sit: only(UPPER),
};
const BAKE_FPS = 30;


/** Where in a looping clip of `frames` frames time `t` falls: [frame, next frame, how far between them]. */
export function frameAt(t, frames, fps = BAKE_FPS) {
  const f = (((t * fps) % frames) + frames) % frames, i = Math.floor(f);
  return [i, (i + 1) % frames, f - i];
}

/** Her walk's phase (logic.mjs walkCycle: her left leg furthest forward at π/2) → the time in a walk clip whose left
 *  leg is furthest forward at `lead` seconds and which takes `cycles` strides of both legs. */
export function walkTime(phase, { duration, lead, cycles = 1 }) {
  const turn = (phase - Math.PI / 2) / (2 * Math.PI);
  return lead + (((turn % 1) + 1) % 1) * duration / cycles;
}

/** A node of `root` by a rig's bone name (FBX files call Mixamo's "mixamorig:Hips"; three.js drops the colon). */
function findBone(root, name) {
  return root.getObjectByName(name) || root.getObjectByName('mixamorig' + name) || root.getObjectByName('mixamorig:' + name);
}

/** Retargets the clips of one loaded file (`scene`, `animations`) of rig `rig` onto her bones into `baked`. */
function bake(THREE, { scene, animations }, source, { forward, hipsHeight }, baked) {
  const map = RIGS[source.rig], mixer = new THREE.AnimationMixer(scene), node = {};
  for (const mine of MOVED) {
    node[mine] = findBone(scene, map[mine]);
    if (!node[mine]) throw new Error(`${source.file} has no ${map[mine]}`);
  }
  const poseAt = (clip, time) => {
    mixer.stopAllAction();
    mixer.clipAction(clip).reset().play();
    mixer.setTime(time);
    scene.updateMatrixWorld(true);
  };
  const clipOf = name => typeof name === 'number' ? animations[name] : animations.find(a => a.name === name);
  const v = new THREE.Vector3(), w = new THREE.Vector3();
  // the T-pose. Mixamo files are in one as loaded. The mannequin's bind pose is an A-pose: its A_TPose clip, at the
  // moment the arms are most level.
  scene.updateMatrixWorld(true);
  const tpose = source.rig === 'ual' ? clipOf('A_TPose') : null;
  if (source.rig === 'ual') {
    if (!tpose) throw new Error('the clips have no T-pose');
    const armLevel = () => {
      node.leftUpperArm.getWorldPosition(v);
      return Math.abs(node.leftLowerArm.getWorldPosition(w).sub(v).normalize().y);
    };
    let best = [Infinity, 0];
    for (let i = 0; i <= 20; i++) {
      const time = tpose.duration * i / 20;
      poseAt(tpose, time);
      const level = armLevel();
      if (level < best[0]) best = [level, time];
    }
    poseAt(tpose, best[1]);
  }
  const restInv = {}, restHips = new THREE.Vector3();
  for (const n of MOVED) restInv[n] = node[n].getWorldQuaternion(new THREE.Quaternion()).invert();
  node.hips.getWorldPosition(restHips);
  // which way the clip's body faces: its toes point forward
  const toesNode = findBone(scene, map.toes);
  const toes = toesNode ? toesNode.getWorldPosition(new THREE.Vector3()).sub(node.leftFoot.getWorldPosition(v)) : new THREE.Vector3(0, 0, 1);
  const theirYaw = Math.atan2(toes.x, toes.z), myYaw = forward > 0 ? 0 : Math.PI;
  const turn = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), myYaw - theirYaw);
  const turnInv = turn.clone().invert();
  const scale = hipsHeight / Math.max(1e-6, restHips.y);       // (both kinds of file stand on y = 0)

  const world = {}, q = new THREE.Quaternion();
  for (const [key, name] of Object.entries(source.clips)) {
    const clip = clipOf(name);
    if (!clip) continue;
    const frames = Math.max(2, Math.round(clip.duration * BAKE_FPS));
    const bones = Object.fromEntries(MOVED.map(n => [n, new Float32Array(frames * 4)]));
    const hips = new Float32Array(frames * 3), ahead = new Float32Array(frames);
    for (let f = 0; f < frames; f++) {
      poseAt(clip, f / BAKE_FPS);
      for (const n of MOVED) {                      // how it has turned from the T-pose, in her frame
        node[n].getWorldQuaternion(q).multiply(restInv[n]);
        world[n] = turn.clone().multiply(q).multiply(turnInv);
      }
      for (const n of MOVED) (PARENT[n] ? world[PARENT[n]].clone().invert().multiply(world[n]) : world[n]).toArray(bones[n], f * 4);
      node.hips.getWorldPosition(v).sub(restHips).applyQuaternion(turn).multiplyScalar(scale).toArray(hips, f * 3);
      // how far her left foot is ahead of her right, along the way she faces (to fit a walk to her steps)
      node.leftFoot.getWorldPosition(v).sub(node.rightFoot.getWorldPosition(w)).applyQuaternion(turn);
      ahead[f] = v.z * forward;
    }
    // when its left leg is furthest forward, and how many strides it holds (times the left leg leads)
    let lead = 0, cycles = 0;
    for (let f = 0; f < frames; f++) {
      if (ahead[f] > ahead[lead]) lead = f;
      if (ahead[f] > 0 && ahead[f] >= ahead[(f + frames - 1) % frames] && ahead[f] > ahead[(f + 1) % frames]) cycles++;
    }
    baked[key] = { frames, bones, hips, duration: frames / BAKE_FPS, lead: lead / BAKE_FPS, cycles: Math.max(1, cycles) };
  }
  mixer.stopAllAction();
}

/** Loads her clips (SOURCES, from the folder `base`) for a VRM. `forward`: which way the VRM's own (normalised) bones
 *  face, +1 for +z, -1 for -z; `hipsHeight`: her hips' height in those units. A file that is missing or fails is
 *  skipped (it says which in `problems`). Returns { has, timing, sample, problems }. */
export async function loadMotions(THREE, base, opts) {
  // (loaded here, not at the top: the page's import map finds them, and node's tests import this file without it)
  const loaders = {
    glb: async () => new (await import('three/addons/loaders/GLTFLoader.js')).GLTFLoader(),
    fbx: async () => new (await import('three/addons/loaders/FBXLoader.js')).FBXLoader(),
  };
  const baked = {}, problems = [];
  for (const source of SOURCES) {
    try {
      const loader = await loaders[source.file.split('.').pop()]();
      const got = await loader.loadAsync(new URL(source.file, base).href);
      bake(THREE, got.scene ? got : { scene: got, animations: got.animations }, source, opts, baked);
    } catch (e) {
      problems.push(`${source.file}: ${e?.message || e}`);
    }
  }
  if (!Object.keys(baked).length) throw new Error(problems.join('; ') || 'no clips');
  const a = new THREE.Quaternion(), b = new THREE.Quaternion(), v = new THREE.Vector3();
  return {
    problems,
    has: key => !!baked[key],
    /** { duration, lead, cycles } of a clip (see walkTime), or null. */
    timing: key => baked[key] ? { duration: baked[key].duration, lead: baked[key].lead, cycles: baked[key].cycles } : null,
    /** The pose of clip `key` at time `t` (it loops) into out = { bones: {name: Quaternion}, hips: Vector3 }. */
    sample(key, t, out) {
      const c = baked[key];
      if (!c) return out;
      const [i, j, k] = frameAt(t, c.frames);
      for (const n in c.bones) {
        a.fromArray(c.bones[n], i * 4);
        b.fromArray(c.bones[n], j * 4);
        (out.bones[n] ||= new THREE.Quaternion()).copy(a).slerp(b, k);
      }
      out.hips.fromArray(c.hips, i * 3).lerp(v.fromArray(c.hips, j * 3), k);
      return out;
    },
  };
}
