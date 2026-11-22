import {
  BoxGeometry,
  CatmullRomCurve3,
  CylinderGeometry,
  Group,
  LatheGeometry,
  Mesh,
  MeshStandardMaterial,
  Quaternion,
  TubeGeometry,
  Vector2,
  Vector3,
} from "three";
import type { BufferGeometry } from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

type Position = readonly [number, number, number];
type RadiusProfile = readonly (readonly [radius: number, depth: number])[];

export function createAircraftLandingGear(): Group {
  const gear = new Group();
  gear.name = "Extended tricycle landing gear";
  const rubber = new MeshStandardMaterial({ name: "Tire rubber", color: "#202529", roughness: .94 });
  const hub = new MeshStandardMaterial({ name: "Wheel hubs and axles", color: "#a3aab0", roughness: .37, metalness: .67 });
  const castMetal = new MeshStandardMaterial({ name: "Strut castings", color: "#818e98", roughness: .48, metalness: .5 });
  const chrome = new MeshStandardMaterial({ name: "Oleo piston rods", color: "#b7c8d2", roughness: .25, metalness: .8 });
  const brake = new MeshStandardMaterial({ name: "Brake assemblies", color: "#45484b", roughness: .64, metalness: .4 });
  const door = new MeshStandardMaterial({ name: "Gear bay door enamel", color: "#ccd0cf", roughness: .53, metalness: .18 });
  const batches = new Map<MeshStandardMaterial, BufferGeometry[]>();
  const vertical = new Vector3(0, 1, 0);

  function add(geometry: BufferGeometry, material: MeshStandardMaterial) {
    const batch = batches.get(material);
    if (batch) batch.push(geometry);
    else batches.set(material, [geometry]);
  }

  function rod(points: readonly [Position, Position], radii: readonly [number, number], material: MeshStandardMaterial, segments = 12) {
    const start = new Vector3(...points[0]);
    const end = new Vector3(...points[1]);
    const axis = end.clone().sub(start);
    const geometry = new CylinderGeometry(radii[1], radii[0], axis.length(), segments);
    geometry.applyQuaternion(new Quaternion().setFromUnitVectors(vertical, axis.normalize()));
    const middle = start.lerp(end, .5);
    geometry.translate(middle.x, middle.y, middle.z);
    add(geometry, material);
  }

  function housing(position: Position, dimensions: Position, tilt: number, material: MeshStandardMaterial) {
    const geometry = new BoxGeometry(...dimensions);
    geometry.rotateX(tilt);
    geometry.translate(...position);
    add(geometry, material);
  }

  function radialPart(center: Position, profile: RadiusProfile, material: MeshStandardMaterial, segments = 36) {
    const geometry = new LatheGeometry(profile.map(([radius, depth]) => new Vector2(radius, depth)), segments);
    geometry.rotateX(Math.PI / 2);
    geometry.translate(...center);
    add(geometry, material);
  }

  function wheel([x, y, z]: Position, radius: number, width: number) {
    radialPart([x, y, z], [
      [.57 * radius, -.48 * width], [.74 * radius, -.50 * width], [.89 * radius, -.46 * width],
      [.967 * radius, -.36 * width], [.995 * radius, -.28 * width], [radius, -.195 * width],
      [radius, -.151 * width], [.984 * radius, -.135 * width], [.984 * radius, -.102 * width],
      [radius, -.086 * width], [radius, -.019 * width], [.984 * radius, -.013 * width],
      [.984 * radius, .013 * width], [radius, .019 * width], [radius, .086 * width],
      [.984 * radius, .102 * width], [.984 * radius, .135 * width], [radius, .151 * width],
      [radius, .195 * width], [.995 * radius, .28 * width], [.967 * radius, .36 * width],
      [.89 * radius, .46 * width], [.74 * radius, .50 * width], [.57 * radius, .48 * width],
      [.57 * radius, -.48 * width],
    ], rubber);

    radialPart([x, y, z], [
      [.47 * radius, -.53 * width], [.56 * radius, -.52 * width], [.595 * radius, -.475 * width],
      [.595 * radius, .475 * width], [.56 * radius, .52 * width], [.47 * radius, .53 * width],
      [.47 * radius, -.53 * width],
    ], hub, 28);
    for (const side of [-1, 1]) {
      const outer = z + side * width * .53;
      rod([[x, y, outer - side * .016], [x, y, outer + side * .004]], [.483 * radius, .48 * radius], brake, 24);
      rod([[x, y, outer], [x, y, outer + side * .044]], [.197 * radius, .153 * radius], hub);
      for (let stud = 0; stud < 6; stud += 1) {
        const theta = 2 * Math.PI * stud / 6;
        const boltX = x + .329 * radius * Math.cos(theta);
        const boltY = y + .329 * radius * Math.sin(theta);
        rod([[boltX, boltY, outer], [boltX, boltY, outer + side * .017]], [.051 * radius, .045 * radius], hub, 6);
      }
    }
  }

  function cable(points: Position[]) {
    const curve = new CatmullRomCurve3(points.map((point) => new Vector3(...point)));
    add(new TubeGeometry(curve, 18, .012, 5), rubber);
  }

  housing([-7.25, -1.16, 0], [.92, .105, .43], 0, brake);
  rod([[-7.29, -1.13, -.209], [-7.29, -1.13, .209]], [.113, .113], castMetal);
  rod([[-7.29, -1.14, 0], [-7.36, -2.112, 0]], [.115, .100], castMetal, 16);
  rod([[-7.352, -1.985, 0], [-7.379, -2.497, 0]], [.100, .065], chrome, 16);
  rod([[-7.378, -2.449, 0], [-7.38, -2.66, 0]], [.092, .126], castMetal);
  rod([[-7.38, -2.66, -.307], [-7.38, -2.66, .307]], [.065, .065], hub);
  rod([[-7.814, -1.116, 0], [-7.675, -1.709, 0]], [.059, .053], castMetal);
  rod([[-7.675, -1.697, 0], [-7.36, -2.081, 0]], [.049, .041], castMetal);
  rod([[-7.675, -1.704, -.078], [-7.675, -1.704, .078]], [.048, .048], hub, 8);
  cable([[-7.20, -1.27, .067], [-7.19, -1.66, .104], [-7.23, -2.02, .116], [-7.256, -2.28, .09], [-7.34, -2.49, .068]]);
  for (const side of [-1, 1]) {
    wheel([-7.38, -2.66, side * .177], .34, .171);
    housing([-7.29, -1.41, side * .277], [.86, .408, .034], side * .185, door);
    rod([[-7.65, -1.256, side * .23], [-6.92, -1.256, side * .23]], [.021, .021], castMetal);
  }

  for (const side of [-1, 1]) {
    const point = (x: number, y: number, z: number): Position => [x, y, side * z];
    housing(point(.6, -.906, 1.49), [.7, .108, .438], side * .08, brake);
    rod([point(.53, -.791, 1.29), point(.53, -.791, 1.705)], [.116, .116], castMetal);
    rod([point(.53, -.808, 1.50), point(.734, -1.98, 1.72)], [.154, .128], castMetal, 16);
    rod([point(.711, -1.841, 1.693), point(.792, -2.397, 1.761)], [.11, .085], chrome, 16);
    rod([point(.788, -2.321, 1.741), point(.8, -2.55, 1.763)], [.12, .151], castMetal);
    rod([point(.8, -2.55, 1.395), point(.8, -2.55, 2.07)], [.088, .088], hub);
    rod([point(-.016, -.958, 1.267), point(.253, -1.59, 1.444)], [.072, .059], castMetal);
    rod([point(.253, -1.59, 1.444), point(.726, -1.866, 1.69)], [.063, .061], castMetal);
    rod([point(.63, -.997, .95), point(.473, -1.529, 1.224)], [.061, .044], castMetal);
    rod([point(.473, -1.529, 1.224), point(.712, -1.869, 1.69)], [.049, .049], chrome);
    rod([point(.782, -1.91, 1.739), point(.958, -2.109, 1.751)], [.048, .039], castMetal);
    rod([point(.958, -2.109, 1.751), point(.843, -2.336, 1.744)], [.044, .044], castMetal);
    rod([point(.958, -2.109, 1.673), point(.958, -2.109, 1.825)], [.029, .029], hub, 8);
    housing(point(.442, -1.234, 1.918), [.486, .688, .044], side * -.23, door);
    cable([point(.631, -1.107, 1.613), point(.746, -1.463, 1.647), point(.894, -1.873, 1.83), point(.873, -2.21, 1.847), point(.8, -2.55, 1.838)]);
    for (const z of [1.589, 1.945]) {
      wheel(point(.8, -2.55, z), .45, .238);
    }
  }

  for (const [material, parts] of batches) {
    const merged = mergeGeometries(parts);
    if (merged) gear.add(new Mesh(merged, material));
    for (const geometry of parts) geometry.dispose();
  }

  return gear;
}
