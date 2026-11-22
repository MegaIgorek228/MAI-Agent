import { useEffect, useRef, useState } from "react";
import type { ReactElement } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

import { createAircraftExterior } from "./aircraftExterior";
import { createAircraftInterior } from "./aircraftInterior";
import { Icon } from "./Icon";
import "./aircraft-viewer.css";

export type AircraftFocus = "overview" | "cockpit" | "seat" | "lounge";
type AircraftBay = Exclude<AircraftFocus, "overview">;

export type AircraftViewerProps = {
  focus: AircraftFocus;
  onReady: () => void;
  onUnavailable: () => void;
  onSelect?: (focus: AircraftBay) => void;
};

type ViewerCallbacks = Omit<AircraftViewerProps, "focus"> & { onExteriorChange: (closed: boolean) => void };
type CameraFlight = {
  start: number;
  duration: number;
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
  fromOrbit: THREE.Spherical;
  toOrbit: THREE.Spherical;
  lift: number;
};

const destinations: Record<AircraftFocus, { x: number; y: number; z: number; angle: number }> = {
  overview: { x: 0, y: -.38, z: 0, angle: -.24 },
  cockpit: { x: -6.6, y: .14, z: .18, angle: .22 },
  seat: { x: -3.45, y: .03, z: .16, angle: .06 },
  lounge: { x: 2.7, y: .07, z: .23, angle: -.09 },
};

const bayBands: [AircraftBay, number, number][] = [
  ["cockpit", -8, -5.3],
  ["seat", -5.25, .85],
  ["lounge", .95, 5.45],
];

function disposeScene(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  root.traverse((object) => {
    if (object instanceof THREE.DirectionalLight && object.castShadow) object.shadow.dispose();
    if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Points)) return;
    geometries.add(object.geometry);
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      materials.add(material);
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) textures.add(value);
      }
    }
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
  for (const texture of textures) texture.dispose();
}

function makeStudioMap(renderer: THREE.WebGLRenderer) {
  const room = new RoomEnvironment();
  const generator = new THREE.PMREMGenerator(renderer);
  try {
    return generator.fromScene(room, .045);
  } finally {
    generator.dispose();
    room.dispose();
  }
}

function createStudio(renderer: THREE.WebGLRenderer, scene: THREE.Scene, airplane: THREE.Group) {
  const key = new THREE.DirectionalLight(0xfff4e5, 1.9);
  key.position.set(-8, 13, 6);
  key.castShadow = true;
  key.shadow.mapSize.setScalar(window.matchMedia("(pointer: coarse)").matches ? 1024 : 1536);
  key.shadow.camera.left = -13;
  key.shadow.camera.right = 13;
  key.shadow.camera.top = 9;
  key.shadow.camera.bottom = -9;
  key.shadow.camera.near = .5;
  key.shadow.camera.far = 34;
  key.shadow.camera.updateProjectionMatrix();
  key.shadow.bias = -.00015;
  key.shadow.normalBias = .018;
  key.shadow.radius = 2.8;

  const rim = new THREE.DirectionalLight(0xdfeaff, .65);
  rim.position.set(7, 5, -9);
  const frontFill = new THREE.DirectionalLight(0xfff5e8, .95);
  frontFill.position.set(-1, 1.6, 11);
  scene.add(key, key.target, rim, frontFill, new THREE.HemisphereLight(0xf2f3ef, 0x807d76, .48));

  airplane.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    object.castShadow = materials.some((material) => !material.transparent);
    object.receiveShadow = true;
  });

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(46, 29),
    new THREE.ShadowMaterial({ color: 0x414951, opacity: .075, depthWrite: false }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -3.008;
  ground.receiveShadow = true;
  scene.add(ground);

  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
}

