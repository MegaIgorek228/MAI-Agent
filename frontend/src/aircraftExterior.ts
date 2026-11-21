import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

type Station = { x: number; ry: number; rz: number; y: number };
type Span = readonly [number, number];

const stations: Station[] = [
  { x: -10, ry: .025, rz: .028, y: -.28 },
  { x: -9.83, ry: .27, rz: .28, y: -.23 },
  { x: -9.42, ry: .57, rz: .55, y: -.16 },
  { x: -8.8, ry: .91, rz: .86, y: -.03 },
  { x: -7.95, ry: 1.17, rz: 1.12, y: .035 },
  { x: -6.55, ry: 1.28, rz: 1.27, y: 0 },
  { x: 4.85, ry: 1.28, rz: 1.27, y: 0 },
  { x: 5.55, ry: 1.24, rz: 1.23, y: .02 },
  { x: 6.81, ry: 1.06, rz: 1.07, y: .12 },
  { x: 8.08, ry: .73, rz: .79, y: .28 },
  { x: 9.2, ry: .4, rz: .45, y: .44 },
  { x: 9.77, ry: .19, rz: .22, y: .53 },
  { x: 10, ry: .025, rz: .04, y: .54 },
];
const openings: Span[] = [[-7.85, -5.47], [-5.2, .88], [1.08, 5.35]];
const fullRing: Span = [-Math.PI / 2, 3 * Math.PI / 2];

function hullStation(x: number): Station {
  const lastIndex = stations.length - 1;
  if (x <= stations[0].x) return stations[0];
  if (x >= stations[lastIndex].x) return stations[lastIndex];

  const leftIndex = stations.findIndex((station) => x < station.x) - 1;
  const left = stations[leftIndex];
  const right = stations[leftIndex + 1];
  const span = right.x - left.x;
  const t = (x - left.x) / span;
  const previous = stations[Math.max(0, leftIndex - 1)];
  const following = stations[Math.min(lastIndex, leftIndex + 2)];
  const interpolate = (key: "ry" | "rz" | "y") => {
    const slope = (right[key] - left[key]) / span;
    const incoming = (right[key] - previous[key]) / (right.x - previous.x);
    const outgoing = (following[key] - left[key]) / (following.x - left.x);
    const slopeAt = (candidate: number) => Math.sign(candidate) === Math.sign(slope)
      ? Math.sign(slope) * Math.min(Math.abs(candidate), Math.abs(slope) * 2.5) : 0;

    return (2 * t - 3) * t * t * left[key] + left[key]
      + (t - 1) ** 2 * t * span * slopeAt(incoming)
      + (3 - 2 * t) * t * t * right[key]
      + (t - 1) * t * t * span * slopeAt(outgoing);
  };

  return { x, ry: interpolate("ry"), rz: interpolate("rz"), y: interpolate("y") };
}

function yAngle(station: Station, y: number) {
  return Math.asin(THREE.MathUtils.clamp((y - station.y) / station.ry, -.997, .997));
}

function projectedZ(x: number, y: number, side: number, offset: number) {
  const station = hullStation(x);
  return side * (station.rz * Math.cos(yAngle(station, y)) + offset);
}

function openingLimits([left, right]: Span, x: number): Span {
  const radius = .14;
  const shoulder = Math.max(0, radius - Math.min(x - left, right - x));
  const corner = radius - Math.sqrt(Math.max(0, radius * radius - shoulder * shoulder));
  return [-.58 + corner, .93 - corner];
}

