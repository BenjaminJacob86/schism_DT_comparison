import {
  BillboardCollection,
  Cartesian3,
  Credit,
  Event as CesiumEvent,
  GeographicTilingScheme,
  HorizontalOrigin,
  ImageryLayer,
  Math as CesiumMath,
  NeverTileDiscardPolicy,
  Rectangle,
  TextureMagnificationFilter,
  TextureMinificationFilter,
  VerticalOrigin,
  type Viewer,
} from "cesium";

import { fetchVectorField, overlayTilesUrl, VECTOR_N_ARROWS } from "@/api/client";
import type { ModelMetadata, VariableMeta } from "@/model/types";

/** Use this many extra Cesium tile zooms vs the camera LOD, then drape the finer PNG. */
const OVERLAY_ZOOM_BIAS = 1;
const OVERLAY_MAX_LEVEL = 19;
const OVERLAY_TILE_PX = 256;

export type HydroExtent = {
  west: number;
  south: number;
  east: number;
  north: number;
};

type Listener = () => void;

/** Cesium GeographicTilingScheme: 2×1 tiles at level 0, y=0 is north. */
function geographicTileXY(level: number, lon: number, lat: number): { x: number; y: number } {
  const tilesX = 2 << level;
  const tilesY = 1 << level;
  return {
    x: Math.min(tilesX - 1, Math.max(0, Math.floor(((lon + 180) / 360) * tilesX))),
    y: Math.min(tilesY - 1, Math.max(0, Math.floor(((90 - lat) / 180) * tilesY))),
  };
}

function clipBox(view: HydroExtent, model: HydroExtent): HydroExtent | null {
  const west = Math.max(view.west, model.west);
  const east = Math.min(view.east, model.east);
  const south = Math.max(view.south, model.south);
  const north = Math.min(view.north, model.north);
  if (east <= west || north <= south) {
    return null;
  }
  return { west, south, east, north };
}

function squareView(view: HydroExtent, model: HydroExtent): HydroExtent {
  const box = clipBox(view, model) ?? model;
  const cx = (box.west + box.east) / 2;
  const cy = (box.south + box.north) / 2;
  const half = 0.5 * Math.max(box.east - box.west, box.north - box.south, 1e-5);
  return { west: cx - half, south: cy - half, east: cx + half, north: cy + half };
}

function cameraView(viewer: Viewer, model: HydroExtent): HydroExtent {
  const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
  if (!rect) {
    return squareView(model, model);
  }
  return squareView(
    {
      west: CesiumMath.toDegrees(rect.west),
      south: CesiumMath.toDegrees(rect.south),
      east: CesiumMath.toDegrees(rect.east),
      north: CesiumMath.toDegrees(rect.north),
    },
    model,
  );
}

function overlayTileUrl(template: string, z: number, x: number, y: number): string {
  return template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
}

function loadOverlayImage(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

async function requestBiasedOverlayImage(
  template: string,
  x: number,
  y: number,
  level: number,
): Promise<HTMLCanvasElement> {
  const z = Math.min(level + OVERLAY_ZOOM_BIAS, OVERLAY_MAX_LEVEL);
  const steps = 1 << Math.max(0, z - level);
  const out = OVERLAY_TILE_PX << OVERLAY_ZOOM_BIAS;
  const cell = Math.floor(out / steps);
  const canvas = document.createElement("canvas");
  canvas.width = out;
  canvas.height = out;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return canvas;
  }
  const jobs: Array<Promise<void>> = [];
  for (let dy = 0; dy < steps; dy += 1) {
    for (let dx = 0; dx < steps; dx += 1) {
      const url = overlayTileUrl(template, z, x * steps + dx, y * steps + dy);
      jobs.push(
        loadOverlayImage(url).then((image) => {
          if (image) {
            ctx.drawImage(image, dx * cell, dy * cell, cell, cell);
          }
        }),
      );
    }
  }
  await Promise.all(jobs);
  return canvas;
}

class ZoomBiasedOverlayProvider {
  readonly tilingScheme = new GeographicTilingScheme();
  readonly rectangle: Rectangle;
  readonly tileWidth = OVERLAY_TILE_PX << OVERLAY_ZOOM_BIAS;
  readonly tileHeight = OVERLAY_TILE_PX << OVERLAY_ZOOM_BIAS;
  readonly minimumLevel: number;
  readonly maximumLevel = OVERLAY_MAX_LEVEL;
  readonly hasAlphaChannel = true;
  readonly credit: Credit;
  readonly tileDiscardPolicy = new NeverTileDiscardPolicy();
  readonly errorEvent = new CesiumEvent();
  readonly ready = true;
  private readonly template: string;

