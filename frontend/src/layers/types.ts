import type { Viewer } from "cesium";

export interface VisualizationLayer {
  readonly id: string;
  readonly name: string;
  visible: boolean;
  available: boolean;
  initialize(viewer: Viewer): Promise<void>;
  setVisible(value: boolean): void;
  destroy(): void;
}

export interface TerrainSource {
  initialize(viewer: Viewer): Promise<void>;
}

export type LayerSnapshot = {
  id: string;
  name: string;
  visible: boolean;
  available: boolean;
};
