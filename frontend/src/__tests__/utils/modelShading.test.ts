import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { applyShadingMode } from '../../utils/modelShading';

function makeGroup() {
  const group = new THREE.Group();
  const a = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshPhongMaterial());
  const b = new THREE.Mesh(new THREE.BoxGeometry(), [new THREE.MeshPhongMaterial(), new THREE.MeshPhongMaterial()]);
  group.add(a, b);
  const materials = [a.material, ...(b.material as THREE.MeshPhongMaterial[])] as THREE.MeshPhongMaterial[];
  return { group, materials };
}

describe('applyShadingMode', () => {
  it('wireframe draws edges only and stays opaque', () => {
    const { group, materials } = makeGroup();
    applyShadingMode(group, 'wireframe');
    for (const m of materials) {
      expect(m.wireframe).toBe(true);
      expect(m.transparent).toBe(false);
      expect(m.opacity).toBe(1);
    }
  });

  it('xray makes every material see-through and double sided', () => {
    const { group, materials } = makeGroup();
    applyShadingMode(group, 'xray');
    for (const m of materials) {
      expect(m.wireframe).toBe(false);
      expect(m.transparent).toBe(true);
      expect(m.opacity).toBeLessThan(1);
      expect(m.depthWrite).toBe(false);
      expect(m.side).toBe(THREE.DoubleSide);
    }
  });

  it('solid restores the default look after another mode', () => {
    const { group, materials } = makeGroup();
    applyShadingMode(group, 'xray');
    applyShadingMode(group, 'wireframe');
    applyShadingMode(group, 'solid');
    for (const m of materials) {
      expect(m.wireframe).toBe(false);
      expect(m.transparent).toBe(false);
      expect(m.opacity).toBe(1);
      expect(m.depthWrite).toBe(true);
      expect(m.side).toBe(THREE.FrontSide);
    }
  });
});