  constructor(template: string, rectangle: Rectangle, minimumLevel: number, credit: string) {
    this.template = template;
    this.rectangle = rectangle;
    this.minimumLevel = minimumLevel;
    this.credit = new Credit(credit, false);
  }

  getTileCredits(): undefined {
    return undefined;
  }

  pickFeatures(): undefined {
    return undefined;
  }

  requestImage(x: number, y: number, level: number): Promise<HTMLCanvasElement> {
    return requestBiasedOverlayImage(this.template, x, y, level);
  }
}

function tileWidthDeg(level: number): number {
  return 360 / (2 << level);
}

function minLevelForExtent(extent: HydroExtent): number {
  const span = Math.max(extent.east - extent.west, extent.north - extent.south, 0.05);
  let level = 4;
  while (level < 12 && tileWidthDeg(level) > span * 1.25) {
    level += 1;
  }
  return level;
}

function levelForSpan(spanDeg: number): number {
  let level = 4;
  while (level < 10 && tileWidthDeg(level) > spanDeg * 0.35) {
    level += 1;
  }
  return level;
}

function tilesCovering(level: number, box: HydroExtent, cap: number): Array<{ z: number; x: number; y: number }> {
  const tilesX = 2 << level;
  const tilesY = 1 << level;
  const x0 = Math.max(0, Math.floor(((box.west + 180) / 360) * tilesX));
  const x1 = Math.min(tilesX - 1, Math.floor(((box.east + 180 - 1e-9) / 360) * tilesX));
  const y0 = Math.max(0, Math.floor(((90 - box.north) / 180) * tilesY));
  const y1 = Math.min(tilesY - 1, Math.floor(((90 - box.south - 1e-9) / 180) * tilesY));
  const out: Array<{ z: number; x: number; y: number }> = [];
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      out.push({ z: level, x, y });
      if (out.length >= cap) {
        return out;
      }
    }
  }
  return out;
}

async function fetchAll(urls: string[], concurrency: number, alive: () => boolean): Promise<void> {
  let i = 0;
  const workers = Array.from({ length: Math.min(concurrency, urls.length) }, async () => {
    while (alive() && i < urls.length) {
      const url = urls[i];
      i += 1;
      try {
        await fetch(url, { cache: "force-cache" });
      } catch {
        /* keep going so play still starts */
      }
    }
  });
  await Promise.all(workers);
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

function paddedRectangle(extent: HydroExtent): Rectangle {
  const spanW = Math.max(extent.east - extent.west, 0.15);
  const spanH = Math.max(extent.north - extent.south, 0.1);
  const pad = 0.08;
  return Rectangle.fromDegrees(
    extent.west - spanW * pad,
    extent.south - spanH * pad,
    extent.east + spanW * pad,
    extent.north + spanH * pad,
  );
}

export function formatHydroTime(seconds: number, index: number, nTimes: number): string {
  const day = Math.floor(seconds / 86_400) + 1;
  const hour = Math.floor((seconds % 86_400) / 3_600);
  return `Day ${day} · ${String(hour).padStart(2, "0")}:00  (${index + 1}/${nTimes})`;
}

/** Speed 1 = slow (~1.5 s/hour), 5 = default (~0.4 s), 10 = fast (~0.12 s). */
export function holdMsForSpeed(speed: number): number {
  const t = Math.max(1, Math.min(10, speed));
  if (t <= 5) {
    return Math.round(1500 - (t - 1) * ((1500 - 420) / 4));
  }
  return Math.round(420 - (t - 5) * ((420 - 120) / 5));
}

let arrowIcon: HTMLCanvasElement | null = null;

function arrowImage(): HTMLCanvasElement {
  if (arrowIcon) {
    return arrowIcon;
  }
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return canvas;
  }
  ctx.translate(32, 32);
  ctx.fillStyle = "rgba(255,255,255,0.95)";
  ctx.strokeStyle = "rgba(12,20,28,0.9)";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.moveTo(0, -26);
  ctx.lineTo(11, 10);
  ctx.lineTo(3.5, 5);
  ctx.lineTo(3.5, 26);
  ctx.lineTo(-3.5, 26);
  ctx.lineTo(-3.5, 5);
  ctx.lineTo(-11, 10);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  arrowIcon = canvas;
  return canvas;
}

