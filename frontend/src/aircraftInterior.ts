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
    runner: new MeshStandardMaterial({ color: "#737a78", roughness: 1 }),
    carpetEdge: new MeshStandardMaterial({ color: "#919994", roughness: .96 }),
    rug: new MeshStandardMaterial({ color: "#a59a8c", roughness: 1 }),
    wall: new MeshStandardMaterial({ color: "#d5cdbd", roughness: .79 }),
    trim: new MeshStandardMaterial({ color: "#e7e0d2", roughness: .6 }),
    seam: new MeshStandardMaterial({ color: "#a69d8d", roughness: .82 }),
    slate: new MeshStandardMaterial({ color: "#505d5e", roughness: .76 }),
    satin: new MeshStandardMaterial({ color: "#9d9d92", metalness: .47, roughness: .5 }),
    fabricSeam: new MeshStandardMaterial({ color: "#aab7bd", roughness: .92 }),
    window: new MeshStandardMaterial({ color: "#cddae0", emissive: "#93adb8", emissiveIntensity: .23, roughness: .34 }),
    light: new MeshStandardMaterial({ color: "#faeacb", emissive: "#ffcf97", emissiveIntensity: .59, roughness: .51 }),
    bracket: new MeshStandardMaterial({ color: "#8c8f8c", metalness: .29, roughness: .57 }),
    frame: new MeshStandardMaterial({ color: "#a8aaa3", roughness: .64 }),
    cushion: new MeshStandardMaterial({ color: "#3e5667", roughness: .95 }),
    cushionInset: new MeshStandardMaterial({ color: "#536b7b", roughness: .9 }),
    selected: new MeshStandardMaterial({ color: "#6d8693", roughness: .91 }),
    selectedInset: new MeshStandardMaterial({ color: "#99afb6", roughness: .89 }),
    charcoal: new MeshStandardMaterial({ color: "#41464a", roughness: .87 }),
    vinyl: new MeshStandardMaterial({ color: "#646a6f", roughness: .8 }),
    instrument: new MeshStandardMaterial({ color: "#292e30", roughness: .68 }),
    instrumentFace: new MeshStandardMaterial({ color: "#3e4749", roughness: .68 }),
    readout: new MeshStandardMaterial({ color: "#173c47", emissive: "#143541", emissiveIntensity: .45, roughness: .42 }),
    readoutSky: new MeshStandardMaterial({ color: "#3a7e98", emissive: "#4a9cb9", emissiveIntensity: .7, roughness: .43 }),
    readoutGround: new MeshStandardMaterial({ color: "#73503f", emissive: "#965a3c", emissiveIntensity: .38, roughness: .49 }),
    signal: new MeshStandardMaterial({ color: "#93bfa5", emissive: "#53a56c", emissiveIntensity: .75, roughness: .57 }),
    caution: new MeshStandardMaterial({ color: "#e6a157", emissive: "#dd7a39", emissiveIntensity: .65, roughness: .46 }),
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

  function cylinder(parent: Group, material: Material, radius: number, height: number, position: Vector, segments = 14) {
    const key = `cylinder:${radius}:${height}:${segments}`;
    return place(parent, key, () => new CylinderGeometry(radius, radius, height, segments), material, position);
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
    box(parent, materials.trim, [length, .43, .09], [middle, .545, -.88], .033).rotation.x = -.22;
    box(parent, materials.seam, [length - .05, .023, .04], [middle, -.08, -.867], .01);
    box(parent, materials.slate, [length - .05, .12, .035], [middle, -.486, -.875], .012);
    box(parent, materials.light, [length - .13, .018, .022], [middle, -.481, -.855], .006);

    let start = min;
    for (const x of windows) {
      const gap = x - .18 - start;
      box(parent, materials.wall, [gap, .44, .08], [start + gap / 2, .126, -.945], .021);
      box(parent, materials.seam, [.37, .428, .055], [x, .12, -.95], .12);
      box(parent, materials.trim, [.308, .365, .039], [x, .128, -.917], .098);
      box(parent, materials.slate, [.25, .312, .029], [x, .122, -.894], .082);
      box(parent, materials.window, [.213, .273, .025], [x, .125, -.876], .074);
      box(parent, materials.trim, [.234, .041, .021], [x, .247, -.857], .009);
      box(parent, materials.satin, [.05, .012, .01], [x, .225, -.842], 0);
      box(parent, materials.wall, [.42, .201, .044], [x, -.267, -.873], .022);
      box(parent, materials.seam, [gap > .35 ? .019 : .012, .52, .013], [x - .229, -.232, -.855], 0);
      for (const slat of [-.085, 0, .085]) {
        box(parent, materials.seam, [.063, .017, .013], [x + slat, -.317, -.844], 0);
      }
      start = x + .18;
    }
    box(parent, materials.wall, [max - start, .44, .08], [(max + start) / 2, .126, -.945], .021);
  }

  function overhead(parent: Group, min: number, max: number) {
    const middle = (max + min) / 2;
    const length = max - min;
    const compartments = Math.round(length / 1.03);
    const pitch = length / compartments;
    box(parent, materials.trim, [length, .095, 1.48], [middle, .883, 0], .028);
    box(parent, materials.seam, [length - .11, .016, .33], [middle, .827, 0], .006);
    box(parent, materials.light, [length - .18, .012, .14], [middle, .814, 0], .005);
    for (const direction of [-1, 1]) {
      for (let index = 0; index < compartments; index += 1) {
        const x = min + (index + .5) * pitch;
        box(parent, materials.wall, [pitch - .026, .181, .287], [x, .761, direction * .745], .044);
        box(parent, materials.trim, [pitch - .059, .126, .037], [x, .746, direction * .593], .016)
          .rotation.x = direction * .22;
        box(parent, materials.seam, [.142, .02, .038], [x, .705, direction * .562], .006);
        box(parent, materials.trim, [.50, .035, .218], [x, .644, direction * .686], .012);
        for (const offset of [-.135, 0, .135]) {
          cylinder(parent, materials.seam, .033, .016, [x + offset, .617, direction * .702], 10);
          cylinder(parent, offset === 0 ? materials.light : materials.satin, .022, .01,
            [x + offset, .606, direction * .702], 10);
        }
      }
      box(parent, materials.light, [length - .1, .019, .036], [middle, .651, direction * .82], .007);
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
    for (const side of [-1, 1]) {
      box(seat, padding, [.422, .046, .065], [-.061, -.26, side * .152], .021);
      box(seat, padding, [.078, .443, .058], [.105, -.059, side * .126], .02).rotation.z = -.165;
      box(seat, pilot ? materials.bracket : materials.fabricSeam, [.005, .355, .012], [.071, -.057, side * .148], 0)
        .rotation.z = -.165;
      box(seat, pilot ? materials.vinyl : materials.cushion, [.19, .018, .046], [-.054, -.227, side * .081], .007)
        .rotation.y = side * .68;
    }
    box(seat, materials.satin, [.059, .021, .061], [.012, -.225, .039], .007);
    box(seat, pilot ? materials.caution : materials.slate, [.026, .012, .033], [-.018, -.215, .039], .002);

    if (pilot) return;
    box(seat, materials.seam, [.024, .247, .32], [.299, -.054, 0], .014).rotation.z = -.165;
    box(seat, materials.trim, [.029, .213, .283], [.312, -.061, 0], .011).rotation.z = -.165;
    box(seat, materials.bracket, [.032, .028, .08], [.335, .054, 0], .007);
    box(seat, materials.slate, [.033, .105, .309], [.299, -.223, 0], .011).rotation.z = -.165;
    box(seat, materials.fabricSeam, [.025, .013, .284], [.32, -.173, 0], .003);
    box(seat, materials.trim, [.016, .065, .183], [.318, -.201, -.024], .005).rotation.set(.04, 0, -.165);
  }

  const cockpit = new Group();
  cockpit.name = "Flight deck";
  deck(cockpit, -7.82, -5.27, 1.77, materials.deckFlight);
  box(cockpit, materials.instrumentFace, [2.24, .96, .086], [-6.58, -.008, -.817], .04);
  box(cockpit, materials.slate, [1.94, .22, .109], [-6.67, -.405, -.76], .027);
  box(cockpit, materials.bracket, [1.78, .026, .034], [-6.69, -.482, -.696], .01);
  box(cockpit, materials.charcoal, [.79, .444, .061], [-6.845, .218, -.754], .034);
  box(cockpit, materials.window, [.63, .31, .042], [-6.86, .231, -.714], .056);
  box(cockpit, materials.slate, [.034, .308, .029], [-6.86, .233, -.689], .005);
  box(cockpit, materials.instrument, [.37, .25, .104], [-5.887, .145, -.746], .025);
  for (const labelY of [.085, .14, .195]) {
    box(cockpit, materials.instrumentFace, [.291, .029, .017], [-5.886, labelY, -.687], .004);
    box(cockpit, labelY < .11 ? materials.caution : materials.signal,
      [.034, .014, .01], [-5.988, labelY, -.674], .003);
  }
  box(cockpit, materials.satin, [.58, .035, .043], [-5.92, -.223, -.692], .011);
  box(cockpit, materials.satin, [.033, .148, .043], [-5.645, -.273, -.692], .011);
  box(cockpit, materials.charcoal, [2.04, .13, .29], [-6.61, .535, -.665], .05);
  box(cockpit, materials.light, [.67, .019, .03], [-6.567, .486, -.513], .006);
  trimPartition(cockpit, -5.26);
  seat(cockpit, -6.42, -.455, false, true);
  seat(cockpit, -6.42, .455, false, true);

  box(cockpit, materials.instrument, [.39, .414, 1.48], [-7.57, -.077, 0], .069).rotation.z = -.14;
  box(cockpit, materials.instrument, [.41, .105, 1.59], [-7.49, .29, 0], .052).rotation.z = -.11;
  box(cockpit, materials.charcoal, [.102, .29, 1.35], [-7.744, -.416, 0], .022);
  for (const z of [-.585, .585]) {
    box(cockpit, materials.instrumentFace, [.16, .274, .129], [-7.657, -.408, z], .021).rotation.z = .1;
    box(cockpit, materials.satin, [.178, .026, .155], [-7.641, floor + .016, z], .007);
  }
  box(cockpit, materials.instrumentFace, [.307, .086, .058], [-7.465, -.143, .752], .022)
    .rotation.z = -.18;
  box(cockpit, materials.satin, [.245, .019, .011], [-7.443, -.145, .786], .004)
    .rotation.z = -.18;
  box(cockpit, materials.instrumentFace, [.06, .35, 1.43], [-7.28, .065, 0], .026).rotation.z = -.14;
  box(cockpit, materials.satin, [.032, .02, 1.29], [-7.273, .236, 0], .006);

  for (const z of [-.50, -.166, .166, .50]) {
    const primary = Math.abs(z) > .3;
    box(cockpit, materials.instrument, [.04, .201, .272], [-7.232, .109, z], .014);
    box(cockpit, materials.readout, [.018, .164, .232], [-7.204, .11, z], .009);
    box(cockpit, materials.readoutSky, [.01, .067, .164], [-7.192, .145, z], .005);
    if (primary) {
      box(cockpit, materials.readoutGround, [.01, .061, .164], [-7.192, .082, z], .005);
      box(cockpit, materials.dial, [.008, .006, .16], [-7.183, .113, z], 0);
      box(cockpit, materials.caution, [.008, .009, .071], [-7.177, .117, z], 0);
    } else {
      const routeLine = box(cockpit, materials.signal, [.009, .011, .123], [-7.183, .1, z], 0);
      routeLine.rotation.x = .33;
      box(cockpit, materials.signal, [.009, .009, .051], [-7.182, .125, z - .04], 0).rotation.x = -.55;
      for (const marker of [-.057, .049]) {
        box(cockpit, materials.dial, [.009, .023, .017], [-7.176, .1 + marker * .36, z + marker], .003);
      }
    }
    for (const offset of [-.093, .093]) {
      for (const mark of [-.05, -.012, .026, .063]) {
        box(cockpit, materials.dial, [.007, .005, .015], [-7.18, .109 + mark, z + offset], 0);
      }
    }
    box(cockpit, materials.instrumentFace, [.05, .052, .227], [-7.221, -.05, z], .01);
    for (const shift of [-.087, -.03, .03, .087]) {
      const knob = cylinder(cockpit, materials.satin, .014, .023, [-7.178, -.05, z + shift], 10);
      knob.rotation.z = Math.PI / 2;
    }
  }
  box(cockpit, materials.instrumentFace, [.217, .048, 1.23], [-7.384, .294, 0], .016);
  for (let index = 0; index < 12; index += 1) {
    const z = -.52 + index * .0945;
    box(cockpit, index % 5 === 0 ? materials.caution : materials.signal, [.049, .012, .042],
      [-7.351, .326, z], .003);
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
  box(cockpit, materials.satin, [.265, .014, .132], [-6.776, -.175, 0], .009);
  box(cockpit, materials.readout, [.181, .017, .118], [-7.169, -.172, 0], .006);
  box(cockpit, materials.readoutSky, [.091, .008, .092], [-7.185, -.16, 0], .005);
  for (const z of [-.052, .052]) {
    box(cockpit, materials.bracket, [.05, .114, .027], [-6.81, -.147, z], .008).rotation.z = .24;
    box(cockpit, materials.vinyl, [.063, .044, .05], [-6.823, -.078, z], .018);
    for (const x of [-7.03, -6.98, -6.93, -6.65, -6.60]) {
      box(cockpit, x < -6.9 ? materials.dial : materials.caution, [.023, .014, .027], [x, -.168, z], .002);
    }
  }
  box(cockpit, materials.instrument, [.51, .066, .8], [-6.94, .846, 0], .031);
  for (const z of [-.295, -.172, -.05, .05, .172, .295]) {
    box(cockpit, materials.instrumentFace, [.29, .031, .089], [-6.95, .803, z], .005);
    box(cockpit, materials.dial, [.081, .019, .024], [-7.02, .782, z], .006);
    box(cockpit, materials.signal, [.033, .012, .028], [-6.913, .779, z], .003);
    box(cockpit, materials.satin, [.024, .025, .012], [-6.855, .774, z], .004).rotation.z = -.29;
  }

  const cabin = new Group();
  cabin.name = "Passenger cabin";
  deck(cabin, -5.19, 1.103, 2.137, materials.deck);
  box(cabin, materials.runner, [6.18, .014, .51], [-2.09, floor + .002, .014], .005);
  for (const z of [-.234, .262]) {
    box(cabin, materials.carpetEdge, [6.13, .008, .023], [-2.09, floor + .011, z], .002);
  }
  sidewall(cabin, -5.15, 1.02, [-4.55, -3.7, -2.85, -2, -1.15, -.30, .55]);
  overhead(cabin, -5.04, .93);
  trimPartition(cabin, 1.04);

  const rows = [-4.52, -3.45, -2.48, -1.56, -.642, .279];
  for (const z of [-.78, -.449, .408, .747]) {
    box(cabin, materials.satin, [5.82, .019, .045], [-2.1, floor + .01, z], .004);
    box(cabin, materials.slate, [5.76, .011, .016], [-2.1, floor + .022, z], .002);
    for (const x of rows) {
      box(cabin, materials.bracket, [.10, .015, .051], [x + .211, floor + .031, z], .004);
    }
  }
  for (const x of rows) {
    seat(cabin, x, -.614);
    seat(cabin, x, .578, x === -3.45);
    box(cabin, materials.satin, [.072, .024, .043], [x - .16, .657, -.561], .006);
    box(cabin, x === -3.45 ? materials.light : materials.seam,
      [.04, .015, .027], [x - .16, .638, -.561], .003);
  }

  const lounge = new Group();
  lounge.name = "Lounge";
  deck(lounge, 1.095, 5.31, 2.115, materials.deck);
  sidewall(lounge, 1.16, 5.25, [1.60, 2.41, 3.22, 4.03, 4.84]);
  overhead(lounge, 1.17, 5.16);
  box(lounge, materials.runner, [2.86, .013, 1.49], [2.972, floor + .006, .08], .008);
  box(lounge, materials.rug, [2.77, .015, 1.40], [2.972, floor + .014, .08], .008);
  for (const z of [-.575, .735]) {
    box(lounge, materials.seam, [2.65, .006, .021], [2.972, floor + .026, z], .003);
  }

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
      box(furniture, materials.slate, [padWidth - .075, .018, .025], [offset, -.274, .242], .007);
      box(furniture, materials.slate, [padWidth - .087, .016, .015], [offset, -.085, -.121], .004);
    }
    box(furniture, materials.pillow, [.192, .216, .102], [width / 2 - .193, -.178, -.084], .043)
      .rotation.set(-.2, 0, -.16);
    if (double) {
      box(furniture, materials.fabricSeam, [.201, .163, .091], [-width / 2 + .204, -.183, -.083], .039)
        .rotation.set(-.22, 0, .14);
    }
  }

  loungeSeat(1.72, .52, .698, Math.PI / 2);
  loungeSeat(4.19, -.626, 1.21, 0, true);
  loungeSeat(3.15, -.528, .68, .37);
  const tableApron = cylinder(lounge, materials.wood, .428, .045, [2.77, -.321, .283], 22);
  tableApron.scale.z = .73;
  const table = cylinder(lounge, materials.woodLight, .423, .039, [2.77, -.279, .283], 22);
  table.scale.z = .73;
  for (const [x, z] of [[2.53, .269], [2.99, .184], [2.94, .427]]) {
    box(lounge, materials.wood, [.059, .25, .06], [x, -.425, z], .019);
  }
  box(lounge, materials.slate, [.199, .017, .137], [2.786, -.25, .24], .004).rotation.y = -.17;
  box(lounge, materials.trim, [.184, .012, .116], [2.792, -.237, .243], .003).rotation.y = -.17;
  box(lounge, materials.wood, [.158, .009, .116], [2.797, -.228, .253], .003).rotation.y = -.23;
  cylinder(lounge, materials.wall, .054, .015, [2.99, -.245, .305]);
  cylinder(lounge, materials.trim, .037, .059, [2.99, -.211, .305]);
  cylinder(lounge, materials.wood, .03, .007, [2.99, -.179, .305]);

  box(lounge, materials.wood, [.394, .458, .358], [3.62, -.335, -.537], .026);
  box(lounge, materials.woodLight, [.433, .034, .398], [3.62, -.09, -.537], .018);
  cylinder(lounge, materials.satin, .073, .028, [3.617, -.055, -.537]);
  cylinder(lounge, materials.satin, .017, .183, [3.617, .041, -.537]);
  place(lounge, "lounge-shade", () => new CylinderGeometry(.084, .126, .123, 18),
    materials.light, [3.617, .153, -.537]);

  box(lounge, materials.wood, [.318, 1.218, .695], [5.051, .042, -.536], .038);
  box(lounge, materials.woodLight, [.322, .036, .683], [5.05, .659, -.536], .013);
  box(lounge, materials.seam, [.322, .018, .673], [5.049, -.129, -.536], .008);
  box(lounge, materials.woodLight, [.034, .472, .303], [4.874, -.324, -.706], .013);
  box(lounge, materials.woodLight, [.034, .472, .303], [4.874, -.324, -.365], .013);
  for (const z of [-.584, -.49]) {
    box(lounge, materials.satin, [.027, .104, .019], [4.848, -.268, z], .007);
  }
  for (const y of [.104, .348]) {
    box(lounge, materials.instrumentFace, [.019, .196, .64], [4.881, y, -.533], .009);
    box(lounge, materials.woodLight, [.113, .025, .64], [4.828, y - .078, -.533], .011);
    box(lounge, materials.light, [.024, .015, .6], [4.777, y + .091, -.533], .005);
    for (const z of [-.745, -.642, -.54, -.437, -.334]) {
      const bottle = Math.abs(z) > .55 ? materials.readout : materials.pillow;
      cylinder(lounge, bottle, .028, .088, [4.842, y - .016, z], 10);
      cylinder(lounge, materials.satin, .014, .031, [4.842, y + .041, z], 10);
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
