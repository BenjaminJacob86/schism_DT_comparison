/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CESIUM_ION_TOKEN?: string;
  readonly VITE_ASSET_BASE_URL?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_BUILDINGS_TILESET_URL?: string;
  readonly VITE_APP_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  CESIUM_BASE_URL?: string;
}
