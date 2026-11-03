import {
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Color,
  HeightReference,
  ImageMaterialProperty,
  PolygonHierarchy,
  Rectangle,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Math as CesiumMath,
  Cartographic,
  type Entity,
  type Viewer,
} from "cesium";

import { fetchPolygonStats, fetchPolygonThreshold, type PolygonStatsPayload } from "@/api/client";
import { waterSurface } from "./waterSurface";

const DRAW_HEIGHT = 40;
const FILL = Color.fromCssColorString("#4eb3c2").withAlpha(0.28);
const FILL_ANALYSED = Color.fromCssColorString("#4eb3c2").withAlpha(0.08);
const LINE = Color.fromCssColorString("#4eb3c2");

type Listener = () => void;
export type LonLat = { lon: number; lat: number };

class PolygonStore {
  drawing = false;
  closed = false;
  vertices: LonLat[] = [];
  stats: PolygonStatsPayload | null = null;
  loading = false;
  error: string | null = null;
  threshold = 0;
  hubView = "";
  analysed = false;
  private viewer: Viewer | null = null;
  private overlayEntity: Entity | null = null;
  private overlayUrl: string | null = null;
  private token = 0;
  private lastQueryKey = "";
  private readonly listeners = new Set<Listener>();
  private line: Entity | null = null;
  private fill: Entity | null = null;
  private dots: Entity[] = [];

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  attach(viewer: Viewer): void {
    this.viewer = viewer;
    this.rebuildGraphics();
  }

  start(): void {
    if (!this.viewer || this.viewer.isDestroyed()) {
      return;
    }
    this.drawing = true;
    this.closed = false;
    this.vertices = [];
    this.stats = null;
    this.error = null;
    this.loading = false;
    this.analysed = false;
    this.lastQueryKey = "";
    this.token += 1;
    this.dropOverlay();
    this.rebuildGraphics();
    this.setCursor("crosshair");
    this.notify();
  }

  addVertex(lon: number, lat: number): void {
    if (!this.drawing) {
      return;
    }
    this.vertices = [...this.vertices, { lon, lat }];
    this.rebuildGraphics();
    this.notify();
  }

  undo(): void {
    if (!this.drawing || !this.vertices.length) {
      return;
    }
    this.vertices = this.vertices.slice(0, -1);
    this.rebuildGraphics();
    this.notify();
  }

  async finish(): Promise<void> {
    if (!this.drawing || this.vertices.length < 3) {
      return;
    }
    this.drawing = false;
    this.closed = true;
    this.setCursor("");
    this.rebuildGraphics();
    this.notify();
  }

  setThreshold(value: number): void {
    if (!Number.isFinite(value) || value === this.threshold) {
      return;
    }
    this.threshold = value;
    this.notify();
  }

  setHubView(view: string): void {
    this.hubView = view;
  }

  async analyse(): Promise<void> {
    if (this.drawing && this.vertices.length >= 3) {
      this.drawing = false;
      this.closed = true;
      this.setCursor("");
      this.rebuildGraphics();
    }
    if (!this.closed || this.vertices.length < 3) {
      this.error = "Draw a polygon with at least 3 vertices first";
      this.notify();
      return;
    }
    this.analysed = true;
    this.rebuildGraphics();
    this.notify();
    await this.compute();
    if (this.analysed && this.stats) {
      await this.showOverlay();
    }
  }

  cancel(): void {
    this.drawing = false;
    this.setCursor("");
    if (!this.closed) {
      this.vertices = [];
      this.stats = null;
      this.error = null;
      this.rebuildGraphics();
    }
    this.notify();
  }

  clear(): void {
    this.token += 1;
    this.drawing = false;
    this.closed = false;
    this.vertices = [];
    this.stats = null;
    this.loading = false;
    this.error = null;
    this.analysed = false;
    this.lastQueryKey = "";
    this.setCursor("");
    this.dropOverlay();
    this.rebuildGraphics();
    this.notify();
  }

