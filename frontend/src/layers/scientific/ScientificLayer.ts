import type { Viewer } from "cesium";

import { fetchModels, pickDefaultModel } from "@/api/client";
import { getViewer } from "@/cesium/viewerStore";
import { layerRegistry } from "../LayerRegistry";
import type { VisualizationLayer } from "../types";
import { waterSurface } from "./waterSurface";

export class ScientificLayer implements VisualizationLayer {
  readonly id = "water-surface";
  readonly name = "Hydro overlay";
  available = false;
  visible = true;

  private cancelled = false;
  private retryTimer: number | undefined;
  private viewer: Viewer | null = null;
  private modelId = "";

  async initialize(viewer: Viewer): Promise<void> {
    this.cancelled = false;
    this.viewer = viewer;
    try {
      await this.load(viewer);
    } catch (error) {
      console.warn("SCHISM water overlay not ready; retrying:", error);
      this.available = false;
      this.retryTimer = window.setInterval(() => {
        if (this.cancelled || !this.viewer) {
          return;
        }
        void this.load(this.viewer)
          .then(() => {
            if (this.retryTimer !== undefined) {
              window.clearInterval(this.retryTimer);
              this.retryTimer = undefined;
            }
            layerRegistry.refresh();
          })
          .catch(() => undefined);
      }, 2500);
    }
  }

  setVisible(value: boolean): void {
    this.visible = value;
    waterSurface.setVisible(value);
  }

  async reload(): Promise<void> {
    if (this.retryTimer !== undefined) {
      window.clearInterval(this.retryTimer);
      this.retryTimer = undefined;
    }
    const viewer =
      this.viewer && !this.viewer.isDestroyed() ? this.viewer : getViewer();
    if (!viewer || viewer.isDestroyed()) {
      throw new Error("Globe is not ready");
    }
    this.viewer = viewer;
    this.cancelled = false;
    this.modelId = "";
    try {
      await this.load(viewer);
      this.available = waterSurface.nTimes > 0 || waterSurface.ready;
      layerRegistry.refresh();
      if (!this.available) {
        throw new Error("Hydro overlay did not load from the new S3 path");
      }
    } catch (error) {
      this.available = false;
      waterSurface.detach();
      layerRegistry.refresh();
      throw error;
    }
  }

  destroy(): void {
    this.cancelled = true;
    if (this.retryTimer !== undefined) {
      window.clearInterval(this.retryTimer);
      this.retryTimer = undefined;
    }
    waterSurface.detach();
    this.available = false;
    this.viewer = null;
  }

  private async load(viewer: Viewer, modelId?: string): Promise<void> {
    const models = await fetchModels();
    const fallback = pickDefaultModel(models);
    const id = modelId ?? (this.modelId || fallback?.id);
    const meta = models.find((model) => model.id === id) ?? fallback;
    if (!meta) {
      throw new Error("No hydro models available");
    }
    if (this.cancelled || !this.viewer || this.viewer.isDestroyed() || this.viewer !== viewer) {
      return;
    }
    this.modelId = meta.id;
    await waterSurface.attachOverview(viewer, meta);
    this.available = waterSurface.nTimes > 0 || waterSurface.ready;
    if (this.available) {
      waterSurface.setVisible(this.visible);
    }
    layerRegistry.refresh();
  }
}