function hullPatch(span: Span, angleSpan: (station: Station) => Span, radialSteps: number, offset = 0) {
  const [left, right] = span;
  const columns = Math.max(6, Math.ceil((right - left) * 14));
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  const normal = new THREE.Vector3();
  const rowSize = radialSteps + 1;

  for (let column = 0; column <= columns; column += 1) {
    const x = THREE.MathUtils.lerp(left, right, column / columns);
    const station = hullStation(x);
    const before = hullStation(x - .002);
    const after = hullStation(x + .002);
    const dx = Math.max(.002, after.x - before.x);
    const [start, end] = angleSpan(station);

    for (let ring = 0; ring <= radialSteps; ring += 1) {
      const theta = THREE.MathUtils.lerp(start, end, ring / radialSteps);
      const sin = Math.sin(theta);
      const cos = Math.cos(theta);
      const slopeY = ((after.ry - before.ry) * sin + after.y - before.y) / dx;
      const slopeZ = (after.rz - before.rz) * cos / dx;
      normal.set(-slopeY * station.rz * sin - slopeZ * station.ry * cos, station.rz * sin, station.ry * cos).normalize();
      positions.push(x + normal.x * offset, station.y + station.ry * sin + normal.y * offset, station.rz * cos + normal.z * offset);
      normals.push(normal.x, normal.y, normal.z);
      if (column === columns || ring === radialSteps) continue;
      const index = column * rowSize + ring;
      indices.push(index, index + rowSize, index + rowSize + 1, index, index + rowSize + 1, index + 1);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  geometry.setIndex(indices);
  return geometry;
}

function addBatch(group: THREE.Group, parts: THREE.BufferGeometry[], material: THREE.Material) {
  if (parts.length === 0) return;
  const geometry = mergeGeometries(parts);
  parts.forEach((part) => part.dispose());
  if (geometry) group.add(new THREE.Mesh(geometry, material));
}

function projectedShape(shape: THREE.Shape, side: number, offset: number) {
  const geometry = new THREE.ShapeGeometry(shape, 6);
  const vertices = geometry.getAttribute("position");
  for (let i = 0; i < vertices.count; i += 1) {
    vertices.setZ(i, projectedZ(vertices.getX(i), vertices.getY(i), side, offset));
  }
  geometry.computeVertexNormals();
  return geometry;
}

function ovalWindow(x: number, y: number, width: number, height: number) {
  const shape = new THREE.Shape();
  shape.absellipse(x, y, width / 2, height / 2, 0, 2 * Math.PI, false, 0);
  return shape;
}

type FoilStation = { lead: number; tail: number; span: number; height: number; thick: number };

function foilGeometry(stations: FoilStation[], vertical = false) {
  const radialSteps = 24;
  const positions: number[] = [];
  const indices: number[] = [];

  stations.forEach((station, row) => {
    for (let angle = 0; angle <= radialSteps; angle += 1) {
      const theta = 2 * Math.PI * angle / radialSteps;
      const x = THREE.MathUtils.lerp(station.lead, station.tail, (1 - Math.cos(theta)) / 2);
      const section = station.height + station.thick * Math.sin(theta);
      positions.push(x, vertical ? station.span : section, vertical ? section : station.span);
      if (row === stations.length - 1 || angle === radialSteps) continue;
      const first = row * (radialSteps + 1) + angle;
      const next = first + radialSteps + 1;
      if (vertical) {
        indices.push(first, first + 1, next + 1, first, next + 1, next);
      } else {
        indices.push(first, next, next + 1, first, next + 1, first + 1);
      }
    }
  });
  for (const end of [0, stations.length - 1]) {
    const first = end * (radialSteps + 1);
    const reverse = (end === 0) === vertical;
    for (let angle = 1; angle < radialSteps - 1; angle += 1) {
      const outer = reverse ? [first + angle + 1, first + angle] : [first + angle, first + angle + 1];
      indices.push(first, ...outer);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function addFoilPair(group: THREE.Group, stations: FoilStation[], material: THREE.Material) {
  const geometry = foilGeometry(stations);
  for (const side of [1, -1]) {
    const foil = new THREE.Mesh(geometry, material);
    foil.scale.z = side;
    group.add(foil);
  }
}

function finPaint(stations: FoilStation[], begin: number, end: number) {
  const positions: number[] = [];
  const indices: number[] = [];
  const rowSize = 6;
  for (const side of [1, -1]) {
    const base = positions.length / 3;
    stations.forEach((station, row) => {
      for (let column = 0; column < rowSize; column += 1) {
        const u = THREE.MathUtils.lerp(begin, end, column / (rowSize - 1));
        const z = side * (station.thick * Math.sqrt(4 * u * (1 - u)) + .014);
        positions.push(THREE.MathUtils.lerp(station.lead, station.tail, u), station.span, z);
        if (row === stations.length - 1 || column === rowSize - 1) continue;
        const index = base + row * rowSize + column;
        indices.push(index, index + 1, index + rowSize + 1, index, index + rowSize + 1, index + rowSize);
      }
    });
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function curveLine(points: THREE.Vector3[], thickness: number, closed = false) {
  const curve = new THREE.CatmullRomCurve3(points, closed, "centripetal");
  return new THREE.TubeGeometry(curve, Math.max(24, points.length * 2), thickness, 6, closed);
}

function openingRim(span: Span) {
  const [left, right] = span;
  const points: THREE.Vector3[] = [];
  for (const direction of [1, -1]) {
    for (let step = 0; step <= 36; step += 1) {
      const x = THREE.MathUtils.lerp(left, right, direction === 1 ? step / 36 : 1 - step / 36);
      const [bottom, top] = openingLimits(span, x);
      const y = direction === 1 ? bottom : top;
      points.push(new THREE.Vector3(x, y, projectedZ(x, y, 1, -.017)));
    }
  }
  return curveLine(points, .018, true);
}

function engineLathe(profile: [number, number][], material: THREE.Material) {
  const geometry = new THREE.LatheGeometry(profile.map(([x, r]) => new THREE.Vector2(r, x)), 40);
  geometry.rotateZ(-Math.PI / 2);
  return new THREE.Mesh(geometry, material);
}

function engine(hull: THREE.Material, lip: THREE.Material, housing: THREE.Material, bladesMaterial: THREE.Material) {
  const group = new THREE.Group();
  group.add(
    engineLathe([[-1.13, .51], [-1.19, .55], [-1.12, .62], [-.99, .662], [-.58, .69], [.02, .66], [.53, .59], [.79, .43], [.91, .35]], hull),
    engineLathe([[-1.13, .51], [-1.19, .55], [-1.12, .62], [-1.04, .647]], lip),
    engineLathe([[-1.13, .51], [-.97, .49], [-.73, .45], [-.62, .02]], housing),
    engineLathe([[.77, .43], [.87, .365], [1.01, .34], [1.015, .285], [.87, .274]], housing),
    engineLathe([[-1.04, .012], [-1.025, .085], [-.965, .132], [-.76, .144]], lip),
  );

  const blades: THREE.BufferGeometry[] = [];
  for (let blade = 0; blade < 19; blade += 1) {
    const theta = 2 * Math.PI * blade / 19;
    const radial = (r: number, offset: number) => [Math.sin(theta + offset) * r, Math.cos(theta + offset) * r];
    const inner = radial(.12, .03);
    const outer = radial(.459, .21);
    const swept = radial(.455, .31);
    const trailing = radial(.13, .20);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute([
      -.845, ...inner, -.88, ...outer, -.832, ...swept, -.81, ...trailing,
    ], 3));
    geometry.setIndex([0, 1, 2, 0, 2, 3]);
    geometry.computeVertexNormals();
    blades.push(geometry);
  }
  addBatch(group, blades, bladesMaterial);
  return group;
}

export function createAircraftExterior(): { body: THREE.Group; panels: THREE.Group } {
  const body = new THREE.Group();
  const panels = new THREE.Group();
  const ivory = new THREE.MeshStandardMaterial({ color: "#e9e8e1", roughness: .43, metalness: .19, side: THREE.DoubleSide });
  const silver = new THREE.MeshStandardMaterial({ color: "#c0c5c4", roughness: .46, metalness: .44, side: THREE.DoubleSide });
  const slate = new THREE.MeshStandardMaterial({ color: "#384d60", roughness: .48, metalness: .19, side: THREE.DoubleSide });
  const seal = new THREE.MeshStandardMaterial({ color: "#616d72", roughness: .55, metalness: .24, side: THREE.DoubleSide });
  const glass = new THREE.MeshStandardMaterial({ color: "#263b49", roughness: .23, metalness: .38, side: THREE.DoubleSide });
  const rotorMetal = new THREE.MeshStandardMaterial({ color: "#7f8789", roughness: .45, metalness: .55, side: THREE.DoubleSide });
  const intakeDark = new THREE.MeshStandardMaterial({ color: "#262b2d", roughness: .74, metalness: .19, side: THREE.DoubleSide });
  const spans: { range: Span; opening: boolean }[] = [];
  let boundary = -10;
  for (const opening of openings) {
    spans.push({ range: [boundary, opening[0]], opening: false }, { range: opening, opening: true });
    boundary = opening[1];
  }
  spans.push({ range: [boundary, 10], opening: false });

  const shells: THREE.BufferGeometry[] = [];
  const covers: THREE.BufferGeometry[] = [];
  const bodyPaint: THREE.BufferGeometry[] = [];
  const panelPaint: THREE.BufferGeometry[] = [];
  for (const { range, opening } of spans) {
    const aperture = (station: Station): Span => {
      const [low, high] = openingLimits(range, station.x);
      return [yAngle(station, low), yAngle(station, high)];
    };
    if (opening) {
      covers.push(hullPatch(range, aperture, 24));
      shells.push(hullPatch(range, (station) => {
        const [low, high] = aperture(station);
        return [high, low + 2 * Math.PI];
      }, 50));
    } else {
      shells.push(hullPatch(range, () => fullRing, 72));
    }

    const clipped: Span = [Math.max(range[0], -9.47), Math.min(range[1], 9.18)];
    if (clipped[0] >= clipped[1]) continue;
    for (const [low, high] of [[-.382, -.283], [-.238, -.21]]) {
      (opening ? panelPaint : bodyPaint).push(hullPatch(clipped, () => [low, high], 3, .008));
      bodyPaint.push(hullPatch(clipped, () => [Math.PI - high, Math.PI - low], 3, .008));
    }
  }
  addBatch(body, shells, ivory);
  addBatch(panels, covers, ivory);
  addBatch(body, bodyPaint, slate);
  addBatch(panels, panelPaint, slate);
  addBatch(body, openings.map(openingRim), silver);

  const bodyWindows: THREE.BufferGeometry[] = [];
  const panelWindows: THREE.BufferGeometry[] = [];
  const bodySeals: THREE.BufferGeometry[] = [];
  const panelSeals: THREE.BufferGeometry[] = [];
  for (const side of [1, -1]) {
    for (let x = -5.02; x < 6.52; x += .46) {
      if (x > .61 && x < 1.28) continue;
      const covered = side === 1 && openings.some(([left, right]) => x > left && x < right);
      (covered ? panelSeals : bodySeals).push(projectedShape(ovalWindow(x, .27, .237, .343), side, .014));
      (covered ? panelWindows : bodyWindows).push(projectedShape(ovalWindow(x, .27, .20, .304), side, .027));
    }
    const windshield: [number, number][][] = [
      [[-9.17, .14], [-8.90, .54], [-8.60, .57], [-8.75, .165]],
      [[-8.68, .156], [-8.53, .57], [-8.20, .562], [-8.20, .16]],
      [[-8.13, .151], [-8.13, .55], [-7.92, .54], [-7.91, .16]],
    ];
    windshield.forEach((points) => {
      const polygon = new THREE.Shape(points.map(([x, y]) => new THREE.Vector2(x, y)));
      bodyWindows.push(projectedShape(polygon, side, .024));
    });
  }
  addBatch(body, bodySeals, seal);
  addBatch(panels, panelSeals, seal);
  addBatch(body, bodyWindows, glass);
  addBatch(panels, panelWindows, glass);

  const wingStations: FoilStation[] = [
    { lead: -2.54, tail: 2.74, span: .85, height: -.72, thick: .23 },
    { lead: -1.84, tail: 2.63, span: 1.37, height: -.74, thick: .19 },
    { lead: -.7, tail: 2.95, span: 2.95, height: -.61, thick: .15 },
    { lead: 1.18, tail: 3.55, span: 5.22, height: -.38, thick: .095 },
    { lead: 2.38, tail: 3.88, span: 6.72, height: -.17, thick: .047 },
    { lead: 2.83, tail: 3.69, span: 7.05, height: -.08, thick: .01 },
  ];
  addFoilPair(body, wingStations, silver);
  addFoilPair(body, [
    { lead: 6.8, tail: 9.46, span: .30, height: .48, thick: .13 },
    { lead: 7.3, tail: 9.37, span: 1.2, height: .53, thick: .10 },
    { lead: 8.49, tail: 9.85, span: 2.85, height: .7, thick: .068 },
    { lead: 8.84, tail: 9.84, span: 3.2, height: .74, thick: .02 },
  ], silver);

  const tail: FoilStation[] = [
    { lead: 5.82, tail: 9.83, span: .64, height: 0, thick: .19 },
    { lead: 6.44, tail: 9.72, span: 1.26, height: 0, thick: .17 },
    { lead: 7.65, tail: 9.69, span: 2.53, height: 0, thick: .12 },
    { lead: 8.49, tail: 9.78, span: 3.62, height: 0, thick: .073 },
    { lead: 8.77, tail: 9.75, span: 3.88, height: 0, thick: .025 },
  ];
  body.add(new THREE.Mesh(foilGeometry(tail, true), ivory));
  body.add(new THREE.Mesh(finPaint(tail, .81, .992), slate), new THREE.Mesh(finPaint(tail, .747, .775), slate));

  for (const side of [1, -1]) {
    const turbofan = engine(ivory, silver, intakeDark, rotorMetal);
    turbofan.position.set(-.9, -1.47, side * 2.78);
    body.add(turbofan);

    const pylon = new THREE.Mesh(foilGeometry([
      { lead: -1.32, tail: .57, span: -1.17, height: side * 2.78, thick: .13 },
      { lead: -1.01, tail: .69, span: -.64, height: side * 2.65, thick: .15 },
    ], true), silver);
    body.add(pylon);
  }
  return { body, panels };
}
