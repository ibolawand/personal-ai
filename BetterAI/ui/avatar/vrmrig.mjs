// A VRM file (for example an avatar exported from VRoid Studio) behind the same few methods the built-in figure
// has (figure.mjs), so avatar.js doesn't care which one she is. Used only when ARIA_AVATAR names a file.
// Tried on VRoid's "AvatarSample_B" (a VRM 0.x file) on 2026-11-13. If loading throws, avatar.js keeps the built-in figure.
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { followJoint } from './logic.mjs';
import { CHARACTER_MOODS, vrmCharacterExpressions } from './presence.mjs';
import { loadMotions, MASKS, walkTime } from './motions.mjs';

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

  polishShading(THREE, vrm.scene);
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

  // Her hair hangs. The file gives hair no weight at all, only stiffness: every strand holds the shape it was
  // modelled in, relative to her head. With her head tipped or turned, hair down to her hips then stood out from
  // her body at that angle and stayed there. So the further down a strand a joint is, the more it weighs and the
  // less it holds its shape: the roots keep her hairstyle, the lengths hang and swing.
  const hair = [];                                    // [joint, how far down its strand 0…1, its phase in the breeze]
  if (springs) {
    const jointOf = new Map([...(springs.joints ?? [])].map(j => [j.bone, j]));
    for (const j of jointOf.values()) {
      if (!/hair/i.test(j.bone.name)) continue;
      let depth = 0;
      for (let b = j.bone.parent; b && jointOf.has(b); b = b.parent) depth++;
      const down = Math.min(1, depth / 3), stiff = j.settings.stiffness;
      j.settings.stiffness = stiff * (1 - 0.7 * down);
      j.settings.gravityPower += stiff * 1.2 * down;
      hair.push([j, down, hair.length * 2.399]);
    }
  }
  /** A breath of air on her hair, [x, z] (small, logic.mjs breeze): it pulls the way hair hangs a little to the
   *  side, each strand a moment apart, so her hair is never frozen while she stands still. */
  const setBreeze = ([x, z]) => {
    for (const [j, down, phase] of hair) {
      const k = down * (0.75 + 0.25 * Math.sin(phase));
      j.settings.gravityDir.set(x * k, -1, z * k).normalize();
    }
  };

  // her hands: a model's fingers come dead straight, which is most of what makes arms look stiff. Each finger
  // curls (about z), fans out from the middle of the hand (about y) and the thumb comes in across the palm.
  const FINGERS = ['Index', 'Middle', 'Ring', 'Little'], JOINTS = [['Proximal', 0.3], ['Intermediate', 0.45], ['Distal', 0.3]];
  const FAN = [1, 0.3, -0.4, -1].map(f => f * 0.2);    // radians at spread 1; the index goes toward the thumb
  const bone = name => vrm.humanoid?.getNormalizedBoneNode(name);
  const fingerBones = {}, thumbBones = {};            // looked up once: they are set every frame
  for (const side of ['left', 'right']) {
    fingerBones[side] = FINGERS.map(finger => JOINTS.map(([joint]) => bone(`${side}${finger}${joint}`)));
    // (VRM 1 calls the thumb's three bones Metacarpal, Proximal, Distal; VRM 0 Proximal, Intermediate, Distal)
    thumbBones[side] = [bone(`${side}ThumbMetacarpal`) || bone(`${side}ThumbProximal`),
                        bone(`${side}ThumbMetacarpal`) ? bone(`${side}ThumbProximal`) : bone(`${side}ThumbIntermediate`),
                        bone(`${side}ThumbDistal`)];
  }
  /** Shape her hands: { left, right }, each { curl: [index, middle, ring, little] (a share of the relaxed curl: 0
   *  straight, 1 hanging relaxed, about 3 a fist), spread (0 fingers together … 1 fanned out), thumb (0 held out
   *  … 1 relaxed … 2 folded across the palm) }. See logic.mjs HANDS. */
  const setFingers = hands => {
    for (const [side, sign] of [['left', -1], ['right', 1]]) {
      const h = hands?.[side], spread = h?.spread ?? 0, thumb = h?.thumb ?? 1;
      fingerBones[side].forEach((joints, f) => joints.forEach((b, j) =>
        b?.rotation.set(0, j ? 0 : sign * FAN[f] * spread, flip * sign * JOINTS[j][1] * (h?.curl?.[f] ?? 1))));
      const [base, mid, tip] = thumbBones[side], fold = Math.max(0, thumb - 1);
      base?.rotation.set(0, sign * (-0.3 * Math.min(1, thumb) - 0.35 * fold), 0);
      mid?.rotation.set(0, sign * -0.55 * fold, 0);
      tip?.rotation.set(0, sign * -0.6 * fold, 0);
    }
  };
  setFingers(null);

  const eyesOn = new THREE.Object3D();
  root.add(eyesOn);
  if (vrm.lookAt) vrm.lookAt.target = eyesOn;
  const express = (name, w) => { try { vrm.expressionManager?.setValue(name, w); } catch { /* this model lacks it */ } };
  const euler = new THREE.Euler(), turn = new THREE.Quaternion(), aim = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0);
  const last = new Map();                           // where each joint was last frame, and how fast it turned
  const has = name => !!vrm.expressionManager?.getExpression(name);
  const vowels = ['aa', 'ih', 'ou', 'ee', 'oh'].filter(has);
  const faceNames = ['happy', 'relaxed', 'surprised', 'angry', 'sad', ...CHARACTER_MOODS];
  const faceAvailable = faceNames.flatMap(name => [name, name[0].toUpperCase() + name.slice(1)]).filter(has);
  const faceValues = {};

  // her motion clips (motions.mjs): loaded after she is shown; until then (or if they fail) she moves as before
  const hipsNode = bone('hips'), hipsRest = hipsNode ? hipsNode.position.clone() : null;
  let clips = null;
  // this frame's clip pose: per bone its rotation and how much of it shows (boneW), and her hips' offset (hipsW)
  const clipNow = { boneW: {}, bones: {}, hips: new THREE.Vector3(), hipsW: 0 };
  const clipB = { bones: {}, hips: new THREE.Vector3() };
  if (hipsNode) {
    loadMotions(THREE, new URL('./motions/', import.meta.url).href,
                { forward: flip < 0 ? -1 : 1, hipsHeight: (hipsNode.getWorldPosition(new THREE.Vector3()).y - vrm.scene.position.y) / scale })
      .then(m => { clips = m; window.ariaClips = m.problems.length ? 'loaded; skipped ' + m.problems.join('; ') : 'loaded'; })
      .catch(e => { window.ariaClips = 'failed: ' + (e?.message || e); });
  }
  const baseQ = new THREE.Quaternion(), layered = new THREE.Quaternion();

  return {
    root,
    canSit: true,                                     // sitting is fitted to a full-size body's legs (logic.mjs LEG)
    /** Put a bone at `angles`; with `toward` and `weight`, that far along the short way round to `toward`. */
    setBone(name, angles, toward, weight = 0, follow = 1, dt = 0, base = null) {
      const bone = vrm.humanoid?.getNormalizedBoneNode(name);
      if (!bone) return;                              // this model has no such bone: that movement is skipped
      const set = (q, [x, y, z, twist = 0]) => {
        q.setFromEuler(euler.set(flip * x, y, flip * z));
        if (twist) q.multiply(turn.setFromAxisAngle(X, flip * twist));
        return q;
      };
      set(bone.quaternion, angles);
      // the clip underneath: its pose, plus how far her code has moved this bone from her plain pose (`base`: her
      // looks, breath, talking, reactions), so all of that still shows on top of the clip
      const clipW = base ? clipNow.boneW[name] || 0 : 0;
      if (clipW > 0.001) {
        layered.copy(clipNow.bones[name]).multiply(set(baseQ, base).invert()).multiply(bone.quaternion);
        bone.quaternion.slerp(layered, clipW);
      }
      if (name === 'hips' && hipsRest) bone.position.copy(hipsRest).addScaledVector(clipNow.hips, base ? clipNow.hipsW : 0);
      if (toward && weight) bone.quaternion.slerp(set(aim, toward), weight);
      // and it gets there from where it was (logic.mjs followJoint): a short filter on every joint, so a new action
      // starting or one being cut short never makes a joint pop, and a spring on her arms (they lag and settle)
      bone.quaternion.fromArray(followJoint(last, name, bone.quaternion.toArray(), dt, follow));
    },
    setFingers,
    setBreeze,
    /** Which clips play under her movement this frame: `parts` = [[clip, t, weight, mask], …] (motions.mjs SOURCES,
     *  MASKS; t: seconds into it, or for 'walk' { phase } of her steps). The weights of what moves one bone add up
     *  to at most 1; less leaves that much of her code's own pose. Before the clips have loaded, nothing plays. */
    setMotion(parts) {
      for (const n in clipNow.boneW) clipNow.boneW[n] = 0;
      clipNow.hipsW = 0;
      if (!clips || !parts) return;
      for (const [key, time, weight, maskName] of parts) {
        if (weight <= 0.001 || !clips.has(key)) continue;
        const mask = MASKS[maskName] || MASKS.full;
        clips.sample(key, time?.phase != null ? walkTime(time.phase, clips.timing(key)) : time, clipB);
        for (const n in clipB.bones) {
          const s = weight * (mask[n] || 0), had = clipNow.boneW[n] || 0;
          if (s <= 0.001) continue;
          if (had <= 0.001) (clipNow.bones[n] ||= new THREE.Quaternion()).copy(clipB.bones[n]);
          else clipNow.bones[n].slerp(clipB.bones[n], s / (had + s));
          clipNow.boneW[n] = had + s;
        }
        const s = weight * (mask.hips || 0);
        if (s > 0.001) {
          if (clipNow.hipsW <= 0.001) clipNow.hips.copy(clipB.hips);
          else clipNow.hips.lerp(clipB.hips, s / (clipNow.hipsW + s));
          clipNow.hipsW += s;
        }
      }
      for (const n in clipNow.boneW) clipNow.boneW[n] = Math.min(1, clipNow.boneW[n]);
      clipNow.hipsW = Math.min(1, clipNow.hipsW);
    },
    get clipsReady() { return !!clips; },
    hasClip(key) { return !!clips?.has(key); },
    /** For IK (piano.mjs): a joint's normalised node (what setBone turns), where a wrist is, and where the middle
     *  of the fingers is (to point the hand). */
    node(name) { return vrm.humanoid?.getNormalizedBoneNode(name) || null; },
    wrist(side, out = new THREE.Vector3()) { return vrm.humanoid.getNormalizedBoneNode(`${side}Hand`).getWorldPosition(out); },
    fingerTip(side, out = new THREE.Vector3()) {
      const n = vrm.humanoid?.getNormalizedBoneNode(`${side}MiddleProximal`);
      return n ? n.getWorldPosition(out) : null;
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
    setExpression(name, w) { faceValues[name] = w; },
    look(x, y) { eyesOn.position.set(x * 1.5, HEIGHT * 0.85 + y * 1.0, 3); },
    update(dt) {
      for (const [name, weight] of Object.entries(vrmCharacterExpressions(faceValues, faceAvailable))) express(name, weight);
      vrm.update(Math.min(dt, 1 / 20));
    },   // steady small steps: a long one makes hair and skirt explode
  };
}