  async refresh(): Promise<void> {
    if (!this.closed || this.vertices.length < 3 || !this.analysed) {
      return;
    }
    await this.compute();
    if (this.analysed && this.stats) {
      await this.showOverlay();
    }
  }

  refreshIfStale(): void {
    if (!this.closed || this.vertices.length < 3 || this.drawing || !this.analysed) {
      return;
    }
    const key = this.queryKey();
    if (key === this.lastQueryKey || this.loading) {
      return;
    }
    void this.refresh();
  }

  detach(): void {
    this.clear();
    this.viewer = null;
  }

  private queryKey(): string {
    return `${waterSurface.modelId}:${waterSurface.variable}:${waterSurface.timeIndex}:${waterSurface.overlayLayerIndex}:${waterSurface.overlayZMeters}:${this.threshold}:${this.hubView}`;
  }

  private async compute(): Promise<void> {
    const modelId = waterSurface.modelId;
    if (!modelId || this.vertices.length < 3) {
      return;
    }
    const token = ++this.token;
    const key = this.queryKey();
    this.loading = true;
    this.error = null;
    this.notify();
    try {
      const ring = this.vertices.map((v) => [v.lon, v.lat] as [number, number]);
      const stats = await fetchPolygonStats(
        modelId,
        ring,
        waterSurface.timeIndex,
        waterSurface.variable,
        waterSurface.overlayLayerIndex,
        waterSurface.overlayZMeters,
        this.threshold,
      );
      if (token !== this.token) {
        return;
      }
      this.stats = stats;
      this.lastQueryKey = key;
    } catch (error) {
      if (token !== this.token) {
        return;
      }
      this.stats = null;
      this.error = error instanceof Error ? error.message : "Polygon stats failed";
    } finally {
      if (token === this.token) {
        this.loading = false;
        this.notify();
      }
    }
  }

  private dropOverlay(): void {
    if (this.overlayEntity && this.viewer && !this.viewer.isDestroyed()) {
      this.viewer.entities.remove(this.overlayEntity);
    }
    this.overlayEntity = null;
    if (this.overlayUrl) {
      URL.revokeObjectURL(this.overlayUrl);
      this.overlayUrl = null;
    }
  }

