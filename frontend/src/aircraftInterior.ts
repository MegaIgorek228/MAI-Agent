import {
  BoxGeometry,
  BufferGeometry,
  CatmullRomCurve3,
  CylinderGeometry,
  ExtrudeGeometry,
  Float32BufferAttribute,
  Group,
  LatheGeometry,
  Material,
  Mesh,
  MeshStandardMaterial,
  Shape,
  Vector2,
  Vector3,
} from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

type Vector = readonly [number, number, number];
type Span = readonly [number, number];

const linerHeight = 1.083;
const linerWidth = 1.097;
const windowHeight: Span = [-.048, .327];
const windowWidth = .386;
const windowCorner = .068;
const windowColumns = 14;

function liningAngle(y: number) {
  return Math.asin(Math.max(-1, Math.min(1, y / linerHeight)));
}

function liningDepth(y: number) {
  return -linerWidth * Math.cos(liningAngle(y));
}

function windowLimits(relativeX: number): Span {
  const cornerReach = Math.max(0, windowCorner - (windowWidth / 2 - Math.abs(relativeX)));
  const inset = windowCorner - Math.sqrt(Math.max(0, windowCorner ** 2 - cornerReach ** 2));
  return [windowHeight[0] + inset, windowHeight[1] - inset];
}

function createSurface(positions: number[], uv: number[], indices: number[], normals?: number[]) {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new Float32BufferAttribute(uv, 2));
  geometry.setIndex(indices);
  if (normals) geometry.setAttribute("normal", new Float32BufferAttribute(normals, 3));
  else geometry.computeVertexNormals();
  return geometry;
}

function liningStrip(span: Span, limits: (x: number) => Span, columns: number) {
  const divisions = 24;
  const positions: number[] = [];
  const normals: number[] = [];
  const uv: number[] = [];
  const indices: number[] = [];
  for (let column = 0; column <= columns; column += 1) {
    const x = span[0] + (span[1] - span[0]) * column / columns;
    const [bottom, top] = limits(x);
    for (let row = 0; row <= divisions; row += 1) {
      const angle = bottom + (top - bottom) * row / divisions;
      const sine = Math.sin(angle);
      const cosine = Math.cos(angle);
      const normalY = -sine / linerHeight;
      const normalZ = cosine / linerWidth;
      const normalLength = Math.hypot(normalY, normalZ);
      positions.push(x, linerHeight * sine, -linerWidth * cosine);
      normals.push(0, normalY / normalLength, normalZ / normalLength);
      uv.push(x, angle);
      if (column < columns && row < divisions) {
        const vertex = column * (divisions + 1) + row;
        const next = vertex + divisions + 1;
        indices.push(vertex, next, next + 1, vertex, next + 1, vertex + 1);
      }
    }
  }
  return createSurface(positions, uv, indices, normals);
}

function windowContour(center: number, scale: number, recess: number) {
  const lower: Vector[] = [];
  const upper: Vector[] = [];
  const middleY = (windowHeight[0] + windowHeight[1]) / 2;
  for (let column = 0; column <= windowColumns; column += 1) {
    const offset = windowWidth * (column / windowColumns - .5);
    const x = center + offset * scale;
    const [bottom, top] = windowLimits(offset).map((y) => middleY + scale * (y - middleY));
    lower.push([x, bottom, liningDepth(bottom) - recess]);
    upper.push([x, top, liningDepth(top) - recess]);
  }
  return lower.concat(upper.reverse());
}

function windowReveal(outer: Vector[], inner: Vector[]) {
  const positions = outer.concat(inner).flat();
  const uv = outer.concat(inner).flatMap(([x, y]) => [x, y]);
  const indices: number[] = [];
  for (let index = 0; index < outer.length; index += 1) {
    const next = (index + 1) % outer.length;
    indices.push(index, next, next + outer.length, index, next + outer.length, index + outer.length);
  }
  return createSurface(positions, uv, indices);
}

