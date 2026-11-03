import { env } from "@/config/env";

const api = (path: string): string => `${env.apiBaseUrl}${path}`;

export type StorageConfig = {
  dataSource: string;
  endpoint: string;
  bucket: string;
  modelPrefix: string;
  zarrPrefix: string;
  buildingsPrefix: string;
  exampleObject?: string;
  zarrUrl?: string;
  zarrOk?: boolean;
  zarrError?: string | null;
  zarrNTimes?: number | null;
  buildingsTileset?: string;
  buildingsTilesetOk?: boolean | null;
  meshPath?: string | null;
  meshError?: string | null;
};

export type StorageForm = {
  endpoint: string;
  bucket: string;
  modelPrefix: string;
  zarrPrefix: string;
  buildingsPrefix: string;
};

type Listener = () => void;

const listeners = new Set<Listener>();

export let sourceRevision = 0;

export function bumpSource(): void {
  notify();
}

export function subscribeStorage(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(): void {
  sourceRevision += 1;
  for (const listener of listeners) {
    listener();
  }
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    /* keep fallback */
  }
  return fallback;
}

export async function fetchStorage(): Promise<StorageConfig> {
  const response = await fetch(api("/api/storage"));
  if (!response.ok) {
    throw new Error(await readError(response, `Storage request failed: ${response.status}`));
  }
  return (await response.json()) as StorageConfig;
}

export async function applyStorage(update: StorageForm): Promise<StorageConfig> {
  const response = await fetch(api("/api/storage"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(await readError(response, `Storage update failed: ${response.status}`));
  }
  const next = (await response.json()) as StorageConfig;
  notify();
  return next;
}

export function formFromStorage(config: StorageConfig): StorageForm {
  return {
    endpoint: config.endpoint ?? "",
    bucket: config.bucket ?? "",
    modelPrefix: config.modelPrefix ?? "",
    zarrPrefix: config.zarrPrefix ?? "",
    buildingsPrefix: config.buildingsPrefix ?? "",
  };
}

export function previewObjectUrl(form: StorageForm, filename = "surface_mesh.npz"): string {
  const endpoint = form.endpoint.replace(/\/$/, "");
  const bucket = form.bucket.replace(/^\/+|\/+$/g, "");
  const prefix = form.modelPrefix.replace(/^\/+|\/+$/g, "");
  if (!endpoint || !bucket || !prefix) {
    return "";
  }
  return `${endpoint}/${bucket}/${prefix}/${filename}`;
}

export function previewZarrUrl(form: StorageForm): string {
  const endpoint = form.endpoint.replace(/\/$/, "");
  const bucket = form.bucket.replace(/^\/+|\/+$/g, "");
  const prefix = form.zarrPrefix.replace(/^\/+|\/+$/g, "");
  if (!endpoint || !bucket || !prefix) {
    return "";
  }
  return `${endpoint}/${bucket}/${prefix}`;
}
