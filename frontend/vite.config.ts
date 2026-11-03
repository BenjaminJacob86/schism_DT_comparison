import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, normalize, resolve, sep } from "node:path";
import { fileURLToPath, URL } from "node:url";

const cesiumSource = "node_modules/cesium/Build/Cesium";
const cesiumBaseUrl = "cesiumStatic";
const dataRoot = fileURLToPath(new URL("../data", import.meta.url));

const mime: Record<string, string> = {
  ".json": "application/json",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".glb": "model/gltf-binary",
  ".b3dm": "application/octet-stream",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".wasm": "application/wasm",
  ".ktx2": "image/ktx2",
};

function serveLocalData(): Plugin {
  return {
    name: "serve-local-data",
    configureServer(server) {
      server.middlewares.use("/data", (req, res, next) => {
        const rel = decodeURIComponent((req.url ?? "/").split("?")[0]).replace(/^\/+/, "");
        const file = resolve(dataRoot, rel);
        const root = resolve(dataRoot) + sep;
        if (normalize(file) !== resolve(dataRoot) && !normalize(file).startsWith(root)) {
          next();
          return;
        }
        if (!existsSync(file) || !statSync(file).isFile()) {
          next();
          return;
        }
        res.setHeader("Content-Type", mime[extname(file).toLowerCase()] ?? "application/octet-stream");
        res.setHeader("Cache-Control", "no-cache");
        createReadStream(file).pipe(res);
      });
    },
  };
}

/** Serve Cesium Workers/Assets in dev. vite-plugin-static-copy can no-op if any target fails. */
function serveCesiumStatic(): Plugin {
  const cesiumRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), cesiumSource) + sep;
  const prefix = `/${cesiumBaseUrl}/`;
  return {
    name: "serve-cesium-static",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url ?? "";
        if (!url.startsWith(prefix)) {
          next();
          return;
        }
        const rel = decodeURIComponent(url.slice(prefix.length).split("?")[0]).replace(/^\/+/, "");
        const file = resolve(cesiumRoot, rel);
        if (!normalize(file).startsWith(cesiumRoot)) {
          next();
          return;
        }
        if (!existsSync(file) || !statSync(file).isFile()) {
          next();
          return;
        }
        res.setHeader("Content-Type", mime[extname(file).toLowerCase()] ?? "application/octet-stream");
        res.setHeader("Cache-Control", "no-cache");
        createReadStream(file).pipe(res);
      });
    },
  };
}

const copyTargets = [
  { src: `${cesiumSource}/ThirdParty`, dest: cesiumBaseUrl },
  { src: `${cesiumSource}/Workers`, dest: cesiumBaseUrl },
  { src: `${cesiumSource}/Assets`, dest: cesiumBaseUrl },
  { src: `${cesiumSource}/Widgets`, dest: cesiumBaseUrl },
];

export default defineConfig({
  define: {
    CESIUM_BASE_URL: JSON.stringify(`/${cesiumBaseUrl}/`),
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  plugins: [react(), serveLocalData(), serveCesiumStatic(), viteStaticCopy({ targets: copyTargets })],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    fs: {
      allow: [".."],
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 5000,
  },
});
