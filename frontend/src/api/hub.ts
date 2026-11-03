import { env } from "@/config/env";
import { bumpSource } from "@/api/storage";

const api = (path: string): string => `${env.apiBaseUrl}${path}`;

export type HubScenario = {
  id: string;
  label: string;
  endpoint: string;
  bucket: string;
  modelPrefix: string;
  zarrPrefix: string;
  buildingsPrefix: string;
};

export type HubSelection = {
  a: string;
  b: string;
  view: "a" | "b" | "diff" | string;
  critical: number;
  compareOk: boolean;
  compareError: string | null;
  nodesA: number;
  nodesB: number;
  sharedMesh?: boolean;
};

export type HubPayload = {
  mode: string;
  catalog: {
    title: string;
    tagline: string;
    defaultA: string;
    defaultB: string;
    criticalDefault: number;
    scenarios: HubScenario[];
  };
  selection: HubSelection;
};

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

export async function fetchHub(): Promise<HubPayload> {
  const response = await fetch(api("/api/hub/scenarios"));
  if (!response.ok) {
    throw new Error(await readError(response, `Hub catalog failed: ${response.status}`));
  }
  return (await response.json()) as HubPayload;
}

export async function applyHubSelection(update: {
  a: string;
  b: string;
  view: string;
  critical?: number;
}): Promise<HubPayload> {
  const response = await fetch(api("/api/hub/selection"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    throw new Error(await readError(response, `Hub selection failed: ${response.status}`));
  }
  const next = (await response.json()) as HubPayload;
  bumpSource();
  return next;
}
