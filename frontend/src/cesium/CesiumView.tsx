import { useEffect, useRef } from "react";

import { createViewer } from "./createViewer";
import { setViewer } from "./viewerStore";
import { layerRegistry } from "@/layers/LayerRegistry";
import { attachPolygonDrawer } from "@/layers/scientific/polygonTool";
import { attachSeriesPicker } from "@/layers/scientific/seriesPick";
import { waterSurface } from "@/layers/scientific/waterSurface";

type CesiumViewProps = {
  onReady: (ready: boolean) => void;
};

export function CesiumView({ onReady }: CesiumViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const viewer = createViewer(container);
    setViewer(viewer);
    onReady(true);
    const detachPicker = attachSeriesPicker(viewer);
    const detachPolygon = attachPolygonDrawer(viewer);

    return () => {
      detachPolygon();
      detachPicker();
      onReady(false);
      layerRegistry.clear();
      if (!viewer.isDestroyed()) {
        viewer.destroy();
      }
      setViewer(null);
    };
  }, [onReady]);

  return <div className="cesium-root" ref={containerRef} />;
}

export function zoomToHydroModel(): void {
  waterSurface.zoomToData(true);
}
