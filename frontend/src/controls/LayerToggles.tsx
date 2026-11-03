import { useEffect, useState } from "react";

import { layerRegistry } from "@/layers/LayerRegistry";
import type { LayerSnapshot } from "@/layers/types";

export function LayerToggles() {
  const [layers, setLayers] = useState<LayerSnapshot[]>(() => layerRegistry.list());

  useEffect(() => {
    setLayers(layerRegistry.list());
    return layerRegistry.subscribe(() => setLayers(layerRegistry.list()));
  }, []);

  return (
    <ul className="layer-list">
      {layers.map((layer) => (
        <li key={layer.id}>
          <label className={layer.available ? undefined : "is-disabled"}>
            <input
              type="checkbox"
              checked={layer.visible}
              disabled={!layer.available}
              onChange={(event) => layerRegistry.setVisible(layer.id, event.target.checked)}
            />
            <span>{layer.name}</span>
            {!layer.available ? <em>soon</em> : null}
          </label>
        </li>
      ))}
    </ul>
  );
}
