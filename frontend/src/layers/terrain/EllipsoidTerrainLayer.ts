import type { Viewer } from "cesium";

import type { TerrainSource, VisualizationLayer } from "../types";

/** Phase 1 terrain: WGS84 ellipsoid. Swap the provider in Phase 2. */
export class EllipsoidTerrainLayer implements VisualizationLayer, TerrainSource {
  readonly id = "terrain";
  readonly name = "Terrain";
  readonly available = true;
  visible = true;
  private viewer: Viewer | null = null;

  async initialize(viewer: Viewer): Promise<void> {
    this.viewer = viewer;
    viewer.scene.globe.show = this.visible;
  }

  setVisible(value: boolean): void {
    this.visible = value;
    if (this.viewer && !this.viewer.isDestroyed()) {
      this.viewer.scene.globe.show = value;
    }
  }

  destroy(): void {
    this.viewer = null;
  }
}