function paintQuiver(
  billboards: BillboardCollection,
  lon: number[],
  lat: number[],
  u: number[],
  v: number[],
  refSpeed: number,
): void {
  billboards.removeAll();
  const image = arrowImage();
  const ref = Math.max(refSpeed, 0.5);
  const z = Cartesian3.UNIT_Z;
  for (let i = 0; i < lon.length; i++) {
    const speed = Math.hypot(u[i], v[i]);
    if (!Number.isFinite(lon[i]) || !Number.isFinite(lat[i]) || !Number.isFinite(speed)) {
      continue;
    }
    const scale = 0.5 + 0.6 * Math.min(speed / ref, 1);
    billboards.add({
      position: Cartesian3.fromDegrees(lon[i], lat[i], 20),
      image,
      rotation: -Math.atan2(u[i], v[i]),
      alignedAxis: z,
      width: 26 * scale,
      height: 34 * scale,
      horizontalOrigin: HorizontalOrigin.CENTER,
      verticalOrigin: VerticalOrigin.CENTER,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });
  }
}

export class WaterSurfaceRenderer {
  private viewer: Viewer | null = null;
  private overlayLayer: ImageryLayer | null = null;
  private incomingOverlay: ImageryLayer | null = null;
  private overlayToken = 0;
  private syncWaiters: Array<() => void> = [];
  private meta: ModelMetadata | null = null;
  private readonly listeners = new Set<Listener>();
  private desiredIndex = 0;
  private loadedIndex = -1;
  private syncing = false;
  private colorTimer: number | undefined;
  timeIndex = 0;
  visible = true;
  modelId = "";
  overlayReady = false;
  fetching = false;
  buffering = false;
  playbackBuffered = false;
  playSpeed = 5;
  private bufferToken = 0;
  colorMin: number | null = null;
  colorMax: number | null = null;
  variable = "elevation";
  colormap = "haline";
  colormapCss =
    "linear-gradient(90deg, rgb(42, 24, 108), rgb(31, 98, 164), rgb(32, 163, 168), rgb(128, 201, 116), rgb(253, 231, 103))";
  hubView = "";
  layerIndex = -1;
  zInterp = false;
  zMeters = -2;
  private colormapCssById = new Map<string, string>();
  private quiver: BillboardCollection | null = null;
  private unbindCamera: (() => void) | null = null;
  private quiverTimer: number | undefined;
  private quiverToken = 0;
  private cameraMoving = false;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async attachOverview(viewer: Viewer, meta: ModelMetadata): Promise<void> {
    this.removeOverlay();
    this.viewer = viewer;
    const keepVariable = this.variable;
    const keepTime = this.timeIndex;
    const keepLayer = this.layerIndex;
    const keepZInterp = this.zInterp;
    const keepZMeters = this.zMeters;
    const keepColormap = this.colormap;
    this.meta = meta;
    this.modelId = meta.id;
    this.bindCamera(viewer);
    const ids = new Set([
      ...(meta.variableMeta?.map((item) => item.id) ?? []),
      ...(meta.variables ?? []),
    ]);
    this.variable = ids.has(keepVariable)
      ? keepVariable
      : (meta.defaultVariable ?? meta.variableMeta?.[0]?.id ?? "elevation");
    const active = this.activeVariable;
    this.colorMin = active?.min ?? meta.elevationMin;
    this.colorMax = active?.max ?? meta.elevationMax;
    this.colormap = keepColormap;
    const nLayers = active?.nLayers ?? 0;
    if (ids.has(keepVariable) && nLayers > 1) {
      this.layerIndex = Math.max(0, Math.min(nLayers - 1, keepLayer < 0 ? nLayers - 1 : keepLayer));
      this.zInterp = keepZInterp;
      this.zMeters = keepZMeters;
    } else {
      this.layerIndex = this.surfaceLayer(active);
      this.zInterp = false;
    }
    const t = Math.max(0, Math.min(Math.max(meta.nTimes, 1) - 1, keepTime));
    this.timeIndex = t;
    this.desiredIndex = t;
    this.loadedIndex = -1;
    this.overlayReady = false;
    this.fetching = true;
    this.invalidatePlaybackBuffer();
    this.notify();
    this.zoomToData(false);
    await this.setOverlay(t);
    this.loadedIndex = t;
    this.timeIndex = t;
    this.notify();
    void this.syncStep();
  }