function windowGlass(contour: Vector[], x: number, recess: number) {
  const y = (windowHeight[0] + windowHeight[1]) / 2;
  const positions = [x, y, liningDepth(y) - recess, ...contour.flat()];
  const uv = [x, y, ...contour.flatMap(([pointX, pointY]) => [pointX, pointY])];
  const indices: number[] = [];
  for (let index = 0; index < contour.length; index += 1) {
    indices.push(0, index + 1, (index + 1) % contour.length + 1);
  }
  return createSurface(positions, uv, indices);
}

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

  function seatShell(parent: Group, material: Material, size: Vector, position: Vector, radius: number, back: boolean) {
    const key = `seat-shell:${size.join(",")}:${radius}:${back}`;
    return place(parent, key, () => {
      const geometry = new RoundedBoxGeometry(...size, radius >= .03 ? 2 : 1, radius);
      const coordinates = geometry.getAttribute("position");
      const normals = geometry.getAttribute("normal");
      for (let index = 0; index < coordinates.count; index += 1) {
        const x = coordinates.getX(index);
        const y = coordinates.getY(index);
        const z = coordinates.getZ(index);
        const span = z * 2 / size[2];
        let nx = normals.getX(index);
        let ny = normals.getY(index);
        let nz = normals.getZ(index);
        if (back) {
          const height = y * 2 / size[1];
          const shoulders = 1 - .10 * Math.abs(height - .30);
          const lumbar = .032 * Math.exp(-10 * (height + .31) ** 2);
          // Both shell and cushion taper towards the neck and support the lumbar curve.
          coordinates.setXYZ(index, x - lumbar + .028 * span * span + .021 * height * height, y, z * shoulders);
          nz = (nz - nx * .056 * span * 2 / size[2]) / shoulders;
          ny += ((.10 * z * Math.sign(height - .30) * nz) - (20 * lumbar * (height + .31) + .042 * height) * nx)
            * 2 / size[1];
        } else {
          const depth = x * 2 / size[0];
          const taper = .95 + .05 * depth;
          const support = .022 * span * span - .015 * depth * depth;
          coordinates.setXYZ(index, x, y + support, z * taper);
          nz = (nz - ny * .044 * span * 2 / size[2]) / taper;
          nx += (.03 * depth * ny - .05 * z * nz) * 2 / size[0];
        }
        const normalLength = Math.hypot(nx, ny, nz);
        normals.setXYZ(index, nx / normalLength, ny / normalLength, nz / normalLength);
      }
      coordinates.needsUpdate = true;
      normals.needsUpdate = true;
      return geometry;
    }, material, position);
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
    const lowerAngle = liningAngle(floor);
    const upperAngle = 2.10;
    const continuousLimits = (): Span => [lowerAngle, upperAngle];
    const closedPanel = (start: number, end: number) => liningStrip([start, end], continuousLimits, Math.max(3, Math.ceil((end - start) * 12)));
    const strips: BufferGeometry[] = [];

    let start = min;
    for (const x of windows) {
      const span: Span = [x - windowWidth / 2, x + windowWidth / 2];
      strips.push(closedPanel(start, span[0]));
      strips.push(liningStrip(span, (column) => [lowerAngle, liningAngle(windowLimits(column - x)[0])], windowColumns));
      strips.push(liningStrip(span, (column) => [liningAngle(windowLimits(column - x)[1]), upperAngle], windowColumns));
      start = span[1];

      const outer = windowContour(x, 1, -.001);
      const chamfer = windowContour(x, .87, .036);
      const gasket = windowContour(x, .71, .076);
      const pane = windowContour(x, .66, .082);
      place(parent, `window-chamfer:${x}`, () => windowReveal(outer, chamfer), materials.trim, [0, 0, 0]);
      place(parent, `window-reveal:${x}`, () => windowReveal(chamfer, gasket), materials.seam, [0, 0, 0]);
      place(parent, `window-gasket:${x}`, () => windowReveal(gasket, pane), materials.slate, [0, 0, 0]);
      place(parent, `window-glass:${x}`, () => windowGlass(pane, x, .082), materials.window, [0, 0, 0]);
      box(parent, materials.satin, [.046, .014, .014], [x, .275, liningDepth(.275) - .014], .004);
    }
    strips.push(closedPanel(start, max));
    const lining = mergeGeometries(strips);
    for (const strip of strips) strip.dispose();
    if (lining) place(parent, `cabin-lining:${min}:${max}`, () => lining, materials.wall, [0, 0, 0]);
    box(parent, materials.seam, [length - .06, .022, .031], [middle, -.107, liningDepth(-.107) + .008], .009);
    box(parent, materials.slate, [length - .065, .08, .034], [middle, -.50, liningDepth(-.50) + .009], .012);
    box(parent, materials.light, [length - .15, .016, .025], [middle, -.475, liningDepth(-.475) + .018], .006);
  }

  function overhead(parent: Group, min: number, max: number) {
    const middle = (max + min) / 2;
    const length = max - min;
    const compartments = Math.round(length / 1.03);
    const pitch = length / compartments;
    box(parent, materials.seam, [length - .11, .025, .28], [middle, 1.044, 0], .01);
    box(parent, materials.light, [length - .18, .013, .128], [middle, 1.023, 0], .006);
    for (const direction of [-1, 1]) {
      box(parent, materials.seam, [length - .05, .136, .19], [middle, .731, direction * .81], .022);
      for (let index = 0; index < compartments; index += 1) {
        const x = min + (index + .5) * pitch;
        const depth = pitch - .042;
        place(parent, `bin-door:${depth}:${direction}`, () => {
          const section = new Shape();
          section.moveTo(-direction * .85, .692);
          section.lineTo(-direction * .65, .674);
          section.bezierCurveTo(-direction * .578, .667, -direction * .556, .707, -direction * .56, .774);
          section.bezierCurveTo(-direction * .567, .832, -direction * .576, .861, -direction * .62, .894);
          section.quadraticCurveTo(-direction * .692, .889, -direction * .778, .827);
          section.quadraticCurveTo(-direction * .831, .782, -direction * .85, .692);
          section.closePath();
          const geometry = new ExtrudeGeometry(section, {
            depth, curveSegments: 5, bevelEnabled: true, bevelSize: .008, bevelThickness: .009, bevelSegments: 2,
          });
          geometry.rotateY(Math.PI / 2);
          geometry.translate(-depth / 2, 0, 0);
          return geometry;
        }, materials.trim, [x, 0, 0]);
        box(parent, materials.seam, [.16, .024, .018], [x, .717, direction * .562], .005);
        box(parent, materials.satin, [.091, .008, .012], [x, .717, direction * .549], .003);
        box(parent, materials.trim, [.49, .031, .169], [x, .654, direction * .737], .011);
        for (const offset of [-.135, 0, .135]) {
          cylinder(parent, materials.seam, .03, .015, [x + offset, .628, direction * .727], 10);
          cylinder(parent, offset === 0 ? materials.light : materials.satin, .02, .01,
            [x + offset, .618, direction * .727], 10);
        }
      }
      box(parent, materials.light, [length - .10, .016, .035], [middle, .658, direction * .819], .007);
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
      place(seat, "armrest-support", () => {
        const profile = new Shape();
        profile.moveTo(.172, -.349);
        profile.bezierCurveTo(.175, -.258, .176, -.204, .151, -.161);
        profile.quadraticCurveTo(.12, -.134, .073, -.124);
        profile.lineTo(-.233, -.116);
        profile.quadraticCurveTo(-.265, -.115, -.267, -.139);
        profile.quadraticCurveTo(-.268, -.157, -.237, -.166);
        profile.lineTo(.006, -.183);
        profile.bezierCurveTo(.076, -.191, .101, -.241, .094, -.345);
        profile.quadraticCurveTo(.13, -.362, .172, -.349);
        profile.closePath();
        const depth = .048;
        const geometry = new ExtrudeGeometry(profile, {
          depth, curveSegments: 5, bevelEnabled: true, bevelThickness: .005, bevelSize: .005, bevelSegments: 2,
        });
        geometry.translate(0, 0, -depth / 2);
        return geometry;
      }, frame, [0, 0, side * .231]);
      box(seat, padding, [.278, .025, .053], [-.104, -.111, side * .231], .011).rotation.z = -.015;
      const pivot = cylinder(seat, materials.bracket, .031, .018, [.128, -.219, side * .254], 10);
      pivot.rotation.x = Math.PI / 2;
    }

    seatShell(seat, frame, [.525, .087, .435], [-.023, -.388, 0], .034, false);
    seatShell(seat, padding, [.517, .106, .396], [-.064, -.331, 0], .045, false);
    seatShell(seat, insert, [.435, .038, .302], [-.082, -.282, 0], .017, false);
    // The cabin faces negative x, so the positive-x backs describe the recline.
    seatShell(seat, frame, [.102, .674, .421], [.231, -.045, 0], .044, true).rotation.z = -.182;
    seatShell(seat, padding, [.112, .604, .377], [.159, -.068, 0], .049, true).rotation.z = -.182;
    seatShell(seat, insert, [.052, .48, .308], [.088, -.078, 0], .023, true).rotation.z = -.182;
    seatShell(seat, insert, [.125, .114, .319], [.17, .241, 0], .049, true).rotation.z = -.182;
    for (const side of [-1, 1]) {
      seatShell(seat, padding, [.408, .049, .063], [-.065, -.267, side * .153], .021, false);
      seatShell(seat, padding, [.079, .461, .061], [.099, -.066, side * .127], .022, true).rotation.z = -.182;
      if (!pilot) {
        seatShell(seat, materials.fabricSeam, [.012, .321, .014], [.063, -.067, side * .148], .004, true)
          .rotation.z = -.182;
      }
      box(seat, pilot ? materials.vinyl : materials.cushion, [.19, .018, .046], [-.054, -.227, side * .081], .007)
        .rotation.y = side * .68;
    }
    box(seat, materials.satin, [.059, .021, .061], [.012, -.225, .039], .007);
    box(seat, pilot ? materials.caution : materials.slate, [.026, .012, .033], [-.018, -.215, .039], .002);

    if (pilot) return;
    box(seat, materials.seam, [.024, .247, .32], [.279, -.054, 0], .014).rotation.z = -.182;
    box(seat, materials.trim, [.029, .213, .283], [.293, -.061, 0], .011).rotation.z = -.182;
    box(seat, materials.slate, [.019, .031, .061], [.314, .048, 0], .007).rotation.z = -.182;
    box(seat, materials.bracket, [.023, .017, .053], [.329, .049, 0], .005).rotation.z = -.182;
    for (const hinge of [-.103, .103]) {
      const pin = cylinder(seat, materials.bracket, .018, .055, [.283, -.153, hinge], 10);
      pin.rotation.x = Math.PI / 2;
    }
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
  deck(cabin, -5.27, 1.103, 2.137, materials.deck);
  // The entry sill meets the deck and the stair hinge without protruding through the closed skin.
  box(cabin, materials.satin, [.715, .018, .171], [-4.955, floor + .011, 1.0435], .006);
  for (const z of [1.08, 1.113]) {
    box(cabin, materials.slate, [.655, .008, .017], [-4.955, floor + .024, z], .002);
  }
  box(cabin, materials.runner, [6.18, .014, .51], [-2.09, floor + .002, .014], .005);
  for (const z of [-.234, .262]) {
    box(cabin, materials.carpetEdge, [6.13, .008, .023], [-2.09, floor + .011, z], .002);
  }
  sidewall(cabin, -5.15, 1.02, [-4.55, -3.7, -2.85, -2, -1.15, -.30, .55]);
  overhead(cabin, -5.04, .93);
  trimPartition(cabin, 1.04);

  const rows = [-3.45, -2.48, -1.56, -.642, .279];
  const trackStart = -4.45;
  const trackEnd = .81;
  const trackLength = trackEnd - trackStart;
  const trackCenter = (trackStart + trackEnd) / 2;
  for (const z of [-.78, -.449, .408, .747]) {
    box(cabin, materials.satin, [trackLength, .019, .045], [trackCenter, floor + .01, z], .004);
    box(cabin, materials.slate, [trackLength - .06, .011, .016], [trackCenter, floor + .022, z], .002);
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

    box(furniture, materials.sofa, [width - .145, .086, .474], [0, -.452, -.017], .031);
    for (const side of [-1, 1]) {
      for (const edge of [-1, 1]) {
        const leg = place(furniture, "lounge-seat-leg", () => new CylinderGeometry(.022, .013, .086, 10),
          materials.wood, [side * (width / 2 - .108), floor + .043, edge * .192]);
        leg.rotation.set(edge * .13, 0, side * .16);
      }
    }

    const side = width / 2 - .08;
    seatShell(furniture, materials.sofa, [.576, .153, width - .04], [0, -.394, -.014], .054, false)
      .rotation.y = Math.PI / 2;
    place(furniture, `lounge-wrap:${width}`, () => {
      const route = new CatmullRomCurve3([
        new Vector3(-side, -.255, .221),
        new Vector3(-side, -.241, .002),
        new Vector3(-side + .047, -.176, -.207),
        new Vector3(-side * .54, -.132, -.276),
        new Vector3(0, -.125, -.288),
        new Vector3(side * .54, -.132, -.276),
        new Vector3(side - .047, -.176, -.207),
        new Vector3(side, -.241, .002),
        new Vector3(side, -.255, .221),
      ]);
      const rings = 50;
      const samples = 16;
      const positions: number[] = [];
      const uv: number[] = [];
      const indices: number[] = [];
      for (let ring = 0; ring <= rings; ring += 1) {
        const progress = ring / rings;
        const point = route.getPointAt(progress);
        const tangent = route.getTangentAt(progress);
        const bearing = Math.hypot(tangent.x, tangent.z);
        const cap = Math.sqrt(Math.min(1, Math.max(.001, progress * 16), Math.max(.001, (1 - progress) * 16)));
        const backRise = Math.max(0, 1 - Math.abs(progress - .5) * 3.45);
        for (let sample = 0; sample <= samples; sample += 1) {
          const angle = sample / samples * Math.PI * 2;
          const offset = .078 * cap * Math.cos(angle);
          positions.push(point.x + offset * tangent.z / bearing,
            point.y + Math.sin(angle) * cap * (.136 + .083 * backRise),
            point.z - offset * tangent.x / bearing);
          uv.push(progress, sample / samples);
          if (ring < rings && sample < samples) {
            const vertex = ring * (samples + 1) + sample;
            const next = vertex + samples + 1;
            indices.push(vertex, vertex + 1, next, vertex + 1, next + 1, next);
          }
        }
      }
      return createSurface(positions, uv, indices);
    }, materials.sofa, [0, 0, 0]);
    const seats = double ? [-.235, .235] : [0];
    for (const offset of seats) {
      const padWidth = double ? .455 : width - .215;
      seatShell(furniture, materials.sofaInset, [.426, .102, padWidth], [offset, -.299, .041], .045, false)
        .rotation.y = Math.PI / 2;
      seatShell(furniture, materials.sofaInset, [.119, .356, padWidth], [offset, -.129, -.164], .047, true)
        .rotation.set(-.106, Math.PI / 2, 0);
    }
    seatShell(furniture, materials.pillow, [.102, .21, .19], [width / 2 - .193, -.179, -.08], .043, true)
      .rotation.set(-.18, Math.PI / 2 - .12, -.09);
    if (double) {
      seatShell(furniture, materials.fabricSeam, [.091, .166, .199], [-width / 2 + .204, -.183, -.078], .039, true)
        .rotation.set(-.21, Math.PI / 2 + .12, .12);
    }
  }

  loungeSeat(1.72, .52, .698, Math.PI / 2);
  loungeSeat(4.19, -.626, 1.21, 0, true);
  loungeSeat(3.15, -.528, .68, .37);
  const tableApron = cylinder(lounge, materials.wood, .365, .038, [2.77, -.309, .283], 26);
  tableApron.scale.z = .73;
  const table = place(lounge, "lounge-table-top", () => new LatheGeometry([
    new Vector2(0, -.02), new Vector2(.377, -.02), new Vector2(.4, -.016),
    new Vector2(.419, -.009), new Vector2(.426, .006), new Vector2(.421, .016),
    new Vector2(.408, .021), new Vector2(0, .021),
  ], 36), materials.woodLight, [2.77, -.28, .283]);
  table.scale.z = .73;
  for (const [x, z] of [[2.53, .269], [2.99, .184], [2.94, .427]]) {
    const leg = place(lounge, "lounge-table-leg", () => new CylinderGeometry(.026, .016, .247, 12),
      materials.wood, [x, -.435, z]);
    leg.rotation.set((z - .283) * .75, 0, -(x - 2.77) * .65);
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
