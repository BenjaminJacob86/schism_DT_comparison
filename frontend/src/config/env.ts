export const env = {
  cesiumIonToken: import.meta.env.VITE_CESIUM_ION_TOKEN?.trim() ?? "",
  assetBaseUrl: (import.meta.env.VITE_ASSET_BASE_URL ?? "/data").replace(/\/$/, ""),
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, ""),
  buildingsTilesetUrl: (import.meta.env.VITE_BUILDINGS_TILESET_URL ?? "").replace(/\/$/, ""),
  appMode: (import.meta.env.VITE_APP_MODE ?? "hub").trim().toLowerCase() === "viewer" ? "viewer" : "hub",
} as const;
