import * as THREE from 'three';

export type ShadingMode = 'solid' | 'wireframe' | 'xray';

const XRAY_OPACITY = 0.3;

/**
 * Switch every mesh material in *group* to the given display mode.
 *
 * Only material flags change, so switching is instant and needs no rebuild:
 * - solid: the normal opaque, front-face shaded model
 * - wireframe: triangle edges only, to inspect mesh density / topology
 * - xray: see-through, both faces drawn and no depth writes, so hidden inner
 *   walls, cavities and overlapping parts stay visible
 */
export function applyShadingMode(group: THREE.Object3D, mode: ShadingMode) {
  group.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return;
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of materials as THREE.Material[]) {
      const xray = mode === 'xray';
      if ('wireframe' in material) {
        (material as THREE.MeshPhongMaterial).wireframe = mode === 'wireframe';
      }
      material.transparent = xray;
      material.opacity = xray ? XRAY_OPACITY : 1;
      material.depthWrite = !xray;
      material.side = xray ? THREE.DoubleSide : THREE.FrontSide;
      material.needsUpdate = true;
    }
  });
}
