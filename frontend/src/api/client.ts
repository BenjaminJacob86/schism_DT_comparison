import { env } from "@/config/env";
import { sourceRevision } from "@/api/storage";
import type { ModelMetadata } from "@/model/types";

const api = (path: string): string => `${env.apiBaseUrl}${path}`;

export type HydroExtent = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type MeshPayload = ModelMetadata & {
  lon: string;
  lat: string;
  tris: string;
  depth?: string;
  timeSeconds: number[];
  extent: HydroExtent;
  subset?: string;
  coordSource?: string;
};

export type StepPayload = {
  id: string;
  timeIndex: number;
  timeSeconds: number;
  elevation: string;
  dry: string;
};

export type SurfacePayload = MeshPayload & {
  elevation: string;
  dry: string;
};

export type ColormapMeta = {
  id: string;
  label: string;
  kind: "sequential" | "diverging" | "cyclic" | string;
  stops: string[];
  css: string;
};

export async function fetchColormaps(): Promise<ColormapMeta[]> {
  const response = await fetch(api("/api/models/colormaps"));
  if (!response.ok) {
    throw new Error(`Colormaps request failed: ${response.status}`);
  }
  return (await response.json()) as ColormapMeta[];
}

export async function fetchModels(): Promise<ModelMetadata[]> {
  const response = await fetch(api("/api/models"));
  if (!response.ok) {
    throw new Error(`Models request failed: ${response.status}`);
  }
  const models = (await response.json()) as ModelMetadata[];
  return models.filter((model) => model.id !== "sample_data2");
}

export function overlayUrl(
  modelId: string,
  timeIndex: number,
  vmin?: number,
  vmax?: number,
  variable?: string,
  colormap?: string,
  layer?: number | null,
  zMeters?: number | null,
): string {
  const params = new URLSearchParams({ v: "ugrid", src: String(sourceRevision) });
  if (vmin !== undefined) {
    params.set("vmin", String(vmin));
  }
  if (vmax !== undefined) {
    params.set("vmax", String(vmax));
  }
  if (variable) {
    params.set("variable", variable);
  }
  if (colormap) {
    params.set("colormap", colormap);
  }
  if (zMeters !== null && zMeters !== undefined && Number.isFinite(zMeters)) {
    params.set("z", String(zMeters));
  } else if (layer !== null && layer !== undefined) {
    params.set("layer", String(layer));
  }
  return `${api(`/api/models/${modelId}/overlay/${timeIndex}`)}?${params.toString()}`;
}

export function overlayTilesUrl(
  modelId: string,
  timeIndex: number,
  vmin?: number,
  vmax?: number,
  variable?: string,
  colormap?: string,
  layer?: number | null,
  zMeters?: number | null,
): string {
  const params = new URLSearchParams({ v: "ugrid-fill12", src: String(sourceRevision) });
  if (vmin !== undefined) {
    params.set("vmin", String(vmin));
  }
  if (vmax !== undefined) {
    params.set("vmax", String(vmax));
  }
  if (variable) {
    params.set("variable", variable);
  }
  if (colormap) {
    params.set("colormap", colormap);
  }
  if (zMeters !== null && zMeters !== undefined && Number.isFinite(zMeters)) {
    params.set("z", String(zMeters));
  } else if (layer !== null && layer !== undefined) {
    params.set("layer", String(layer));
  }
  return `${api(`/api/models/${modelId}/tiles/${timeIndex}/{z}/{x}/{y}.png`)}?${params.toString()}`;
}

export const VECTOR_N_ARROWS = 50;

export type VectorFieldPayload = {
  id: string;
  variable?: string;
  timeIndex?: number;
  nArrows: number;
  cell?: number;
  west?: number;
  south?: number;
  east?: number;
  north?: number;
  lon: number[];
  lat: number[];
  u: number[];
  v: number[];
};

export async function fetchVectorField(
  modelId: string,
  timeIndex: number,
  view: HydroExtent,
  variable?: string,
  n = VECTOR_N_ARROWS,
  layer?: number | null,
  zMeters?: number | null,
): Promise<VectorFieldPayload> {
  const params = new URLSearchParams({
    west: String(view.west),
    south: String(view.south),
    east: String(view.east),
    north: String(view.north),
    n: String(n),
  });
  if (variable) {
    params.set("variable", variable);
  }
  if (zMeters !== null && zMeters !== undefined && Number.isFinite(zMeters)) {
    params.set("z", String(zMeters));
  } else if (layer !== null && layer !== undefined) {
    params.set("layer", String(layer));
  }
  const response = await fetch(api(`/api/models/${modelId}/vectors/${timeIndex}?${params.toString()}`));
  if (!response.ok) {
    throw new Error(`Vector field request failed: ${response.status}`);
  }
  return (await response.json()) as VectorFieldPayload;
}

export async function fetchMesh(modelId: string): Promise<MeshPayload> {
  const response = await fetch(api(`/api/models/${modelId}/mesh`));
  if (!response.ok) {
    throw new Error(`Mesh request failed: ${response.status}`);
  }
  return (await response.json()) as MeshPayload;
}

export type SeriesPayload = {
  id: string;
  nodeIndex: number;
  lon: number;
  lat: number;
  distanceMeters: number;
  variable: string;
  label?: string;
  unit?: string;
  timeVarying?: boolean;
  vertical?: boolean;
  nLayers?: number | null;
  layer?: number | null;
  zMeters?: number | null;
  timeSeconds: number[];
  values?: Array<number | null>;
  elevation: Array<number | null>;
  compare?: {
    a: { id: string; label: string; values: Array<number | null> };
    b: { id: string; label: string; values: Array<number | null> };
  } | null;
  view?: "a" | "b" | "diff" | string | null;
  min?: number;
  max?: number;
  elevationMin: number;
  elevationMax: number;
};