  setColorRange(vmin: number, vmax: number): void {
    const lo = Math.round(Math.min(vmin, vmax) * 100) / 100;
    const hi = Math.round(Math.max(vmin, vmax) * 100) / 100;
    this.colorMin = lo;
    this.colorMax = Math.max(hi, lo + 0.02);
    this.notify();
    if (this.colorTimer !== undefined) {
      window.clearTimeout(this.colorTimer);
    }
    this.colorTimer = window.setTimeout(() => {
      this.colorTimer = undefined;
      void this.applyColorRange();
    }, 280);
  }

  resetColorRange(): void {
    const active = this.activeVariable;
    if (!active && !this.meta) {
      return;
    }
    if (this.hubView === "diff") {
      const span = this.diffSpan();
      this.setColorRange(-span, span);
      return;
    }
    this.setColorRange(
      active?.min ?? this.meta!.elevationMin,
      active?.max ?? this.meta!.elevationMax,
    );
  }

  setVariable(variable: string): void {
    if (!this.meta || variable === this.variable) {
      return;
    }
    const next = this.meta.variableMeta?.find((item) => item.id === variable);
    if (!next && this.meta.variables.length && !this.meta.variables.includes(variable)) {
      return;
    }
    this.variable = variable;
    if (this.hubView === "diff") {
      const span = this.diffSpan();
      this.colorMin = -span;
      this.colorMax = span;
    } else {
      this.colorMin = next?.min ?? this.meta.elevationMin;
      this.colorMax = next?.max ?? this.meta.elevationMax;
    }
    this.layerIndex = this.surfaceLayer(next);
    this.zInterp = false;
    this.notify();
    void this.applyColorRange();
  }

  setLayer(layer: number): void {
    if (!this.isVertical) {
      return;
    }
    const k = Math.max(0, Math.min(this.nLayers - 1, Math.round(layer)));
    if (k === this.layerIndex && !this.zInterp) {
      return;
    }
    this.layerIndex = k;
    this.zInterp = false;
    this.notify();
    void this.applyColorRange();
  }

  setZInterp(enabled: boolean, zMeters?: number): void {
    if (!this.isVertical) {
      return;
    }
    this.zInterp = enabled;
    if (zMeters !== undefined && Number.isFinite(zMeters)) {
      this.zMeters = zMeters;
    }
    this.notify();
    void this.applyColorRange();
  }

  setZMeters(zMeters: number): void {
    if (!this.isVertical || !Number.isFinite(zMeters)) {
      return;
    }
    this.zMeters = zMeters;
    if (this.zInterp) {
      this.notify();
      void this.applyColorRange();
    } else {
      this.notify();
    }
  }

  registerColormaps(items: Array<{ id: string; css: string }>): void {
    for (const item of items) {
      if (item.id && item.css) {
        this.colormapCssById.set(item.id, item.css);
      }
    }
  }

  applyHubView(view: string): void {
    this.hubView = view;
    if (view !== "diff") {
      this.notify();
      return;
    }
    const css = this.colormapCssById.get("balance");
    if (css) {
      this.colormapCss = css;
    }
    this.colormap = "balance";
    const span = this.diffSpan();
    this.colorMin = -span;
    this.colorMax = span;
    this.notify();
    void this.applyColorRange();
  }

  setColormap(colormap: string, css?: string): void {
    const gradient = css || this.colormapCssById.get(colormap);
    if (gradient) {
      this.colormapCss = gradient;
    }
    const same = colormap === this.colormap;
    if (same) {
      this.notify();
      return;
    }
    this.colormap = colormap;
    this.notify();
    void this.applyColorRange();
  }

  private async applyColorRange(): Promise<void> {
    this.invalidatePlaybackBuffer();
    const t = this.loadedIndex >= 0 ? this.loadedIndex : this.desiredIndex;
    await this.setOverlay(t);
    this.notify();
  }

  async prefetchPlayback(): Promise<boolean> {
    if (!this.meta || this.nTimes < 2 || !this.modelId) {
      return false;
    }
    const token = ++this.bufferToken;
    this.buffering = true;
    this.fetching = true;
    this.playbackBuffered = false;
    this.notify();
    const tiles = this.visiblePlaybackTiles();
    const n = this.nTimes;
    try {
      if (tiles.length) {
        for (let t = 0; t < n; t++) {
          if (token !== this.bufferToken) {
            return false;
          }
          const tmpl = this.overlayTemplate(t);
          const frameUrls = tiles.map((tile) =>
            tmpl.replace("{z}", String(tile.z)).replace("{x}", String(tile.x)).replace("{y}", String(tile.y)),
          );
          await fetchAll(frameUrls, 4, () => token === this.bufferToken);
        }
      }
      if (token !== this.bufferToken) {
        return false;
      }
      this.playbackBuffered = true;
      return true;
    } finally {
      if (token === this.bufferToken) {
        this.buffering = false;
        this.fetching = false;
        this.notify();
      }
    }
  }

