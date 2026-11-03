import { useEffect, useState } from "react";

import { useCesiumApp } from "@/cesium/CesiumContext";
import { waterSurface } from "@/layers/scientific/waterSurface";

export function StatusBar() {
  const { ready } = useCesiumApp();
  const [, setTick] = useState(0);

  useEffect(() => {
    const unsub = waterSurface.subscribe(() => setTick((n) => n + 1));
    setTick((n) => n + 1);
    return unsub;
  }, []);

  const hydro = waterSurface.ready
    ? `overlay · ${waterSurface.variableLabel} · ${waterSurface.colormap} · ${waterSurface.nNodes.toLocaleString()} nodes · t ${waterSurface.timeIndex + 1}/${waterSurface.nTimes}${
        waterSurface.isVertical
          ? waterSurface.zInterp
            ? ` · z ${waterSurface.zMeters} m`
            : ` · k ${waterSurface.overlayLayerIndex}/${Math.max(waterSurface.nLayers - 1, 0)}`
          : ""
      }${waterSurface.nTriangles ? ` · ${waterSurface.nTriangles.toLocaleString()} tris` : ""}`
    : "water not loaded";

  return (
    <footer className="status-bar">
      <span>{ready ? "Cesium ready" : "Starting viewer…"}</span>
      <span>{hydro}</span>
    </footer>
  );
}
