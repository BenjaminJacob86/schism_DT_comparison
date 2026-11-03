import { useEffect, useState } from "react";

import { env } from "@/config/env";

export type AppMode = "hub" | "viewer";

const asMode = (value: string | undefined): AppMode =>
  String(value ?? "").trim().toLowerCase() === "hub" ? "hub" : "viewer";

/** Hub chrome only when the running API is APP_MODE=hub, not because the Vite process was last started as hub. */
export function useAppMode(): AppMode {
  const [mode, setMode] = useState<AppMode>(env.appMode);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(`${env.apiBaseUrl}/api/health`);
        if (!response.ok || cancelled) {
          return;
        }
        const body = (await response.json()) as { appMode?: string };
        setMode(asMode(body.appMode));
      } catch {
        /* keep the Vite bake-in until the API answers */
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return mode;
}
