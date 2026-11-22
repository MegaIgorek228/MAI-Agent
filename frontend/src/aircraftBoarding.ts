import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

export const boardingDoor = { left: -5.33, right: -4.58, sill: -.58, top: .89 };

type Point = readonly [number, number, number];

export function createAircraftBoardingStair(): THREE.Group {
  const stair = new THREE.Group();
  stair.name = "Hinged forward boarding stair";
  const batches = new Map<THREE.Material, THREE.BufferGeometry[]>();
  const aluminum = new THREE.MeshStandardMaterial({ color: "#c6cdd0", metalness: .66, roughness: .43 });
  const painted = new THREE.MeshStandardMaterial({ color: "#d8d9d6", metalness: .18, roughness: .46 });
  const fasteners = new THREE.MeshStandardMaterial({ color: "#6b777f", metalness: .75, roughness: .35 });
  const grip = new THREE.MeshStandardMaterial({ color: "#363f45", roughness: .92 });
  const center = (boardingDoor.left + boardingDoor.right) / 2;
  const stepCount = 10;
  const rise = .242;
  const run = .238;
  const threshold = 1.12;
  const sides = [center - .315, center + .315];
  const up = new THREE.Vector3(0, 1, 0);

  function append(geometry: THREE.BufferGeometry, material: THREE.Material) {
    if (geometry.index) {
      const unindexed = geometry.toNonIndexed();
      geometry.dispose();
      geometry = unindexed;
    }
    const batch = batches.get(material);
    if (batch) batch.push(geometry);
    else batches.set(material, [geometry]);
  }

  function plate(size: Point, position: Point, material: THREE.Material, bevel = .012) {
    const geometry = new RoundedBoxGeometry(...size, 1, bevel);
    append(geometry.translate(...position), material);
  }

  function rail(from: Point, to: Point, radius: number, material: THREE.Material) {
    const start = new THREE.Vector3(...from);
    const end = new THREE.Vector3(...to);
    const direction = end.clone().sub(start);
    const geometry = new THREE.CylinderGeometry(radius, radius, direction.length(), 10);
    geometry.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(up, direction.normalize()));
    geometry.translate(...start.lerp(end, .5).toArray());
    append(geometry, material);
  }

  for (let index = 0; index < stepCount; index += 1) {
    const y = boardingDoor.sill - index * rise;
    const z = threshold + (index + .56) * run;
    plate([.64, .056, run + .012], [center, y - .028, z], aluminum);
    plate([.55, .009, .16], [center, y + .005, z + .008], grip, .004);
    plate([.64, .018, .024], [center, y - .009, z + .117], painted, .006);
  }

  const last = stepCount - 1;
  const footZ = threshold + (last + .75) * run;
  const startY = boardingDoor.sill - .11;
  for (const x of sides) {
    rail([x, startY, threshold], [x, -2.94, footZ], .042, painted);
    rail([x, boardingDoor.sill - .026, threshold + .01], [x, -2.934, footZ], .019, aluminum);
    rail([x, -2.76, footZ - .014], [x, -2.972, footZ + .07], .025, fasteners);
    plate([.11, .052, .21], [x, -2.974, footZ + .042], grip, .013);

    const handStart: Point = [x, boardingDoor.sill + .57, threshold - .08];
    const handEnd: Point = [x, boardingDoor.sill - last * rise + .54, footZ - .07];
    rail(handStart, handEnd, .021, painted);
    rail([x, handStart[1] + .16, threshold - .15], handStart, .021, aluminum);
    rail(handEnd, [x, handEnd[1] - .16, footZ + .04], .021, aluminum);
    for (const index of [1, 4, 7, 9]) {
      const y = boardingDoor.sill - index * rise;
      const z = threshold + (index + .35) * run;
      rail([x, y - .07, z], [x, y + .55, z], .013, aluminum);
      plate([.072, .028, .087], [x, y - .046, z], fasteners, .008);
    }
  }
  plate([.7, .048, .16], [center, boardingDoor.sill - .026, threshold - .025], fasteners);

  for (const [material, parts] of batches) {
    const merged = mergeGeometries(parts);
    for (const part of parts) part.dispose();
    if (merged) stair.add(new THREE.Mesh(merged, material));
  }
  return stair;
}