/** How a game's anime characters are lit, on top of what the VRM file asks for (VRoid exports are flat: no rim, a
 *  soft wash of shade). Per kind of material, read from its name (VRoid names them …_FACE, _SKIN, _HAIR, _CLOTH,
 *  _EYE): a cel shadow edge on hair and clothes, a little shape on her face (a hard edge there looks dirty without a
 *  painted face-shadow map), and a thin light along her silhouette that takes the colour of the light (rimLightingMix),
 *  so she separates from any desktop behind her. Eyes are left alone. Materials of other models without these names
 *  get the clothes' settings. */
export const SHADING = {
  face:  { toony: 0.55, shift: -0.65, rim: 0.14, power: 5.0 },
  skin:  { toony: 0.85, shift: -0.45, rim: 0.22, power: 4.0 },
  hair:  { toony: 0.92, shift: -0.30, rim: 0.42, power: 3.0 },
  cloth: { toony: 0.92, shift: -0.40, rim: 0.32, power: 3.4 },
};
export function shadingKind(name) {
  if (/_EYE\b|eye|iris|highlight/i.test(name)) return null;
  if (/_FACE|face/i.test(name)) return 'face';
  if (/_SKIN|skin|body/i.test(name)) return 'skin';
  if (/_HAIR|hair/i.test(name)) return 'hair';
  return 'cloth';
}
function polishShading(THREE, scene) {
  const rimColour = new THREE.Color(1.0, 0.94, 0.98);
  scene.traverse(obj => {
    for (const m of [obj.material].flat()) {
      if (!m?.isMToonMaterial || m.isOutline) continue;
      const kind = shadingKind(m.name || ''), s = kind && SHADING[kind];
      if (!s) continue;
      m.shadingToonyFactor = Math.max(m.shadingToonyFactor, s.toony);
      m.shadingShiftFactor = s.shift;
      m.parametricRimColorFactor.copy(rimColour).multiplyScalar(s.rim);
      m.parametricRimFresnelPowerFactor = s.power;
      m.parametricRimLiftFactor = 0;
      m.rimLightingMixFactor = 1;
    }
  });
}