  cancelPlaybackBuffer(): void {
    this.bufferToken += 1;
    this.buffering = false;
    this.fetching = false;
    this.notify();
  }

  setTime(index: number): void {
    if (!this.meta || this.meta.nTimes < 1) {
      return;
    }
    this.desiredIndex = Math.max(0, Math.min(this.meta.nTimes - 1, index));
    this.timeIndex = this.desiredIndex;
    this.notify();
    void this.syncStep();
  }

  async advancePlayback(): Promise<void> {
    if (!this.meta || this.nTimes < 2) {
      return;
    }
    await this.whenIdle();
    if (!this.meta || this.nTimes < 2) {
      return;
    }
    const current = this.loadedIndex >= 0 ? this.loadedIndex : this.timeIndex;
    this.desiredIndex = (current + 1) % this.nTimes;
    this.notify();
    await this.syncStep();
  }

  async seekAndWait(index: number): Promise<void> {
    if (!this.meta || this.nTimes < 1) {
      return;
    }
    await this.whenIdle();
    if (!this.meta || this.nTimes < 1) {
      return;
    }
    this.desiredIndex = Math.max(0, Math.min(this.nTimes - 1, Math.round(index)));
    this.timeIndex = this.desiredIndex;
    this.notify();
    await this.syncStep();
  }

  setPlaySpeed(speed: number): void {
    const next = Math.max(1, Math.min(10, Math.round(speed)));
    if (next === this.playSpeed) {
      return;
    }
    this.playSpeed = next;
    this.notify();
  }

  get playHoldMs(): number {
    return holdMsForSpeed(this.playSpeed);
  }

  async waitUntilFrameReady(index: number): Promise<boolean> {
    await this.seekAndWait(index);
    const viewer = this.viewer;
    if (!viewer || viewer.isDestroyed()) {
      return false;
    }
    if (this.loadedIndex !== index || !this.overlayReady || !this.overlayLayer) {
      return false;
    }
    const start = performance.now();
    const timeout = this.playbackBuffered ? 2_000 : 8_000;
    let queued = 0;
    let sawWork = false;
    const remove = viewer.scene.globe.tileLoadProgressEvent.addEventListener((count: number) => {
      queued = count;
      if (count > 0) {
        sawWork = true;
      }
    });
    try {
      while (!viewer.isDestroyed() && performance.now() - start < timeout) {
        viewer.scene.render();
        await nextFrame();
        if (this.incomingOverlay) {
          continue;
        }
        if (sawWork && queued === 0) {
          break;
        }
        if (!sawWork && performance.now() - start > 400 && viewer.scene.globe.tilesLoaded) {
          break;
        }
      }
    } finally {
      remove();
    }
    viewer.scene.render();
    await nextFrame();
    viewer.scene.render();
    await nextFrame();
    return (
      this.loadedIndex === index &&
      this.overlayReady &&
      Boolean(this.overlayLayer && !this.overlayLayer.isDestroyed()) &&
      !this.incomingOverlay
    );
  }

  setVisible(value: boolean): void {
    this.visible = value;
    if (this.overlayLayer && !this.overlayLayer.isDestroyed()) {
      this.overlayLayer.show = value;
    }
    if (this.incomingOverlay && !this.incomingOverlay.isDestroyed()) {
      this.incomingOverlay.show = value;
    }
    if (this.quiver && !this.quiver.isDestroyed()) {
      this.quiver.show = value;
    }
  }

  zoomToData(fly = true): void {
    const extent = this.meta?.extent;
    if (!this.viewer || this.viewer.isDestroyed() || !extent) {
      return;
    }
    const destination = paddedRectangle(extent);
    if (fly) {
      this.viewer.camera.flyTo({ destination, duration: 1.6 });
    } else {
      this.viewer.camera.setView({ destination });
    }
  }

  handleRenderError(): void {
    this.removeOverlay();
  }

  get nTimes(): number {
    return this.meta?.nTimes ?? 0;
  }

  get name(): string {
    return this.meta?.name ?? "";
  }

