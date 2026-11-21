import {
  BoxGeometry,
  BufferGeometry,
  CylinderGeometry,
  Group,
  Material,
  Mesh,
  MeshStandardMaterial,
} from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

type Vector = readonly [number, number, number];

export function createAircraftInterior(): Group {
  const floor = -.57;
  const materials = {
    deck: new MeshStandardMaterial({ color: "#a5a197", roughness: .86 }),
    deckFlight: new MeshStandardMaterial({ color: "#515353", roughness: .91 }),
    runner: new MeshStandardMaterial({ color: "#837d72", roughness: 1 }),
    rug: new MeshStandardMaterial({ color: "#ada297", roughness: 1 }),
    wall: new MeshStandardMaterial({ color: "#d5cdbd", roughness: .79 }),
    trim: new MeshStandardMaterial({ color: "#e7e0d2", roughness: .6 }),
    seam: new MeshStandardMaterial({ color: "#a69d8d", roughness: .82 }),
    window: new MeshStandardMaterial({ color: "#cddae0", emissive: "#93adb8", emissiveIntensity: .23, roughness: .34 }),
    light: new MeshStandardMaterial({ color: "#f5e4c8", emissive: "#efcca0", emissiveIntensity: .38 }),
    bracket: new MeshStandardMaterial({ color: "#8c8f8c", metalness: .29, roughness: .57 }),
    frame: new MeshStandardMaterial({ color: "#c1c1b7", roughness: .59 }),
    cushion: new MeshStandardMaterial({ color: "#597286", roughness: .91 }),
    cushionInset: new MeshStandardMaterial({ color: "#6e8496", roughness: .85 }),
    selected: new MeshStandardMaterial({ color: "#889fae", roughness: .85 }),
    selectedInset: new MeshStandardMaterial({ color: "#a4b5be", roughness: .83 }),
    charcoal: new MeshStandardMaterial({ color: "#41464a", roughness: .87 }),
    vinyl: new MeshStandardMaterial({ color: "#646a6f", roughness: .8 }),
    instrument: new MeshStandardMaterial({ color: "#292e30", roughness: .68 }),
    instrumentFace: new MeshStandardMaterial({ color: "#3e4749", roughness: .68 }),
    readout: new MeshStandardMaterial({ color: "#427786", emissive: "#25565b", emissiveIntensity: .35, roughness: .46 }),
    dial: new MeshStandardMaterial({ color: "#9cae97", emissive: "#75856c", emissiveIntensity: .12 }),
    sofa: new MeshStandardMaterial({ color: "#535a5e", roughness: .91 }),
    sofaInset: new MeshStandardMaterial({ color: "#687075", roughness: .88 }),
    pillow: new MeshStandardMaterial({ color: "#b3a992", roughness: .92 }),
    wood: new MeshStandardMaterial({ color: "#9b846a", roughness: .64 }),
    woodLight: new MeshStandardMaterial({ color: "#b99b78", roughness: .62 }),
  };
  const primitives = new Map<string, BufferGeometry>();

  function place(parent: Group, key: string, create: () => BufferGeometry, material: Material, position: Vector) {
    let geometry = primitives.get(key);
    if (!geometry) {
      geometry = create();
      primitives.set(key, geometry);
    }

    const mesh = new Mesh(geometry, material);
    mesh.position.set(...position);
    parent.add(mesh);
    return mesh;
  }

  function box(parent: Group, material: Material, size: Vector, position: Vector, radius = .035) {
    const key = `box:${size.join(",")}:${radius}`;
    const bevelSteps = radius >= .04 ? 2 : 1;
    return place(parent, key, () => radius
      ? new RoundedBoxGeometry(...size, bevelSteps, radius)
      : new BoxGeometry(...size), material, position);
  }

  function cylinder(parent: Group, material: Material, radius: number, height: number, position: Vector) {
    const key = `cylinder:${radius}:${height}`;
    return place(parent, key, () => new CylinderGeometry(radius, radius, height, 20), material, position);
  }

  function deck(parent: Group, min: number, max: number, width: number, material: Material) {
    const length = max - min;
    const middle = (min + max) / 2;
    box(parent, material, [length, .07, width], [middle, floor - .035, 0], .023);
    box(parent, materials.seam, [length - .055, .036, .038], [middle, floor - .025, width / 2 - .006], .012);
  }

  function trimPartition(parent: Group, x: number) {
    for (const direction of [-1, 1]) {
      const z = direction * .66;
      box(parent, materials.wall, [.135, 1.29, .61], [x, .09, z], .045);
      box(parent, materials.trim, [.145, 1.18, .027], [x + .006, .08, z - direction * .28], .009);
      box(parent, materials.seam, [.022, .085, .43], [x + .078, floor + .04, z], .007);
    }
    box(parent, materials.wall, [.14, .2, 1.36], [x, .79, 0], .04);
  }

  function sidewall(parent: Group, min: number, max: number, windows: number[]) {
    const length = max - min;
    const middle = (max + min) / 2;
    box(parent, materials.wall, [length, .48, .095], [middle, -.308, -.94], .032);
    box(parent, materials.trim, [length, .43, .09], [middle, .545, -.88], .033);
    box(parent, materials.seam, [length - .05, .025, .04], [middle, -.08, -.867], .012);

    let start = min;
    for (const x of windows) {
      const gap = x - .18 - start;
      box(parent, materials.wall, [gap, .44, .08], [start + gap / 2, .126, -.945], .021);
      box(parent, materials.seam, [.37, .406, .055], [x, .12, -.951], .17);
      box(parent, materials.trim, [.308, .345, .055], [x, .126, -.918], .14);
      box(parent, materials.window, [.227, .265, .033], [x, .133, -.883], .108);
      start = x + .18;
    }
    box(parent, materials.wall, [max - start, .44, .08], [(max + start) / 2, .126, -.945], .021);
  }

  function overhead(parent: Group, min: number, max: number) {
    const middle = (max + min) / 2;
    const length = max - min;
    for (const direction of [-1, 1]) {
      for (const offset of [-1, 0, 1]) {
        const x = middle + offset * length / 3;
        box(parent, materials.wall, [length / 3 - .015, .195, .306], [x, .755, direction * .727], .068);
        box(parent, materials.seam, [.175, .022, .047], [x, .687, direction * .594], .01);
      }
      box(parent, materials.light, [length - .1, .025, .054], [middle, .645, direction * .789], .011);
    }
  }

  function seat(parent: Group, x: number, z: number, highlighted = false, pilot = false) {
    const frame = pilot ? materials.instrumentFace : materials.frame;
    const padding = pilot ? materials.charcoal : highlighted ? materials.selected : materials.cushion;
    const insert = pilot ? materials.vinyl : highlighted ? materials.selectedInset : materials.cushionInset;
    const seat = new Group();
    seat.position.set(x, 0, z);
    parent.add(seat);

    for (const side of [-1, 1]) {
      box(seat, materials.bracket, [.49, .031, .05], [-.018, floor + .026, side * .168], .008);
      box(seat, frame, [.09, .16, .055], [.139, floor + .089, side * .16], .014).rotation.z = -.14;
      box(seat, frame, [.10, .16, .055], [-.158, floor + .089, side * .16], .014).rotation.z = .14;
      box(seat, frame, [.06, .151, .045], [.086, -.224, side * .255], .012);
      box(seat, frame, [.391, .065, .058], [-.046, -.143, side * .255], .023);
      box(seat, padding, [.257, .023, .051], [-.094, -.102, side * .255], .011);
    }

    box(seat, frame, [.539, .097, .462], [-.024, -.385, 0], .041);
    box(seat, padding, [.528, .105, .389], [-.061, -.328, 0], .047);
    box(seat, insert, [.445, .036, .294], [-.078, -.275, 0], .017);
    // The cabin faces negative x, so the positive-x backs describe the recline.
    box(seat, frame, [.121, .696, .412], [.247, -.047, 0], .054).rotation.z = -.165;
    box(seat, padding, [.116, .606, .37], [.161, -.065, 0], .054).rotation.z = -.165;
    box(seat, insert, [.042, .455, .298], [.091, -.077, 0], .018).rotation.z = -.165;
    box(seat, insert, [.141, .139, .308], [.182, .257, 0], .063).rotation.z = -.165;

    if (!pilot) {
      box(seat, materials.trim, [.022, .219, .292], [.298, -.052, 0], .01).rotation.z = -.165;
      box(seat, materials.bracket, [.03, .028, .081], [.325, .06, 0], .007);
    }
  }

  const cockpit = new Group();
  cockpit.name = "Flight deck";
  deck(cockpit, -7.82, -5.27, 1.77, materials.deckFlight);
  box(cockpit, materials.instrumentFace, [2.24, .96, .086], [-6.58, -.008, -.817], .04);
  box(cockpit, materials.charcoal, [2.04, .13, .29], [-6.61, .535, -.665], .05);
  trimPartition(cockpit, -5.26);
  seat(cockpit, -6.42, -.455, false, true);
  seat(cockpit, -6.42, .455, false, true);

  box(cockpit, materials.instrument, [.437, .54, 1.51], [-7.53, -.013, 0], .075).rotation.z = -.14;
  box(cockpit, materials.instrument, [.41, .105, 1.59], [-7.49, .29, 0], .052).rotation.z = -.11;
  box(cockpit, materials.instrumentFace, [.06, .35, 1.43], [-7.28, .065, 0], .026).rotation.z = -.14;

  for (const z of [-.48, -.16, .16, .48]) {
    box(cockpit, materials.instrument, [.035, .187, .267], [-7.232, .106, z], .017);
    box(cockpit, materials.readout, [.021, .143, .213], [-7.205, .107, z], .01);
    box(cockpit, materials.dial, [.015, .014, .13], [-7.19, .129, z], .006);
    box(cockpit, materials.dial, [.015, .058, .018], [-7.19, .09, z - .029], .006);
    box(cockpit, materials.instrumentFace, [.05, .052, .227], [-7.221, -.05, z], .01);
    for (const shift of [-.075, 0, .075]) {
      const knob = cylinder(cockpit, materials.seam, .015, .021, [-7.182, -.05, z + shift]);
      knob.rotation.z = Math.PI / 2;
    }
  }

  for (const position of [-.455, .455]) {
    const column = cylinder(cockpit, materials.instrument, .043, .455, [-7.013, -.119, position]);
    column.rotation.z = Math.PI / 2 - .16;
    box(cockpit, materials.instrument, [.079, .057, .249], [-6.825, -.071, position], .025);
    for (const offset of [-.102, .102]) {
      box(cockpit, materials.vinyl, [.067, .143, .058], [-6.824, -.033, position + offset], .026);
      box(cockpit, materials.bracket, [.125, .033, .075], [-7.33, floor + .055, position + offset], .013).rotation.z = .35;
    }
  }

  box(cockpit, materials.instrument, [1.08, .318, .237], [-6.86, -.393, 0], .042);
  box(cockpit, materials.instrumentFace, [.97, .044, .212], [-6.89, -.204, 0], .021);
  for (const z of [-.052, .052]) {
    box(cockpit, materials.bracket, [.05, .114, .027], [-6.81, -.147, z], .008).rotation.z = .24;
    box(cockpit, materials.vinyl, [.063, .044, .05], [-6.823, -.078, z], .018);
  }
  box(cockpit, materials.instrument, [.51, .066, .8], [-6.94, .846, 0], .031);
  for (const z of [-.295, -.172, -.05, .05, .172, .295]) {
    box(cockpit, materials.dial, [.14, .025, .024], [-6.96, .803, z], .011);
  }

  const cabin = new Group();
  cabin.name = "Passenger cabin";
  deck(cabin, -5.19, 1.103, 2.137, materials.deck);
  box(cabin, materials.runner, [6.16, .012, .417], [-2.1, floor + .002, .014], .005);
  sidewall(cabin, -5.15, 1.02, [-4.55, -3.7, -2.85, -2, -1.15, -.30, .55]);
  overhead(cabin, -5.04, .93);
  trimPartition(cabin, 1.04);

  for (const x of [-4.52, -3.45, -2.48, -1.56, -.642, .279]) {
    seat(cabin, x, -.614);
    seat(cabin, x, .578, x === -3.45);
  }

  const lounge = new Group();
  lounge.name = "Lounge";
  deck(lounge, 1.095, 5.31, 2.115, materials.deck);
  sidewall(lounge, 1.16, 5.25, [1.60, 2.41, 3.22, 4.03, 4.84]);
  overhead(lounge, 1.17, 5.16);
  box(lounge, materials.rug, [2.72, .017, 1.42], [2.972, floor + .006, .08], .008);

  function loungeSeat(x: number, z: number, width: number, rotation: number, double = false) {
    const furniture = new Group();
    furniture.position.set(x, 0, z);
    furniture.rotation.y = rotation;
    lounge.add(furniture);

    for (const side of [-1, 1]) {
      for (const edge of [-1, 1]) {
        box(furniture, materials.wood, [.048, .067, .049], [side * (width / 2 - .082), floor + .035, edge * .241], .013);
      }
      box(furniture, materials.sofa, [.129, .334, .574], [side * (width / 2 - .064), -.345, 0], .06);
    }

    box(furniture, materials.sofa, [width - .046, .186, .563], [0, -.41, 0], .068);
    box(furniture, materials.sofa, [width - .038, .473, .158], [0, -.203, -.233], .073).rotation.x = -.13;
    const seats = double ? [-.235, .235] : [0];
    for (const offset of seats) {
      const padWidth = double ? .455 : width - .215;
      box(furniture, materials.sofaInset, [padWidth, .107, .42], [offset, -.297, .043], .048);
      box(furniture, materials.sofaInset, [padWidth, .336, .091], [offset, -.139, -.174], .043).rotation.x = -.13;
    }
    box(furniture, materials.pillow, [.184, .192, .087], [width / 2 - .19, -.185, -.098], .041)
      .rotation.set(-.2, 0, -.16);
  }

  loungeSeat(1.72, .52, .698, Math.PI / 2);
  loungeSeat(4.19, -.626, 1.21, 0, true);
  loungeSeat(3.15, -.528, .68, .37);
  const table = cylinder(lounge, materials.woodLight, .423, .07, [2.77, -.29, .283]);
  table.scale.z = .73;
  for (const [x, z] of [[2.53, .269], [2.99, .184], [2.94, .427]]) {
    box(lounge, materials.wood, [.059, .25, .06], [x, -.425, z], .019);
  }
  box(lounge, materials.trim, [.18, .02, .127], [2.786, -.247, .24], .008).rotation.y = -.17;
  cylinder(lounge, materials.wall, .054, .015, [2.99, -.245, .305]);
  cylinder(lounge, materials.trim, .031, .069, [2.99, -.205, .305]);

  box(lounge, materials.wood, [.318, 1.218, .695], [5.051, .042, -.536], .038);
  box(lounge, materials.woodLight, [.322, .036, .683], [5.05, .659, -.536], .013);
  box(lounge, materials.seam, [.322, .018, .673], [5.049, -.129, -.536], .008);
  for (const y of [.104, .348]) {
    box(lounge, materials.instrumentFace, [.019, .196, .64], [4.881, y, -.533], .009);
    box(lounge, materials.woodLight, [.113, .025, .64], [4.828, y - .078, -.533], .011);
    for (const z of [-.745, -.642, -.54, -.437, -.334]) {
      cylinder(lounge, materials.pillow, .027, .101, [4.842, y - .01, z]);
    }
  }

  const combined = new Group();
  combined.name = "Aircraft interior";

  // Batch stationary cabin fittings without losing the three independent sections.
  for (const region of [cockpit, cabin, lounge]) {
    region.updateMatrixWorld(true);
    const parts = new Map<Material, BufferGeometry[]>();
    region.traverse((child) => {
      if (!(child instanceof Mesh)) return;
      const geometry = child.geometry.index ? child.geometry.toNonIndexed() : child.geometry.clone();
      geometry.applyMatrix4(child.matrixWorld);
      const material = child.material as Material;
      const group = parts.get(material) ?? [];
      group.push(geometry);
      parts.set(material, group);
    });

    const geometryGroup = new Group();
    geometryGroup.name = region.name;
    for (const [material, geometries] of parts) {
      const merged = mergeGeometries(geometries);
      for (const geometry of geometries) geometry.dispose();
      if (merged) geometryGroup.add(new Mesh(merged, material));
    }
    combined.add(geometryGroup);
  }

  for (const geometry of primitives.values()) geometry.dispose();
  return combined;
}
