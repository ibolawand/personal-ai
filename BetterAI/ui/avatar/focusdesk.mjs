// A small, locally generated desk: no textures, external assets or services.
import { makeIK } from './piano.mjs';
import { PIANO, HANDS, mixHand } from './logic.mjs';
import { writing } from './presence.mjs';

export function buildFocusDesk(THREE, layout) {
  const group = new THREE.Group(), ik = makeIK(THREE);
  const material = color => new THREE.MeshToonMaterial({ color });
  const wood = material(0xc7a27a), violet = material(0x8871c9), paper = material(0xfff9e8), ink = material(0x8b83a5);
  const box = (w, h, d, mat, x, y, z) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    mesh.position.set(x, y, z); group.add(mesh); return mesh;
  };
  const { keyY: y, keyZ: z, keyWidth: width, benchY, benchZ } = layout;
  const depth = width * 0.35, centre = z + depth * 0.3;
  box(width * 0.9, 0.025, depth, wood, 0, y - 0.02, centre);
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    box(0.025, y - 0.04, 0.025, wood, sx * width * 0.38, (y - 0.04) / 2, centre + sz * depth * 0.38);
    box(0.022, benchY, 0.022, wood, sx * width * 0.2, benchY / 2, benchZ + sz * 0.055);
  }
  box(width * 0.5, 0.035, 0.16, violet, 0, benchY - 0.0175, benchZ);
  box(width * 0.46, 0.012, depth * 0.72, violet, 0, y, z);
  for (const sx of [-1, 1]) {
    box(width * 0.215, 0.005, depth * 0.67, paper, sx * width * 0.115, y + 0.009, z);
    for (let i = 0; i < 5; i++) box(width * 0.16, 0.001, 0.002, ink,
      sx * width * 0.115, y + 0.012, z - depth * 0.23 + i * depth * 0.095);
  }
  const pen = new THREE.Mesh(new THREE.CylinderGeometry(0.003, 0.003, 0.075, 8), violet);
  pen.name = 'focus-pen';
  group.add(pen);
  const target = new THREE.Vector3(), pole = new THREE.Vector3(), direction = new THREE.Vector3();
  const localPen = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  return {
    group,
    update(rig, stage, t, floorY, hands = null) {
      group.visible = stage.show > 0.001;
      if (!group.visible) return;
      group.position.set(rig.root.position.x, floorY, rig.root.position.z);
      group.rotation.y = PIANO.yaw * stage.turn;
      group.scale.setScalar(Math.max(0.001, stage.show));
      group.updateMatrixWorld(true);
      const w = writing(t);
      pen.visible = stage.hands > 0.01;
      if (!pen.visible || !rig.node) return;
      for (const [side, sign] of [['left', 1], ['right', -1]]) {
        target.set(side === 'right' ? w.x : width * 0.14,
                   y + 0.045 + (side === 'right' ? w.lift : 0), z - 0.025 + (side === 'right' ? w.z : 0));
        group.localToWorld(target);
        const upper = rig.node(`${side}UpperArm`);
        if (!upper) continue;
        upper.getWorldPosition(pole);
        pole.x += sign * 0.22 * Math.cos(PIANO.yaw);
        pole.z -= sign * 0.22 * Math.sin(PIANO.yaw);
        pole.y -= 0.18;
        direction.set(Math.sin(PIANO.yaw), -0.55, Math.cos(PIANO.yaw)).normalize();
        ik.reach(rig, side, target, pole, stage.hands, direction);
      }
      // The pen follows the actual posed hand, including while her arms are arriving/leaving.
      const hand = rig.node('rightHand');
      if (hand || rig.wrist) {
        if (hand) hand.getWorldPosition(localPen);
        else rig.wrist('right', localPen);
        group.worldToLocal(localPen);
        pen.position.copy(localPen);
        pen.position.y -= 0.025;
        pen.quaternion.setFromUnitVectors(up, direction.set(0.25, 1, -0.3).normalize());
      }
      if (hands && rig.setFingers) rig.setFingers({
        left: mixHand(hands.left, HANDS.flat, stage.hands),
        right: mixHand(hands.right, HANDS.pinch, stage.hands),
      });
    },
  };
}