  get timeSeconds(): number[] {
    const n = this.nTimes;
    const dt = this.meta?.dtSeconds ?? 3600;
    const start = this.meta?.timeStartSeconds ?? dt;
    return Array.from({ length: n }, (_, i) => start + i * dt);
  }

  get elevMin(): number | null {
    return this.activeVariable?.min ?? this.meta?.elevationMin ?? null;
  }

  get elevMax(): number | null {
    return this.activeVariable?.max ?? this.meta?.elevationMax ?? null;
  }

  diffSpan(): number {
    const lo = this.elevMin ?? 1;
    const hi = this.elevMax ?? 1;
    return Math.max(Math.abs(lo), Math.abs(hi), 0.25);
  }

  get colorScaleMin(): number | null {
    return this.hubView === "diff" ? -this.diffSpan() : this.elevMin;
  }

  get colorScaleMax(): number | null {
    return this.hubView === "diff" ? this.diffSpan() : this.elevMax;
  }

  get activeVariable(): VariableMeta | null {
    const vars = this.meta?.variableMeta ?? [];
    return vars.find((item) => item.id === this.variable) ?? vars[0] ?? null;
  }

  get variables(): VariableMeta[] {
    return this.meta?.variableMeta ?? [];
  }

  get variableLabel(): string {
    return this.activeVariable?.label ?? "Water level";
  }

  get variableUnit(): string {
    return this.activeVariable?.unit ?? "m";
  }

  get isVertical(): boolean {
    return Boolean(this.activeVariable?.vertical && (this.activeVariable.nLayers ?? 0) > 1);
  }

  get nLayers(): number {
    return this.activeVariable?.nLayers ?? this.meta?.nLayers ?? 0;
  }

  get overlayLayerIndex(): number | null {
    if (!this.isVertical || this.zInterp) {
      return null;
    }
    return this.layerIndex >= 0 ? this.layerIndex : this.nLayers - 1;
  }

  get overlayZMeters(): number | null {
    return this.isVertical && this.zInterp ? this.zMeters : null;
  }

  private surfaceLayer(meta: VariableMeta | null | undefined): number {
    const n = meta?.nLayers ?? 0;
    return n > 0 ? n - 1 : -1;
  }

  get nNodes(): number {
    return this.meta?.nNodes ?? 0;
  }

  get nTriangles(): number {
    return this.meta?.nTriangles ?? 0;
  }

  get coordSource(): string {
    return this.meta?.coordSource ?? "";
  }

  get subset(): string {
    return this.meta?.subset ?? "";
  }

  get extent(): HydroExtent | null {
    return this.meta?.extent ?? null;
  }

  get ready(): boolean {
    return this.overlayReady;
  }

