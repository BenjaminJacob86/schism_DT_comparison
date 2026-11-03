import { useCallback, useMemo, useState } from "react";

import { CesiumAppContext } from "@/cesium/CesiumContext";
import { CesiumView, zoomToHydroModel } from "@/cesium/CesiumView";
import { AppShell } from "@/components/AppShell";

export default function App() {
  const [ready, setReady] = useState(false);
  const onReady = useCallback((value: boolean) => setReady(value), []);
  const api = useMemo(
    () => ({
      ready,
      zoomToModel: zoomToHydroModel,
    }),
    [ready],
  );

  return (
    <CesiumAppContext.Provider value={api}>
      <AppShell>
        <CesiumView onReady={onReady} />
      </AppShell>
    </CesiumAppContext.Provider>
  );
}
