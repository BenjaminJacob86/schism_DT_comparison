import {
  Cartesian2,
  Cartesian3,
  Color,
  HeightReference,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Math as CesiumMath,
  Cartographic,
  type Entity,
  type Viewer,
} from "cesium";

import { fetchProfile, fetchSeries, type ProfilePayload, type SeriesPayload } from "@/api/client";
import { polygonStore } from "./polygonTool";
import { waterSurface } from "./waterSurface";

type Listener = () => void;

class SeriesStore {
  current: SeriesPayload | null = null;
  profile: ProfilePayload | null = null;
  loading = false;
  error: string | null = null;
  hubView = "";
  private viewer: Viewer | null = null;
  private marker: Entity | null = null;
  private token = 0;
  private lastSliceKey = "";
  private lastTime = -1;
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

  async pick(viewer: Viewer, lon: number, lat: number): Promise<void> {
    const modelId = waterSurface.modelId;
    if (!modelId) {
      this.clear();
      return;
    }
    this.viewer = viewer;
    this.loading = true;
    this.error = null;
    this.placeMarker(lon, lat);
    const token = ++this.token;
    this.notify();
    try {
      const series = await fetchSeries(
        modelId,
        lon,
        lat,
        waterSurface.variable,
        waterSurface.overlayLayerIndex,
        waterSurface.overlayZMeters,
      );
      if (token !== this.token) {
        return;
      }
      if (!series) {
        this.clearMarker();
        this.current = null;
        this.profile = null;
        this.error = "No water at this point";
        this.loading = false;
        this.notify();
        return;
      }
      this.current = series;
      this.error = null;
      this.lastSliceKey = this.sliceKey();
      this.lastTime = waterSurface.timeIndex;
      this.placeMarker(series.lon, series.lat);
      if (waterSurface.isVertical) {
        const profile = await fetchProfile(
          modelId,
          series.lon,
          series.lat,
          waterSurface.timeIndex,
          waterSurface.variable,
        );
        if (token !== this.token) {
          return;
        }
        this.profile = profile;
      } else {
        this.profile = null;
      }
    } catch (error) {
      if (token !== this.token) {
        return;
      }
      this.current = null;
      this.profile = null;
      this.clearMarker();
      this.error = error instanceof Error ? error.message : "Series failed";
    } finally {
      if (token === this.token) {
        this.loading = false;
        this.notify();
      }
    }
  }

  async refresh(): Promise<void> {
    if (!this.viewer || !this.current) {
      return;
    }
    await this.pick(this.viewer, this.current.lon, this.current.lat);
  }

  async refreshProfile(): Promise<void> {
    if (!this.current || !waterSurface.isVertical || !waterSurface.modelId) {
      if (!waterSurface.isVertical) {
        this.profile = null;
        this.notify();
      }
      return;
    }
    const token = this.token;
    try {
      const profile = await fetchProfile(
        waterSurface.modelId,
        this.current.lon,
        this.current.lat,
        waterSurface.timeIndex,
        waterSurface.variable,
      );
      if (token !== this.token) {
        return;
      }
      this.profile = profile;
      this.notify();
    } catch {
      if (token === this.token) {
        this.profile = null;
        this.notify();
      }
    }
  }

  clear(): void {
    this.token += 1;
    this.current = null;
    this.profile = null;
    this.loading = false;
    this.error = null;
    this.clearMarker();
    this.notify();
  }

  refreshIfStale(): void {
    if (!this.current || this.loading) {
      return;
    }
    const slice = this.sliceKey();
    if (slice !== this.lastSliceKey) {
      void this.refresh();
      return;
    }
    if (waterSurface.isVertical && waterSurface.timeIndex !== this.lastTime) {
      this.lastTime = waterSurface.timeIndex;
      void this.refreshProfile();
    }
  }

  private sliceKey(): string {
    return `${waterSurface.modelId}:${waterSurface.variable}:${waterSurface.overlayLayerIndex}:${waterSurface.overlayZMeters}:${this.hubView}`;
  }

  setHubView(view: string): void {
    this.hubView = view;
  }

  detach(): void {
    this.clear();
    this.viewer = null;
  }

  private placeMarker(lon: number, lat: number): void {
    this.clearMarker();
    if (!this.viewer || this.viewer.isDestroyed()) {
      return;
    }
    this.marker = this.viewer.entities.add({
      position: Cartesian3.fromDegrees(lon, lat, 40),
      point: {
        pixelSize: 14,
        color: Color.fromCssColorString("#4eb3c2"),
        outlineColor: Color.WHITE,
        outlineWidth: 2,
        heightReference: HeightReference.NONE,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  private clearMarker(): void {
    if (
      this.viewer &&
      !this.viewer.isDestroyed() &&
      this.marker
    ) {
      this.viewer.entities.remove(this.marker);
    }
    this.marker = null;
  }
}

export const seriesStore = new SeriesStore();

export function attachSeriesPicker(viewer: Viewer): () => void {
  const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((click: { position: { x: number; y: number } }) => {
    if (polygonStore.drawing) {
      return;
    }
    if (!waterSurface.modelId) {
      seriesStore.clear();
      return;
    }
    const cartesian = viewer.camera.pickEllipsoid(
      Cartesian2.fromElements(click.position.x, click.position.y),
      viewer.scene.globe.ellipsoid,
    );
    if (!cartesian) {
      seriesStore.clear();
      return;
    }
    const carto = Cartographic.fromCartesian(cartesian);
    void seriesStore.pick(
      viewer,
      CesiumMath.toDegrees(carto.longitude),
      CesiumMath.toDegrees(carto.latitude),
    );
  }, ScreenSpaceEventType.LEFT_CLICK);

  const unsubWater = waterSurface.subscribe(() => seriesStore.refreshIfStale());

  return () => {
    unsubWater();
    handler.destroy();
    seriesStore.detach();
  };
}