function createViewer(host: HTMLDivElement, initialFocus: AircraftFocus, callbacks: ViewerCallbacks) {
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
  const scene = new THREE.Scene();
  const airplane = new THREE.Group();
  scene.add(airplane);

  let environment: THREE.WebGLRenderTarget | undefined;
  let body: THREE.Group;
  let panels: THREE.Group;
  let cutaway: THREE.Group;
  let interior: THREE.Group;
  try {
    ({ body, panels, cutaway } = createAircraftExterior());
    airplane.add(body, panels, cutaway);
    interior = createAircraftInterior();
    airplane.add(interior);
    panels.visible = false;
    createStudio(renderer, scene, airplane);
    environment = makeStudioMap(renderer);
    scene.environment = environment.texture;
    scene.environmentIntensity = .55;
    scene.environmentRotation.y = -.32;
  } catch (error) {
    disposeScene(scene);
    environment?.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    throw error;
  }

  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = .9;
  const canvas = renderer.domElement;
  canvas.setAttribute("data-aircraft-canvas", "");
  canvas.setAttribute("aria-label", "Трёхмерная модель самолёта. Стрелки вращают, плюс и минус меняют масштаб.");
  canvas.tabIndex = 0;
  host.append(canvas);

  const camera = new THREE.PerspectiveCamera(37, 1, .08, 125);
  camera.position.set(-2.2, 4.1, 18);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false;
  controls.minDistance = 2.8;
  controls.maxDistance = 48;
  controls.minPolarAngle = .07;
  controls.maxPolarAngle = Math.PI - .07;
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const orbit = new THREE.Spherical();
  let focus = initialFocus;
  let flight: CameraFlight | null = null;
  let tapped: { id: number; x: number; y: number; time: number } | null = null;
  let frame = 0;
  let width = 0;
  let height = 0;
  let built = false;
  let reported = false;
  let disposed = false;
  let contextLost = false;
  let manuallyMoved = false;

  function requestFrame() {
    if (!frame && !disposed && !contextLost && width && height) frame = requestAnimationFrame(render);
  }

  function failure() {
    if (contextLost || disposed) return;
    contextLost = true;
    cancelAnimationFrame(frame);
    frame = 0;
    callbacks.onUnavailable();
  }

  function applyOrbit(target: THREE.Vector3, position: THREE.Spherical) {
    controls.target.copy(target);
    camera.position.setFromSpherical(position).add(target);
    controls.update();
  }

  function render(time: number) {
    frame = 0;
    if (contextLost || disposed) return;
    if (flight) {
      const { start, duration, fromTarget, toTarget, fromOrbit, toOrbit, lift } = flight;
      const progress = Math.min(1, (time - start) / duration);
      const eased = progress * progress * (3 - 2 * progress);
      const arc = lift * Math.sin(Math.PI * eased);
      const target = new THREE.Vector3().lerpVectors(fromTarget, toTarget, eased);
      target.y += arc * .43;
      orbit.set(
        THREE.MathUtils.lerp(fromOrbit.radius, toOrbit.radius, eased) + arc,
        THREE.MathUtils.lerp(fromOrbit.phi, toOrbit.phi, eased) - arc * .065,
        THREE.MathUtils.lerp(fromOrbit.theta, toOrbit.theta, eased) + arc * .085,
      );
      applyOrbit(target, orbit);
      if (progress === 1) flight = null;
      else requestFrame();
    }
    try {
      renderer.render(scene, camera);
    } catch {
      failure();
      return;
    }
    if (!reported) {
      reported = true;
      callbacks.onReady();
    }
  }

  function setExterior(exterior: boolean) {
    panels.visible = exterior;
    cutaway.visible = !exterior;
    renderer.shadowMap.needsUpdate = true;
    callbacks.onExteriorChange(exterior);
    requestFrame();
  }

  function distanceFor(next: AircraftFocus) {
    const halfWidthAtOneUnit = Math.tan(THREE.MathUtils.degToRad(camera.fov * .5)) * camera.aspect;
    return next === "overview"
      ? THREE.MathUtils.clamp(13.05 / halfWidthAtOneUnit, 15.8, 43)
      : THREE.MathUtils.clamp(4.8 / halfWidthAtOneUnit, 3.15, 8.4);
  }

  function moveTo(next: AircraftFocus, animate = true, reset = false) {
    if (animate && !reset && focus === next) return;
    const betweenBays = focus !== "overview" && next !== "overview" && focus !== next;
    focus = next;
    manuallyMoved = false;
    if (panels.visible && next !== "overview") setExterior(false);

    const view = destinations[next];
    const target = new THREE.Vector3(view.x, view.y, view.z);
    const toOrbit = new THREE.Spherical(distanceFor(next), next === "overview" ? 1.3 : 1.42, view.angle);

    if (!animate || motion.matches) {
      flight = null;
      applyOrbit(target, toOrbit);
    } else {
      const fromOrbit = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
      const angleDelta = THREE.MathUtils.euclideanModulo(toOrbit.theta - fromOrbit.theta + Math.PI, Math.PI * 2) - Math.PI;
      toOrbit.theta = fromOrbit.theta + angleDelta;
      flight = {
        start: performance.now(),
        duration: betweenBays ? 810 : 650,
        fromTarget: controls.target.clone(),
        toTarget: target,
        fromOrbit,
        toOrbit,
        lift: betweenBays ? 1.65 : .55,
      };
    }
    requestFrame();
  }

  function beginManualMove() {
    flight = null;
    manuallyMoved = true;
  }

  function zoom(scale: number) {
    beginManualMove();
    orbit.setFromVector3(camera.position.clone().sub(controls.target));
    orbit.radius = THREE.MathUtils.clamp(orbit.radius * scale, controls.minDistance, controls.maxDistance);
    applyOrbit(controls.target, orbit);
    requestFrame();
  }

  function rotate(theta: number, phi: number) {
    beginManualMove();
    orbit.setFromVector3(camera.position.clone().sub(controls.target));
    orbit.theta += theta;
    orbit.phi = THREE.MathUtils.clamp(orbit.phi + phi, controls.minPolarAngle, controls.maxPolarAngle);
    applyOrbit(controls.target, orbit);
    requestFrame();
  }

  function onKeyDown(event: KeyboardEvent) {
    const step = .14;
    switch (event.key) {
      case "ArrowLeft": rotate(-step, 0); break;
      case "ArrowRight": rotate(step, 0); break;
      case "ArrowUp": rotate(0, -step); break;
      case "ArrowDown": rotate(0, step); break;
      case "=":
      case "+": zoom(.83); break;
      case "-":
      case "−": zoom(1 / .83); break;
      case "Home": moveTo(focus, true, true); break;
      default: return;
    }
    event.preventDefault();
  }

  function onPointerDown(event: PointerEvent) {
    tapped = event.isPrimary && event.button === 0
      ? { id: event.pointerId, x: event.clientX, y: event.clientY, time: performance.now() }
      : null;
  }

  function onPointerMove(event: PointerEvent) {
    if (tapped && tapped.id === event.pointerId && Math.hypot(event.clientX - tapped.x, event.clientY - tapped.y) > 7) tapped = null;
  }

  function onPointerUp(event: PointerEvent) {
    const gesture = tapped;
    tapped = null;
    if (!gesture || gesture.id !== event.pointerId || performance.now() - gesture.time > 450 || panels.visible) return;
    if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 7) return;
    const box = canvas.getBoundingClientRect();
    pointer.set((event.clientX - box.left) * 2 / box.width - 1, 1 - (event.clientY - box.top) * 2 / box.height);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects([body, interior], true)[0];
    if (!hit) return;

    let object: THREE.Object3D | null = hit.object;
    while (object && object !== interior) object = object.parent;
    if (!object) return;
    const x = airplane.worldToLocal(hit.point).x;
    const bay = bayBands.find(([, min, max]) => x >= min && x <= max)?.[0];
    if (bay) callbacks.onSelect?.(bay);
  }

  function onPointerCancel() {
    tapped = null;
  }

  function onMotionChange() {
    if (motion.matches && flight) moveTo(focus, false);
  }

  function resize() {
    if (disposed || contextLost) return;
    const box = host.getBoundingClientRect();
    const newWidth = Math.floor(box.width);
    const newHeight = Math.floor(box.height);
    if (!newWidth || !newHeight || (newWidth === width && newHeight === height)) return;
    const previousAspect = camera.aspect;
    width = newWidth;
    height = newHeight;
    camera.aspect = width / height;
    const composition = Number.parseFloat(getComputedStyle(host).getPropertyValue("--aircraft-composition-x"));
    if (Number.isFinite(composition) && composition !== 0) camera.setViewOffset(width, height, width * composition, 0, width, height);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.65));
    renderer.setSize(width, height, false);
    if (flight) {
      flight.toOrbit.radius = distanceFor(focus);
    } else if (!built || (!manuallyMoved && Math.abs(previousAspect - camera.aspect) > .05)) {
      moveTo(focus, false);
      built = true;
    }
    requestFrame();
  }

  controls.addEventListener("change", requestFrame);
  controls.addEventListener("start", beginManualMove);
  canvas.addEventListener("webglcontextlost", failure);
  canvas.addEventListener("keydown", onKeyDown);
  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", onPointerUp);
  canvas.addEventListener("pointercancel", onPointerCancel);
  motion.addEventListener("change", onMotionChange);
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();

  return {
    focus: moveTo,
    zoom,
    reset: () => moveTo(focus, true, true),
    toggleExterior: () => setExterior(!panels.visible),
    dispose() {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      motion.removeEventListener("change", onMotionChange);
      controls.removeEventListener("change", requestFrame);
      controls.removeEventListener("start", beginManualMove);
      controls.dispose();
      canvas.removeEventListener("webglcontextlost", failure);
      canvas.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("pointercancel", onPointerCancel);
      disposeScene(scene);
      environment?.dispose();
      renderer.dispose();
      if (!contextLost) renderer.forceContextLoss();
      canvas.remove();
    },
  };
}