  detach(): void {
    this.unbindCamera?.();
    this.unbindCamera = null;
    if (this.quiverTimer !== undefined) {
      window.clearTimeout(this.quiverTimer);
      this.quiverTimer = undefined;
    }
    this.removeOverlay();
    this.clearQuiver();
    this.viewer = null;
    this.meta = null;
    this.modelId = "";
    this.timeIndex = 0;
    this.desiredIndex = 0;
    this.loadedIndex = -1;
    this.overlayReady = false;
    this.fetching = false;
    this.invalidatePlaybackBuffer();
    this.colorMin = null;
    this.colorMax = null;
    this.variable = "elevation";
    this.colormap = "haline";
    this.layerIndex = -1;
    this.zInterp = false;
    if (this.colorTimer !== undefined) {
      window.clearTimeout(this.colorTimer);
      this.colorTimer = undefined;
    }
    this.notify();
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  private whenIdle(): Promise<void> {
    if (!this.syncing) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      this.syncWaiters.push(resolve);
    });
  }

  private async syncStep(): Promise<void> {
    if (this.syncing) {
      await this.whenIdle();
      if (this.meta && this.modelId && this.desiredIndex !== this.loadedIndex && !this.syncing) {
        await this.syncStep();
      }
      return;
    }
    if (!this.meta || !this.modelId) {
      return;
    }
    this.syncing = true;
    try {
      while (this.meta && this.desiredIndex !== this.loadedIndex) {
        const t = this.desiredIndex;
        await this.setOverlay(t, { silent: this.playbackBuffered });
        if (!this.meta || t !== this.desiredIndex) {
          continue;
        }
        this.loadedIndex = t;
        this.timeIndex = t;
        this.notify();
      }
    } catch (error) {
      console.warn("Hydro timestep failed:", error);
    } finally {
      this.syncing = false;
      const waiters = this.syncWaiters.splice(0);
      for (const waiter of waiters) {
        waiter();
      }
    }
  }

  private overlayTemplate(timeIndex: number): string {
    const vmin = this.colorMin ?? this.activeVariable?.min ?? this.meta?.elevationMin;
    const vmax = this.colorMax ?? this.activeVariable?.max ?? this.meta?.elevationMax;
    return overlayTilesUrl(
      this.modelId,
      timeIndex,
      vmin,
      vmax,
      this.variable,
      this.colormap,
      this.overlayLayerIndex,
      this.overlayZMeters,
    );
  }

  private visiblePlaybackTiles(): Array<{ z: number; x: number; y: number }> {
    const extent = this.meta?.extent;
    if (!extent) {
      return [];
    }
    let view: HydroExtent = extent;
    const viewer = this.viewer;
    if (viewer && !viewer.isDestroyed()) {
      const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
      if (rect) {
        view = {
          west: CesiumMath.toDegrees(rect.west),
          south: CesiumMath.toDegrees(rect.south),
          east: CesiumMath.toDegrees(rect.east),
          north: CesiumMath.toDegrees(rect.north),
        };
      }
    }
    const box = clipBox(view, extent) ?? extent;
    const span = Math.max(box.east - box.west, box.north - box.south, 0.05);
    const level = Math.min(OVERLAY_MAX_LEVEL, levelForSpan(span) + OVERLAY_ZOOM_BIAS);
    const tiles = tilesCovering(level, box, 16);
    const floor = Math.min(OVERLAY_MAX_LEVEL, minLevelForExtent(extent) + OVERLAY_ZOOM_BIAS);
    if (level > floor) {
      tiles.push(...tilesCovering(Math.max(floor, level - 1), box, 4));
    }
    return tiles;
  }

  private invalidatePlaybackBuffer(): void {
    this.bufferToken += 1;
    this.playbackBuffered = false;
    this.buffering = false;
  }

  private async setOverlay(timeIndex: number, options?: { silent?: boolean }): Promise<void> {
    const silent = Boolean(options?.silent);
    if (!silent) {
      this.fetching = true;
      this.notify();
    }
    if (!this.viewer || this.viewer.isDestroyed() || !this.meta?.extent) {
      if (!silent) {
        this.fetching = false;
        this.notify();
      }
      return;
    }
    const token = ++this.overlayToken;
    const viewer = this.viewer;
    const extent = this.meta.extent;
    const rectangle = Rectangle.fromDegrees(extent.west, extent.south, extent.east, extent.north);
    const tileUrl = this.overlayTemplate(timeIndex);
    try {
      const minLevel = minLevelForExtent(extent);
      const probeLevel = Math.min(OVERLAY_MAX_LEVEL, minLevel + OVERLAY_ZOOM_BIAS);
      if (!silent) {
        const midLon = (extent.west + extent.east) / 2;
        const midLat = (extent.south + extent.north) / 2;
        const { x, y } = geographicTileXY(probeLevel, midLon, midLat);
        const probe = overlayTileUrl(tileUrl, probeLevel, x, y);
        try {
          await fetch(probe);
        } catch {
          /* Cesium still requests the pyramid after the layer is added. */
        }
      }
      if (token !== this.overlayToken || viewer.isDestroyed() || this.viewer !== viewer) {
        return;
      }
      const provider = new ZoomBiasedOverlayProvider(
        tileUrl,
        rectangle,
        minLevel,
        `SCHISM ${this.variableLabel}`,
      );
      const previous = this.overlayLayer;
      const layer = viewer.imageryLayers.addImageryProvider(provider);
      layer.show = this.visible;
      layer.alpha = 0.92;
      layer.minificationFilter = TextureMinificationFilter.NEAREST;
      layer.magnificationFilter = TextureMagnificationFilter.NEAREST;
      this.incomingOverlay = layer;
      await this.waitForOverlayPaint(viewer, token, silent ? 700 : 8000);
      if (token !== this.overlayToken || viewer.isDestroyed() || this.viewer !== viewer) {
        this.dropLayer(layer);
        if (this.incomingOverlay === layer) {
          this.incomingOverlay = null;
        }
        return;
      }
      this.overlayLayer = layer;
      this.incomingOverlay = null;
      this.overlayReady = true;
      if (previous && previous !== layer) {
        this.dropLayer(previous);
      }
      viewer.scene.requestRender();
      void this.refreshQuiver();
    } finally {
      if (token === this.overlayToken && !silent) {
        this.fetching = false;
        this.notify();
      }
    }
  }

  private async waitForOverlayPaint(viewer: Viewer, token: number, timeoutMs: number): Promise<void> {
    const start = performance.now();
    const maxFrames = timeoutMs <= 1000 ? 12 : 240;
    let frames = 0;
    let queued = 0;
    let sawOverlayWork = false;
    const remove = viewer.scene.globe.tileLoadProgressEvent.addEventListener((count: number) => {
      queued = count;
      if (count > 0) {
        sawOverlayWork = true;
      }
    });
    try {
      while (token === this.overlayToken && !viewer.isDestroyed()) {
        viewer.scene.requestRender();
        await nextFrame();
        frames += 1;
        const elapsed = performance.now() - start;
        if (elapsed > timeoutMs) {
          break;
        }
        if (frames >= 3 && sawOverlayWork && queued === 0) {
          break;
        }
        if (frames >= 3 && !sawOverlayWork && frames >= Math.min(6, maxFrames)) {
          break;
        }
        if (frames >= maxFrames) {
          break;
        }
      }
    } finally {
      remove();
    }
    await nextFrame();
  }

  private dropLayer(layer: ImageryLayer | null): void {
    if (!layer || layer.isDestroyed() || !this.viewer || this.viewer.isDestroyed()) {
      return;
    }
    this.viewer.imageryLayers.remove(layer);
  }

  private removeOverlay(): void {
    this.dropLayer(this.incomingOverlay);
    this.dropLayer(this.overlayLayer);
    this.incomingOverlay = null;
    this.overlayLayer = null;
  }

  private bindCamera(viewer: Viewer): void {
    this.unbindCamera?.();
    this.cameraMoving = false;
    const start = viewer.camera.moveStart.addEventListener(() => {
      this.cameraMoving = true;
      if (this.quiverTimer !== undefined) {
        window.clearTimeout(this.quiverTimer);
        this.quiverTimer = undefined;
      }
      if (this.quiver && !this.quiver.isDestroyed()) {
        this.quiver.show = false;
      }
    });
    const end = viewer.camera.moveEnd.addEventListener(() => {
      this.cameraMoving = false;
      this.scheduleQuiver();
    });
    this.unbindCamera = () => {
      start();
      end();
    };
  }

  private scheduleQuiver(): void {
    if (this.cameraMoving) {
      return;
    }
    if (this.quiverTimer !== undefined) {
      window.clearTimeout(this.quiverTimer);
    }
    this.quiverTimer = window.setTimeout(() => {
      this.quiverTimer = undefined;
      void this.refreshQuiver();
    }, 250);
  }

  private clearQuiver(): void {
    this.quiverToken += 1;
    const viewer = this.viewer;
    if (this.quiver && viewer && !viewer.isDestroyed() && !this.quiver.isDestroyed()) {
      viewer.scene.primitives.remove(this.quiver);
    }
    this.quiver = null;
  }

  private async refreshQuiver(): Promise<void> {
    const viewer = this.viewer;
    const extent = this.meta?.extent;
    if (!viewer || viewer.isDestroyed() || !extent || !this.modelId) {
      return;
    }
    if (this.cameraMoving) {
      return;
    }
    if (!this.activeVariable?.vector || !this.visible) {
      this.clearQuiver();
      return;
    }
    const token = ++this.quiverToken;
    const view = cameraView(viewer, extent);
    try {
      const payload = await fetchVectorField(
        this.modelId,
        this.loadedIndex >= 0 ? this.loadedIndex : this.desiredIndex,
        view,
        this.variable,
        VECTOR_N_ARROWS,
        this.overlayLayerIndex,
        this.overlayZMeters,
      );
      if (token !== this.quiverToken || viewer.isDestroyed() || this.viewer !== viewer || this.cameraMoving) {
        return;
      }
      let quiver = this.quiver;
      if (!quiver || quiver.isDestroyed()) {
        quiver = new BillboardCollection({ scene: viewer.scene });
        viewer.scene.primitives.add(quiver);
        this.quiver = quiver;
      }
      quiver.show = this.visible;
      const ref = Math.abs(this.colorMax ?? this.activeVariable?.max ?? 1.5);
      paintQuiver(quiver, payload.lon, payload.lat, payload.u, payload.v, ref);
    } catch (error) {
      console.warn("Velocity quiver failed:", error);
    }
  }
}

export const waterSurface = new WaterSurfaceRenderer();
