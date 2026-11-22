import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import type { AircraftFocus, AircraftViewerProps } from "./AircraftViewer";

function UnavailableViewer({ onUnavailable }: AircraftViewerProps) {
  useEffect(() => { onUnavailable(); }, [onUnavailable]);
  return null;
}

const AircraftViewer = lazy(() => import("./AircraftViewer")
  .then(({ AircraftViewer: viewer }) => ({ default: viewer }))
  .catch(() => ({ default: UnavailableViewer })));

type AircraftSceneProps = {
  focus: AircraftFocus;
  fallback: ReactNode;
  onSelect?: (focus: Exclude<AircraftFocus, "overview">) => void;
};

export function AircraftScene({ focus, fallback, onSelect }: AircraftSceneProps) {
  const [status, setStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const showViewer = useCallback(() => setStatus("ready"), []);
  const showFallback = useCallback(() => setStatus("unavailable"), []);

  return (
    <div className="aircraft-scene" data-aircraft-status={status}>
      {status === "loading" && (
        <div className="aircraft-scene__loading" role="status">
          <span aria-hidden="true" />
          Загружаем 3D-модель
        </div>
      )}
      {status === "unavailable" && fallback}
      {status !== "unavailable" && (
        <div className="aircraft-scene__canvas" aria-hidden={status !== "ready"}>
          <Suspense fallback={null}>
            <AircraftViewer focus={focus} onReady={showViewer} onUnavailable={showFallback} onSelect={onSelect} />
          </Suspense>
        </div>
      )}
    </div>
  );
}