  private async showOverlay(): Promise<void> {
    const viewer = this.viewer;
    const modelId = waterSurface.modelId;
    if (!viewer || viewer.isDestroyed() || !modelId || this.vertices.length < 3) {
      return;
    }
    const token = this.token;
    const ring = this.vertices.map((v) => [v.lon, v.lat] as [number, number]);
    try {
      const { blob, extent: headerExtent } = await fetchPolygonThreshold(
        modelId,
        ring,
        waterSurface.timeIndex,
        waterSurface.variable,
        waterSurface.overlayLayerIndex,
        waterSurface.overlayZMeters,
        this.threshold,
      );
      if (token !== this.token || viewer.isDestroyed()) {
        return;
      }
      const extent = this.stats?.extent ?? headerExtent;
      if (![extent?.west, extent?.south, extent?.east, extent?.north].every(Number.isFinite)) {
        this.error = "Threshold map has no geographic extent";
        this.notify();
        return;
      }
      this.dropOverlay();
      const url = URL.createObjectURL(blob);
      this.overlayUrl = url;
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("Threshold image failed to decode"));
        img.src = url;
      });
      if (token !== this.token || viewer.isDestroyed()) {
        URL.revokeObjectURL(url);
        return;
      }
      const rectangle = Rectangle.fromDegrees(extent.west, extent.south, extent.east, extent.north);
      this.overlayEntity = viewer.entities.add({
        rectangle: {
          coordinates: rectangle,
          material: new ImageMaterialProperty({
            image,
            transparent: true,
            color: Color.WHITE,
          }),
          height: DRAW_HEIGHT + 4,
          heightReference: HeightReference.NONE,
          outline: false,
        },
      });
      viewer.scene.requestRender();
    } catch (error) {
      if (token !== this.token) {
        return;
      }
      this.error = error instanceof Error ? error.message : "Threshold map failed";
      this.notify();
    }
  }

  private cartesians(): Cartesian3[] {
    return this.vertices.map((v) => Cartesian3.fromDegrees(v.lon, v.lat, DRAW_HEIGHT));
  }

  private rebuildGraphics(): void {
    this.removeGraphics();
    if (!this.viewer || this.viewer.isDestroyed() || this.vertices.length === 0) {
      return;
    }
    const pts = this.cartesians();
    this.dots = pts.map((position) =>
      this.viewer!.entities.add({
        position,
        point: {
          pixelSize: 10,
          color: LINE,
          outlineColor: Color.WHITE,
          outlineWidth: 2,
          heightReference: HeightReference.NONE,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      }),
    );
    if (pts.length >= 2) {
      const closed = this.closed && pts.length >= 3;
      this.line = this.viewer.entities.add({
        polyline: {
          positions: new CallbackProperty(() => {
            const now = this.cartesians();
            return closed && now.length ? [...now, now[0]] : now;
          }, false),
          width: 2.5,
          material: LINE,
          clampToGround: false,
        },
      });
    }
    if (this.closed && pts.length >= 3) {
      this.fill = this.viewer.entities.add({
        polygon: {
          hierarchy: new CallbackProperty(
            () => new PolygonHierarchy(this.cartesians()),
            false,
          ),
          material: this.analysed ? FILL_ANALYSED : FILL,
          outline: false,
          height: DRAW_HEIGHT,
          heightReference: HeightReference.NONE,
        },
      });
    }
  }

  private removeGraphics(): void {
    if (!this.viewer || this.viewer.isDestroyed()) {
      this.line = null;
      this.fill = null;
      this.dots = [];
      return;
    }
    if (this.line) {
      this.viewer.entities.remove(this.line);
    }
    if (this.fill) {
      this.viewer.entities.remove(this.fill);
    }
    for (const dot of this.dots) {
      this.viewer.entities.remove(dot);
    }
    this.line = null;
    this.fill = null;
    this.dots = [];
  }

  private setCursor(value: string): void {
    if (!this.viewer || this.viewer.isDestroyed()) {
      return;
    }
    this.viewer.scene.canvas.style.cursor = value;
  }
}

export const polygonStore = new PolygonStore();

function pickLonLat(viewer: Viewer, position: { x: number; y: number }): LonLat | null {
  const cartesian = viewer.camera.pickEllipsoid(
    Cartesian2.fromElements(position.x, position.y),
    viewer.scene.globe.ellipsoid,
  );
  if (!cartesian) {
    return null;
  }
  const carto = Cartographic.fromCartesian(cartesian);
  return {
    lon: CesiumMath.toDegrees(carto.longitude),
    lat: CesiumMath.toDegrees(carto.latitude),
  };
}

export function attachPolygonDrawer(viewer: Viewer): () => void {
  polygonStore.attach(viewer);
  const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((click: { position: { x: number; y: number } }) => {
    if (!polygonStore.drawing) {
      return;
    }
    const ll = pickLonLat(viewer, click.position);
    if (ll) {
      polygonStore.addVertex(ll.lon, ll.lat);
    }
  }, ScreenSpaceEventType.LEFT_CLICK);
  handler.setInputAction(() => {
    if (polygonStore.drawing) {
      polygonStore.undo();
    }
  }, ScreenSpaceEventType.RIGHT_CLICK);

  const onKey = (event: KeyboardEvent) => {
    if (!polygonStore.drawing) {
      return;
    }
    if (event.key === "Escape") {
      polygonStore.cancel();
    }
    if (event.key === "Enter") {
      void polygonStore.finish();
    }
  };
  window.addEventListener("keydown", onKey);
  const unsubWater = waterSurface.subscribe(() => polygonStore.refreshIfStale());

  return () => {
    window.removeEventListener("keydown", onKey);
    unsubWater();
    handler.destroy();
    polygonStore.detach();
  };
}
