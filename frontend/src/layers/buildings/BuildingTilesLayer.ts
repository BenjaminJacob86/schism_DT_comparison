import {
  Cesium3DTileset,
  type Viewer,
} from "cesium";

import { env } from "@/config/env";
import type { VisualizationLayer } from "../types";

function tilesetCandidates(): string[] {
  const urls = [
    env.buildingsTilesetUrl,
    `${env.apiBaseUrl}/api/assets/buildings/tileset.json`,
    `${env.assetBaseUrl}/buildings/hamburg/area1/tileset.json`,
  ];
  return [...new Set(urls.filter((url) => url.length > 0))];
}

export class BuildingTilesLayer implements VisualizationLayer {
  readonly id = "buildings";
  readonly name = "Buildings";
  available = false;
  visible = true;
  private viewer: Viewer | null = null;
  private tileset: Cesium3DTileset | null = null;

  async initialize(viewer: Viewer): Promise<void> {
    this.viewer = viewer;
    const candidates = tilesetCandidates();
    for (const url of candidates) {
      try {
        const tileset = await Cesium3DTileset.fromUrl(url, {
          maximumScreenSpaceError: 8,
        });
        viewer.scene.primitives.add(tileset);
        this.tileset = tileset;
        this.available = true;
        tileset.show = this.visible;
        return;
      } catch (error) {
        console.warn("Hamburg 3D Tiles not loaded from", url, error);
      }
    }
    this.available = false;
  }

  private unloadTileset(): void {
    if (
      this.viewer &&
      !this.viewer.isDestroyed() &&
      this.tileset &&
      !this.tileset.isDestroyed()
    ) {
      this.viewer.scene.primitives.remove(this.tileset);
    }
    this.tileset = null;
    this.available = false;
  }

  async reload(): Promise<void> {
    const viewer = this.viewer;
    if (!viewer || viewer.isDestroyed()) {
      return;
    }
    this.unloadTileset();
    await this.initialize(viewer);
  }

  setVisible(value: boolean): void {
    this.visible = value;
    if (this.tileset && !this.tileset.isDestroyed()) {
      this.tileset.show = value;
    }
  }

  destroy(): void {
    this.unloadTileset();
    this.viewer = null;
  }
}
