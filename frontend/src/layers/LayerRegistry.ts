import type { Viewer } from "cesium";

import type { LayerSnapshot, VisualizationLayer } from "./types";

type Listener = () => void;

class LayerRegistry {
  private readonly layers = new Map<string, VisualizationLayer>();
  private readonly listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  get(id: string): VisualizationLayer | undefined {
    return this.layers.get(id);
  }

  async register(layer: VisualizationLayer, viewer: Viewer): Promise<void> {
    this.layers.set(layer.id, layer);
    this.notify();
    await layer.initialize(viewer);
    this.notify();
  }

  list(): LayerSnapshot[] {
    return [...this.layers.values()].map((layer) => ({
      id: layer.id,
      name: layer.name,
      visible: layer.visible,
      available: layer.available,
    }));
  }

  refresh(): void {
    this.notify();
  }

  setVisible(id: string, visible: boolean): void {
    const layer = this.layers.get(id);
    if (!layer || !layer.available) {
      return;
    }
    layer.setVisible(visible);
    this.notify();
  }

  clear(): void {
    for (const layer of this.layers.values()) {
      layer.destroy();
    }
    this.layers.clear();
    this.notify();
  }
}

export const layerRegistry = new LayerRegistry();
