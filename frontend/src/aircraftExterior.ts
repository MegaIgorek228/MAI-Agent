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
  const tessellation = new THREE.ShapeGeometry(shape, 6);
  const vertices = tessellation.getAttribute("position");
  const indices = tessellation.getIndex()!;
  const positions: number[] = [];
  const triangles: number[] = [];
  const a = new THREE.Vector2();
  const b = new THREE.Vector2();
  const c = new THREE.Vector2();
  const point = new THREE.Vector2();
  tessellation.computeBoundingBox();
  const bounds = tessellation.boundingBox!;
  const barrel = bounds.min.x >= -6.60 && bounds.max.x <= 4.85;
  const longitudinal = (bounds.max.x - bounds.min.x) * (barrel ? .2 : 1);
  const steps = Math.max(1, Math.ceil(Math.max(longitudinal, bounds.max.y - bounds.min.y) / .12));

  for (let index = 0; index < indices.count; index += 3) {
    const corners = [a, b, c];
    corners.forEach((vertex, i) => {
      const source = indices.getX(index + i);
      vertex.set(vertices.getX(source), vertices.getY(source));
    });
    const from = positions.length / 3;
    const rowStart = (row: number) => from + row * (steps + 1) - row * (row - 1) / 2;
    for (let row = 0; row <= steps; row += 1) {
      for (let column = 0; column <= steps - row; column += 1) {
        point.copy(a).multiplyScalar(1 - (row + column) / steps)
          .addScaledVector(b, row / steps).addScaledVector(c, column / steps);
        positions.push(point.x, point.y, projectedZ(point.x, point.y, side, offset));
        if (row + column === steps) continue;
        const start = rowStart(row) + column;
        const next = rowStart(row + 1) + column;
        triangles.push(start, next, start + 1);
        if (row + column < steps - 1) triangles.push(start + 1, next, next + 1);
      }
    }
  }
  tessellation.dispose();
  if (side < 0) {
    for (let index = 0; index < triangles.length; index += 3) {
      [triangles[index + 1], triangles[index + 2]] = [triangles[index + 2], triangles[index + 1]];
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(triangles);
  geometry.computeVertexNormals();
  return geometry;
}

function roundedPanel(x: number, y: number, width: number, height: number, radius: number) {
  const left = x - width / 2;
  const right = x + width / 2;
  const bottom = y - height / 2;
  const top = y + height / 2;
  const shape = new THREE.Shape();
  shape.moveTo(left + radius, bottom);
  shape.lineTo(right - radius, bottom);
  shape.quadraticCurveTo(right, bottom, right, bottom + radius);
  shape.lineTo(right, top - radius);
  shape.quadraticCurveTo(right, top, right - radius, top);
  shape.lineTo(left + radius, top);
  shape.quadraticCurveTo(left, top, left, top - radius);
  shape.lineTo(left, bottom + radius);
  shape.quadraticCurveTo(left, bottom, left + radius, bottom);
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

function skinOutline(shape: THREE.Shape, side: number, width: number) {
  const points = shape.getPoints(8).slice(0, -1);
  return curveLine(points.map(({ x, y }) => new THREE.Vector3(x, y, projectedZ(x, y, side, .013))), width, true);
}

function openingRim(span: Span) {
  const [left, right] = span;
  const points: THREE.Vector3[] = [];
  for (const direction of [1, -1]) {
    for (let step = 0; step <= 36; step += 1) {
      const x = THREE.MathUtils.lerp(left, right, direction === 1 ? step / 36 : 1 - step / 36);
      const [bottom, top] = openingLimits(span, x);
      const y = direction === 1 ? bottom : top;
      points.push(new THREE.Vector3(x, y, projectedZ(x, y, 1, -.037)));
    }
  }
  return curveLine(points, .029, true);
}

function foilSurface(stations: FoilStation[], span: number, chord: number, side: number, offset: number, vertical = false) {
  const endIndex = stations.findIndex((station) => station.span >= span);
  const end = stations[endIndex < 0 ? stations.length - 1 : Math.max(1, endIndex)];
  const begin = stations[stations.indexOf(end) - 1];
  const mix = THREE.MathUtils.clamp((span - begin.span) / (end.span - begin.span), 0, 1);
  const lead = THREE.MathUtils.lerp(begin.lead, end.lead, mix);
  const tail = THREE.MathUtils.lerp(begin.tail, end.tail, mix);
  const x = THREE.MathUtils.lerp(lead, tail, chord);
  const thickness = THREE.MathUtils.lerp(begin.thick, end.thick, mix);
  const height = THREE.MathUtils.lerp(begin.height, end.height, mix) + thickness * Math.sqrt(4 * chord * (1 - chord)) + offset;
  return new THREE.Vector3(x, vertical ? span : height, vertical ? side * height : side * span);
}

function foilPatch(stations: FoilStation[], range: Span, chord: Span, side: number) {
  const rows = Math.ceil((range[1] - range[0]) * 13);
  const columns = 5;
  const stride = columns + 1;
  const positions: number[] = [];
  const indices: number[] = [];
  for (let row = 0; row <= rows; row += 1) {
    const span = THREE.MathUtils.lerp(...range, row / rows);
    for (let column = 0; column <= columns; column += 1) {
      const point = foilSurface(stations, span, THREE.MathUtils.lerp(...chord, column / columns), side, .008);
      positions.push(point.x, point.y, point.z);
      if (row === rows || column === columns) continue;
      const first = row * stride + column;
      if (side > 0) indices.push(first, first + stride, first + stride + 1, first, first + stride + 1, first + 1);
      else indices.push(first, first + 1, first + stride + 1, first, first + stride + 1, first + stride);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function foilOutline(stations: FoilStation[], range: Span, chord: Span, side: number) {
  const points: THREE.Vector3[] = [];
  for (const position of [0, 1]) {
    for (let step = 0; step <= 14; step += 1) {
      const span = THREE.MathUtils.lerp(...range, position === 0 ? step / 14 : 1 - step / 14);
      points.push(foilSurface(stations, span, chord[position], side, .011));
    }
    const end = range[1 - position];
    for (let step = 1; step < 5; step += 1) {
      const u = THREE.MathUtils.lerp(chord[position], chord[1 - position], step / 5);
      points.push(foilSurface(stations, end, u, side, .011));
    }
  }
  return curveLine(points, .006, true);
}

function tailHinge(stations: FoilStation[], side: number) {
  const points = Array.from({ length: 19 }, (_, i) => {
    const span = THREE.MathUtils.lerp(1.19, 3.79, i / 18);
    return foilSurface(stations, span, .755, side, .008, true);
  });
  return curveLine(points, .009);
}

function engineLathe(profile: [number, number][], material: THREE.Material) {
  const geometry = new THREE.LatheGeometry(profile.map(([x, r]) => new THREE.Vector2(r, x)), 40);
  geometry.rotateZ(-Math.PI / 2);
  return new THREE.Mesh(geometry, material);
}

function engine(hull: THREE.Material, lip: THREE.Material, housing: THREE.Material, bladesMaterial: THREE.Material) {
  const group = new THREE.Group();
  group.add(
    engineLathe([[-1.18, .52], [-1.19, .56], [-1.12, .621], [-.99, .66], [-.71, .686], [-.48, .69], [.02, .665], [.47, .601], [.71, .496], [.84, .396], [.9, .351]], hull),
    engineLathe([[-1.18, .52], [-1.193, .53], [-1.195, .558], [-1.16, .591], [-1.12, .625], [-1.075, .638]], lip),
    engineLathe([[-1.183, .523], [-1.06, .508], [-.86, .474], [-.68, .446], [-.62, .02]], housing),
    engineLathe([[.71, .495], [.78, .453], [.833, .401]], lip),
    engineLathe([[.833, .40], [.89, .365], [.99, .341], [1.001, .302], [.967, .283], [.88, .272]], housing),
    engineLathe([[.895, .353], [.976, .346], [1, .336], [1.01, .318]], bladesMaterial),
    engineLathe([[.82, .231], [1.02, .20], [1.08, .126], [1.105, .012]], bladesMaterial),
    engineLathe([[-1.057, .01], [-1.028, .073], [-.978, .113], [-.928, .132], [-.76, .144]], lip),
  );

  const blades: THREE.BufferGeometry[] = [];
  const bladeCount = 22;
  for (let blade = 0; blade < bladeCount; blade += 1) {
    const theta = 2 * Math.PI * blade / bladeCount;
    const positions: number[] = [];
    const indices: number[] = [];
    for (let row = 0; row <= 5; row += 1) {
      const t = row / 5;
      const radius = THREE.MathUtils.lerp(.118, .469, t);
      const twist = .318 * t ** 1.5;
      for (let column = 0; column <= 3; column += 1) {
        const u = column / 3;
        const angle = theta + twist + u * THREE.MathUtils.lerp(.228, .117, t);
        const x = -.918 + .055 * t - .021 * Math.sin(u * Math.PI) + u * (.066 - .032 * t);
        positions.push(x, Math.sin(angle) * radius, Math.cos(angle) * radius);
        if (row === 5 || column === 3) continue;
        const first = row * 4 + column;
        indices.push(first, first + 4, first + 5, first, first + 5, first + 1);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    blades.push(geometry);
  }
  addBatch(group, blades, bladesMaterial);
  const nacelleJoints = [
    engineLathe([[-.725, .684], [-.718, .687], [-.711, .687]], bladesMaterial),
    engineLathe([[.444, .6072], [.453, .6066], [.463, .6052]], bladesMaterial),
  ];
  const door = Array.from({ length: 19 }, (_, index) => {
    const t = index / 18;
    const radial = .675 + .014 * Math.sin(t * Math.PI) - .062 * t ** 3;
    return new THREE.Vector3(THREE.MathUtils.lerp(-.7, .44, t), -.079, radial);
  });
  group.add(...nacelleJoints, new THREE.Mesh(curveLine(door, .004), bladesMaterial));
  return group;
}

export function createAircraftExterior(): { body: THREE.Group; panels: THREE.Group } {
  const body = new THREE.Group();
  body.name = "Fuselage, flight surfaces and propulsion";
  const panels = new THREE.Group();
  panels.name = "Removable exterior panels";
  const ivory = new THREE.MeshStandardMaterial({ color: "#dddcd6", roughness: .38, metalness: .24, side: THREE.DoubleSide });
  const silver = new THREE.MeshStandardMaterial({ color: "#a5aeb3", roughness: .43, metalness: .48, side: THREE.DoubleSide });
  const flightSurface = new THREE.MeshStandardMaterial({ color: "#bcc3c5", roughness: .56, metalness: .32, side: THREE.DoubleSide });
  const trim = new THREE.MeshStandardMaterial({ color: "#87949a", roughness: .36, metalness: .48, side: THREE.DoubleSide });
  const hatch = new THREE.MeshStandardMaterial({ color: "#d2d1cb", roughness: .43, metalness: .23, side: THREE.DoubleSide });
  const slate = new THREE.MeshStandardMaterial({ color: "#384d60", roughness: .48, metalness: .19, side: THREE.DoubleSide });
  const seal = new THREE.MeshStandardMaterial({ color: "#616d72", roughness: .55, metalness: .24, side: THREE.DoubleSide });
  const glass = new THREE.MeshStandardMaterial({ color: "#213441", roughness: .26, metalness: .33, side: THREE.DoubleSide });
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
  const bodyHatches: THREE.BufferGeometry[] = [];
  const panelHatches: THREE.BufferGeometry[] = [];
  const bodySeams: THREE.BufferGeometry[] = [];
  const panelSeams: THREE.BufferGeometry[] = [];
  for (const side of [1, -1]) {
    const doors = [-6.29, 6.08];
    for (let x = -5.02; x < 6.52; x += .46) {
      if ((x > .61 && x < 1.28) || doors.some((door) => Math.abs(x - door) < .39)) continue;
      const covered = side === 1 && openings.some(([left, right]) => x > left && x < right);
      (covered ? panelSeals : bodySeals).push(projectedShape(roundedPanel(x, .27, .217, .33, .092), side, .013));
      (covered ? panelWindows : bodyWindows).push(projectedShape(roundedPanel(x, .27, .176, .283, .076), side, .022));
    }
    for (const x of doors) {
      const covered = x < 0 && side === 1;
      const door = roundedPanel(x, .15, .58, 1.32, .111);
      const outlines = covered ? panelSeams : bodySeams;
      const glazings = covered ? panelWindows : bodyWindows;
      (covered ? panelHatches : bodyHatches).push(projectedShape(door, side, .009));
      outlines.push(skinOutline(door, side, .0065));
      glazings.push(projectedShape(roundedPanel(x, .40, .115, .175, .047), side, .022));
      (covered ? panelSeals : bodySeals).push(projectedShape(roundedPanel(x + .128, .01, .142, .048, .017), side, .024));
    }
    for (const [x, width] of [[-4.34, 1.26], [3.54, 1.60]]) {
      const cargo = roundedPanel(x, -.853, width, .357, .068);
      bodyHatches.push(projectedShape(cargo, side, .009));
      bodySeams.push(skinOutline(cargo, side, .0065));
      bodySeals.push(projectedShape(roundedPanel(x + width * .23, -.81, .13, .046, .017), side, .019));
    }
    const radome = Array.from({ length: 30 }, (_, i) => {
      const x = -9.25 - (i / 29) * .10;
      const y = THREE.MathUtils.lerp(-.57, .48, i / 29);
      return new THREE.Vector3(x, y, projectedZ(x, y, side, .009));
    });
    bodySeams.push(curveLine(radome, .006));
    const windshield: [number, number][][] = [
      [[-9.17, .14], [-8.90, .54], [-8.60, .57], [-8.75, .165]],
      [[-8.68, .156], [-8.53, .57], [-8.20, .562], [-8.20, .16]],
      [[-8.13, .151], [-8.13, .55], [-7.92, .54], [-7.91, .16]],
    ];
    windshield.forEach((points) => {
      const polygon = new THREE.Shape(points.map(([x, y]) => new THREE.Vector2(x, y)));
      bodyWindows.push(projectedShape(polygon, side, .024));
      const outline = [...points, points[0]].map(([x, y]) => new THREE.Vector3(x, y, projectedZ(x, y, side, .026)));
      bodySeams.push(curveLine(outline, .008));
    });
    const wiper: [number, number][] = [[-8.867, .186], [-8.79, .245], [-8.682, .348], [-8.63, .398]];
    bodySeams.push(curveLine(wiper.map(([x, y]) => new THREE.Vector3(x, y, projectedZ(x, y, side, .033))), .007));
  }
  addBatch(body, bodyHatches, hatch);
  addBatch(panels, panelHatches, hatch);
  addBatch(body, bodySeals, seal);
  addBatch(panels, panelSeals, seal);
  addBatch(body, bodyWindows, glass);
  addBatch(panels, panelWindows, glass);
  addBatch(panels, panelSeams, trim);

  const wingStations: FoilStation[] = [
    { lead: -2.54, tail: 2.74, span: .85, height: -.72, thick: .23 },
    { lead: -1.84, tail: 2.63, span: 1.37, height: -.74, thick: .19 },
    { lead: -.7, tail: 2.95, span: 2.95, height: -.61, thick: .15 },
    { lead: 1.18, tail: 3.55, span: 5.22, height: -.38, thick: .095 },
    { lead: 2.38, tail: 3.88, span: 6.72, height: -.17, thick: .047 },
    { lead: 2.83, tail: 3.69, span: 7.05, height: -.08, thick: .01 },
  ];
  addFoilPair(body, wingStations, silver);
  const stabilizer: FoilStation[] = [
    { lead: 6.8, tail: 9.46, span: .30, height: .48, thick: .13 },
    { lead: 7.3, tail: 9.37, span: 1.2, height: .53, thick: .10 },
    { lead: 8.49, tail: 9.85, span: 2.85, height: .7, thick: .068 },
    { lead: 8.84, tail: 9.84, span: 3.2, height: .74, thick: .02 },
  ];
  addFoilPair(body, stabilizer, silver);
  const surfacePanels: THREE.BufferGeometry[] = [];
  for (const side of [1, -1]) {
    const flaps: Span[] = [[1.44, 2.78], [2.87, 4.69], [4.78, 6.59]];
    for (const span of flaps) {
      surfacePanels.push(foilPatch(wingStations, span, [.748, .981], side));
      bodySeams.push(foilOutline(wingStations, span, [.745, .982], side));
    }
    const spoilers: Span[] = [[2.18, 2.96], [3.02, 3.72], [3.78, 4.45]];
    for (const span of spoilers) bodySeams.push(foilOutline(wingStations, span, [.54, .714], side));
    surfacePanels.push(foilPatch(wingStations, [1.46, 6.8], [.022, .158], side));
    bodySeams.push(foilOutline(stabilizer, [.98, 3.02], [.701, .965], side));
    for (const span of [2.15, 3.95, 5.39]) {
      const center = foilSurface(wingStations, span, .785, side, -.23);
      const fairing = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 8), silver);
      fairing.scale.set(.49, .135, .103);
      fairing.rotation.y = -.125 * side;
      fairing.position.copy(center);
      body.add(fairing);
    }

    const wingletStations: FoilStation[] = [
      { lead: 2.72, tail: 3.72, span: -.095, height: side * 6.98, thick: .078 },
      { lead: 2.92, tail: 3.68, span: .05, height: side * 7.04, thick: .061 },
      { lead: 3.22, tail: 3.66, span: .42, height: side * 7.18, thick: .032 },
      { lead: 3.46, tail: 3.65, span: .60, height: side * 7.22, thick: .012 },
    ];
    body.add(new THREE.Mesh(foilGeometry(wingletStations, true), ivory));
    const navigationLight = new THREE.Mesh(new THREE.SphereGeometry(1, 12, 6), new THREE.MeshStandardMaterial({
      color: side > 0 ? "#af433d" : "#537b66",
      emissive: side > 0 ? "#65291f" : "#1c5a3d",
      emissiveIntensity: .4,
      roughness: .22,
    }));
    navigationLight.scale.set(.082, .043, .056);
    navigationLight.position.set(2.95, .058, side * 7.046);
    body.add(navigationLight);
  }
  addBatch(body, surfacePanels, flightSurface);

  const tail: FoilStation[] = [
    { lead: 5.82, tail: 9.83, span: .64, height: 0, thick: .19 },
    { lead: 6.44, tail: 9.72, span: 1.26, height: 0, thick: .17 },
    { lead: 7.65, tail: 9.69, span: 2.53, height: 0, thick: .12 },
    { lead: 8.49, tail: 9.78, span: 3.62, height: 0, thick: .073 },
    { lead: 8.77, tail: 9.75, span: 3.88, height: 0, thick: .025 },
  ];
  body.add(new THREE.Mesh(foilGeometry(tail, true), ivory));
  body.add(new THREE.Mesh(finPaint(tail, .81, .992), slate), new THREE.Mesh(finPaint(tail, .747, .775), slate));
  for (const side of [1, -1]) bodySeams.push(tailHinge(tail, side));

  const antenna = new THREE.Mesh(foilGeometry([
    { lead: -.7, tail: -.37, span: 1.252, height: 0, thick: .036 },
    { lead: -.59, tail: -.39, span: 1.39, height: 0, thick: .025 },
    { lead: -.47, tail: -.395, span: 1.455, height: 0, thick: .010 },
  ], true), ivory);
  body.add(antenna);
  addBatch(body, bodySeams, trim);

  for (const side of [1, -1]) {
    const turbofan = engine(ivory, silver, intakeDark, rotorMetal);
    turbofan.scale.z = side;
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