export function AircraftViewer({ focus, onReady, onUnavailable, onSelect }: AircraftViewerProps): ReactElement | null {
  const host = useRef<HTMLDivElement>(null);
  const initialFocus = useRef(focus);
  const callbacks = useRef({ onReady, onUnavailable, onSelect });
  const viewer = useRef<ReturnType<typeof createViewer> | null>(null);
  const [ready, setReady] = useState(false);
  const [exterior, setExterior] = useState(false);

  useEffect(() => {
    callbacks.current = { onReady, onUnavailable, onSelect };
  }, [onReady, onUnavailable, onSelect]);

  useEffect(() => {
    if (!host.current) return;
    try {
      const active = createViewer(host.current, initialFocus.current, {
        onReady: () => {
          setReady(true);
          callbacks.current.onReady();
        },
        onUnavailable: () => {
          setReady(false);
          callbacks.current.onUnavailable();
        },
        onSelect: (zone) => callbacks.current.onSelect?.(zone),
        onExteriorChange: setExterior,
      });
      viewer.current = active;
      return () => {
        viewer.current = null;
        active.dispose();
      };
    } catch {
      callbacks.current.onUnavailable();
    }
  }, []);

  useEffect(() => { viewer.current?.focus(focus); }, [focus]);

  const exteriorLabel = exterior ? "Показать самолёт в разрезе" : "Показать самолёт снаружи";
  return (
    <div className="aircraft-viewer" data-ready={ready}>
      <div className="aircraft-viewer__canvas" ref={host} />
      {ready && (
        <div className="aircraft-viewer__tools" role="group" aria-label="Управление трёхмерной моделью">
          <button type="button" aria-label="Приблизить" title="Приблизить" onClick={() => viewer.current?.zoom(.83)}>
            <Icon name="plus" />
          </button>
          <button type="button" aria-label="Отдалить" title="Отдалить" onClick={() => viewer.current?.zoom(1 / .83)}>
            <span aria-hidden="true" className="aircraft-viewer__minus">−</span>
          </button>
          <button type="button" aria-label="Сбросить вид" title="Сбросить вид" onClick={() => viewer.current?.reset()}>
            <Icon name="refresh" />
          </button>
          <button type="button" aria-label={exteriorLabel} title={exteriorLabel} aria-pressed={exterior} onClick={() => viewer.current?.toggleExterior()}>
            <Icon name={exterior ? "panel-left" : "plane"} />
          </button>
        </div>
      )}
    </div>
  );
}