export async function fetchSeries(
  modelId: string,
  lon: number,
  lat: number,
  variable?: string,
  layer?: number | null,
  zMeters?: number | null,
): Promise<SeriesPayload | null> {
  const params = new URLSearchParams({
    lon: lon.toFixed(6),
    lat: lat.toFixed(6),
  });
  if (variable) {
    params.set("variable", variable);
  }
  if (zMeters !== null && zMeters !== undefined && Number.isFinite(zMeters)) {
    params.set("z", String(zMeters));
  } else if (layer !== null && layer !== undefined) {
    params.set("layer", String(layer));
  }
  const response = await fetch(api(`/api/models/${modelId}/series?${params.toString()}`), {
    signal: AbortSignal.timeout(120_000),
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Series request failed: ${response.status}`);
  }
  return (await response.json()) as SeriesPayload;
}

export type ProfilePayload = {
  id: string;
  nodeIndex: number;
  lon: number;
  lat: number;
  distanceMeters: number;
  variable: string;
  label: string;
  unit: string;
  timeIndex: number;
  timeSeconds: number;
  nLayers: number;
  layers: number[];
  z: Array<number | null>;
  values: Array<number | null>;
};

export async function fetchProfile(
  modelId: string,
  lon: number,
  lat: number,
  timeIndex: number,
  variable?: string,
): Promise<ProfilePayload | null> {
  const params = new URLSearchParams({
    lon: lon.toFixed(6),
    lat: lat.toFixed(6),
    timeIndex: String(timeIndex),
  });
  if (variable) {
    params.set("variable", variable);
  }
  const response = await fetch(api(`/api/models/${modelId}/profile?${params.toString()}`));
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Profile request failed: ${response.status}`);
  }
  return (await response.json()) as ProfilePayload;
}

export type PolygonStatsPayload = {
  id: string;
  variable: string;
  label: string;
  unit: string;
  timeIndex: number;
  timeSeconds: number;
  nNodes: number;
  nFaces?: number;
  mean: number | null;
  min: number | null;
  max: number | null;
  method: string;
  nVertices: number;
  vertical?: boolean;
  layer?: number | null;
  zMeters?: number | null;
  critical?: number;
  nAbove?: number;
  nBelow?: number;
  areaKm2?: number;
  areaAboveKm2?: number;
  areaBelowKm2?: number;
  histCounts?: number[];
  histArea?: number[];
  histEdges?: number[];
  extent?: HydroExtent;
};

type PolygonBody = {
  ring: Array<[number, number]>;
  timeIndex: number;
  variable?: string;
  layer?: number;
  z?: number;
  critical?: number;
};

function polygonBody(
  ring: Array<[number, number]>,
  timeIndex: number,
  variable?: string,
  layer?: number | null,
  zMeters?: number | null,
  critical?: number,
): PolygonBody {
  return {
    ring,
    timeIndex,
    variable: variable || undefined,
    layer: layer ?? undefined,
    z: zMeters ?? undefined,
    critical,
  };
}

export async function fetchPolygonStats(
  modelId: string,
  ring: Array<[number, number]>,
  timeIndex: number,
  variable?: string,
  layer?: number | null,
  zMeters?: number | null,
  critical?: number,
): Promise<PolygonStatsPayload> {
  const response = await fetch(api(`/api/models/${modelId}/polygon-stats`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(polygonBody(ring, timeIndex, variable, layer, zMeters, critical)),
  });
  if (!response.ok) {
    let message = `Polygon stats failed: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      /* keep status text */
    }
    throw new Error(message);
  }
  return (await response.json()) as PolygonStatsPayload;
}

export async function fetchPolygonThreshold(
  modelId: string,
  ring: Array<[number, number]>,
  timeIndex: number,
  variable?: string,
  layer?: number | null,
  zMeters?: number | null,
  critical?: number,
): Promise<{ blob: Blob; extent: HydroExtent }> {
  const response = await fetch(api(`/api/models/${modelId}/polygon-threshold.png`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(polygonBody(ring, timeIndex, variable, layer, zMeters, critical)),
  });
  if (!response.ok) {
    let message = `Threshold map failed: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      /* keep status text */
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  return {
    blob,
    extent: {
      west: Number(response.headers.get("X-West")),
      south: Number(response.headers.get("X-South")),
      east: Number(response.headers.get("X-East")),
      north: Number(response.headers.get("X-North")),
    },
  };
}

export async function fetchStep(modelId: string, timeIndex: number): Promise<StepPayload> {
  const response = await fetch(api(`/api/models/${modelId}/step/${timeIndex}`));
  if (!response.ok) {
    throw new Error(`Step request failed: ${response.status}`);
  }
  return (await response.json()) as StepPayload;
}

export const DEFAULT_MODEL_ID = "sample_data";

export function pickDefaultModel(models: ModelMetadata[]): ModelMetadata | undefined {
  return models.find((model) => model.id === DEFAULT_MODEL_ID) ?? models[0];
}

export async function fetchSurface(modelId = DEFAULT_MODEL_ID): Promise<SurfacePayload> {
  const response = await fetch(api(`/api/models/${modelId}/surface`));
  if (!response.ok) {
    throw new Error(`Surface request failed: ${response.status}`);
  }
  return (await response.json()) as SurfacePayload;
}

export function decodeF32(b64: string): Float32Array {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}

export function decodeU8(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

export function decodeI32(b64: string): Int32Array {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return new Int32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
}
