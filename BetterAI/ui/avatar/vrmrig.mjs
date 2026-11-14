// A VRM file (for example an avatar exported from VRoid Studio) behind the same few methods the built-in figure
// has (figure.mjs), so avatar.js doesn't care which one she is. Used only when ARIA_AVATAR names a file.
// Tried on VRoid's "AvatarSample_B" (a VRM 0.x file) on 2026-11-13. If loading throws, avatar.js keeps the built-in figure.
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';

const HEIGHT = 0.95;        // the built-in figure's height: the camera and the ring are set up for it

export async function loadVrm(THREE, url) {
  const loader = new GLTFLoader();
  loader.register(parser => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error('not a VRM file');
  VRMUtils.rotateVRM0(vrm);                         // older VRM files face the other way
  // ...and after being turned round, their bones nod and tilt the other way too (turning left and right is the same)
  const flip = vrm.meta?.metaVersion === '0' ? -1 : 1;

  const root = new THREE.Group();
  root.add(vrm.scene);
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const scale = HEIGHT / Math.max(0.01, box.max.y - box.min.y);
  vrm.scene.scale.setScalar(scale);
  vrm.scene.position.y = -box.min.y * scale;
  // three-vrm's spring bones work in world units: collider and hair radii, and the pull of stiffness and gravity,
  // are not scaled with the model. Shrunk to fit, every collider was too big for her (1.65x for the first model)
  // and pushed her hair out from her head and back, so it stuck out stiffly instead of hanging and swinging.
  const springs = vrm.springBoneManager;
  if (springs) {
    const shapes = new Set([...(springs.colliders ?? [])].map(c => c.shape).filter(sh => sh && 'radius' in sh));
    for (const shape of shapes) shape.radius *= scale;          // once each, even if colliders share a shape
    for (const j of springs.joints ?? []) {
      j.settings.hitRadius *= scale;
      j.settings.stiffness *= scale;
      j.settings.gravityPower *= scale;
    }
  }

  // relaxed hands: a model's fingers come dead straight, which is most of what makes arms look stiff
  for (const [side, sign] of [['left', -1], ['right', 1]]) {
    for (const finger of ['Index', 'Middle', 'Ring', 'Little']) {
      for (const [joint, curl] of [['Proximal', 0.3], ['Intermediate', 0.45], ['Distal', 0.3]]) {
        vrm.humanoid?.getNormalizedBoneNode(`${side}${finger}${joint}`)?.rotation.set(0, 0, flip * sign * curl);
      }
    }
    vrm.humanoid?.getNormalizedBoneNode(`${side}ThumbProximal`)?.rotation.set(0, sign * -0.3, 0);
  }

  const lock = hairLock(THREE, vrm);

  const eyesOn = new THREE.Object3D();
  root.add(eyesOn);
  if (vrm.lookAt) vrm.lookAt.target = eyesOn;
  const express = (name, w) => { try { vrm.expressionManager?.setValue(name, w); } catch { /* this model lacks it */ } };
  const euler = new THREE.Euler(), turn = new THREE.Quaternion(), aim = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0);
  const last = new Map();                           // where each joint was last frame (for the follow filter)
  const has = name => !!vrm.expressionManager?.getExpression(name);
  const vowels = ['aa', 'ih', 'ou', 'ee', 'oh'].filter(has);

  return {
    root,
    canSit: true,                                     // sitting is fitted to a full-size body's legs (logic.mjs LEG)
    /** Put a bone at `angles`; with `toward` and `weight`, that far along the short way round to `toward`. */
    setBone(name, angles, toward, weight = 0, follow = 1) {
      const bone = vrm.humanoid?.getNormalizedBoneNode(name);
      if (!bone) return;                              // this model has no such bone: that movement is skipped
      const set = (q, [x, y, z, twist = 0]) => {
        q.setFromEuler(euler.set(flip * x, y, flip * z));
        if (twist) q.multiply(turn.setFromAxisAngle(X, flip * twist));
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
    setBlink(w) { express('blink', w); },
    setMouth(w) { express('aa', w); },
    /** The vowel shapes this model has; with none of them, "aa" alone opens her mouth. */
    setVisemes(v) {
      if (vowels.length < 2) return express('aa', Math.max(...Object.values(v)));
      for (const name of vowels) express(name, v[name] || 0);
    },
    /** Where a bone really is in the scene, [x, y, z] (her right is -x, up is +y, toward the viewer is +z). */
    where(name) {
      const node = vrm.humanoid?.getRawBoneNode(name);
      return node ? node.getWorldPosition(new THREE.Vector3()).toArray().map(n => +n.toFixed(3)) : null;
    },
    /** After she was hidden, or first shown: let hair and clothes hang from where she is now. A spring-bone reset
     *  puts hair back in the shape it was modelled in (for her, partly sticking out), and seen live it then drops and
     *  wobbles into place: that was the shiver every time she appeared. So the fall happens here, unseen: a second
     *  of small steps with her body held still. */
    reset() {
      last.clear();                                   // joints go straight to where she is told, no catching up
      const springs = vrm.springBoneManager;
      if (!springs) return;
      vrm.humanoid?.update();
      root.updateMatrixWorld(true);
      springs.reset();
      for (let i = 0; i < 60; i++) springs.update(1 / 60);
    },
    /** Her hair tucked behind her right ear, `w` of the way (0…1). */
    tuckHair(w) { lock?.(w); },
    setExpression(name, w) { express(name, w); },
    look(x, y) { eyesOn.position.set(x * 1.5, HEIGHT * 0.85 + y * 1.0, 3); },
    update(dt) { vrm.update(Math.min(dt, 1 / 20)); },   // steady small steps: a long one makes hair and skirt explode
  };
}

/** The lock of hair hanging in front of her right ear, as a function that tucks it behind her ear `w` of the way
 *  (0…1); null when the model has no such lock. A hand passing by doesn't move spring-bone hair, so the tuck moves
 *  where the lock *rests*: its rest pose turns back and out round her ear, and the hair physics carries it there
 *  (and back), with its own swing and lag. */
function hairLock(THREE, vrm) {
  const springs = vrm.springBoneManager, head = vrm.humanoid?.getRawBoneNode('head');
  if (!springs || !head) return null;
  vrm.scene.updateMatrixWorld(true);
  const at = head.getWorldPosition(new THREE.Vector3());
  // a chain hanging straight from her head, to her right (-x: she faces +z) and not behind it, nearest her ear
  const near = [...springs.joints].filter(j => j.bone.parent === head)
    .map(j => [j, j.bone.getWorldPosition(new THREE.Vector3()).sub(at)])
    .filter(([, p]) => p.x < -0.02 && p.z > -0.02 && p.x > -0.12)
    .sort((a, b) => Math.hypot(a[1].x + 0.06, a[1].z) - Math.hypot(b[1].x + 0.06, b[1].z));
  if (!near.length) return null;
  const joint = near[0][0];
  const rest = joint._initialLocalRotation?.clone(), local = joint._initialLocalMatrix;
  if (!rest || !local) return null;
  const position = new THREE.Vector3(), scale = new THREE.Vector3();
  local.decompose(position, new THREE.Quaternion(), scale);
  // tucked: swung back past her ear and a little out from her head (turned about the world's axes, worked out in
  // her head's own frame)
  const headTurn = head.getWorldQuaternion(new THREE.Quaternion());
  const swing = new THREE.Quaternion().setFromEuler(new THREE.Euler(TUCK_BACK, 0, -TUCK_OUT, 'ZYX'));
  const toHead = headTurn.clone().invert();
  const none = new THREE.Quaternion(), part = new THREE.Quaternion(), turned = new THREE.Quaternion();
  let was = 0;
  return w => {
    w = Math.max(0, Math.min(1, w));
    if (Math.abs(w - was) < 1e-4) return;
    was = w;
    part.slerpQuaternions(none, swing, w);
    turned.copy(toHead).multiply(part).multiply(headTurn).multiply(rest);
    joint._initialLocalRotation.copy(turned);
    local.compose(position, turned, scale);
  };
}
const TUCK_BACK = 1.25, TUCK_OUT = 0.35;    // radians
