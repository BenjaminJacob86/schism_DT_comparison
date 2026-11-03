# SCHISM scenario comparison

Cesium hub for **comparing two SCHISM runs** on the same mesh: pick named MinIO scenarios, view A, view B, or live **B − A**. Overlay tiles, time series, and Analyse charts (donut, histogram, threshold map) follow the selected view.

This is the comparison tool. The single-run viewer lives in a separate repo: [schism_DT_cesium_viewer](https://github.com/BenjaminJacob86/schism_DT_cesium_viewer).

**GitHub About:**  
`Compare named SCHISM coastal scenarios on a Cesium globe: A, B, or live B minus A from public Zarr — FastAPI keeps the mesh off the client.`

Suggested topics: `cesium` `schism` `scenario-comparison` `hydrodynamics` `zarr` `fastapi` `react` `digital-twin` `edito`

## What it does

- Same CesiumJS globe as the viewer (Esri imagery, no Cesium ion).
- Catalog of named runs in `config/scenarios.json` (endpoint, bucket, mesh prefix, Zarr prefix).
- A / B / difference buttons. Difference is node-wise B minus A on the shared mesh.
- Time series: A (blue) and B (orange) together; difference view shows B − A only.
- Analyse polygon: donut, histogram, and exceedance map use the active view (including difference).
- Difference view switches the colormap to Balance (red–blue) and a symmetric color range.

Python owns NetCDF/Zarr. React only renders. The full ~515k-node mesh never goes to the browser.

## Named scenarios

Edit `config/scenarios.json`. Each entry is a public MinIO path. Object keys are case-sensitive (`RCP85_Veg_CNTRL` ≠ `RCP85_VEG_CNTRL`).

Default A/B and the critical threshold for Analyse are in that file.

## Quick start (local)

From this folder, `start.bat` (or `start-hub.bat`) starts FastAPI on **8000** and Vite on **5173**.

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Stop the viewer first if it is using the same ports.

## Docker

Single container: built UI + FastAPI on port **8080**, `APP_MODE=hub`. Kubernetes / EDITO Visual Port should use **8080**.

```powershell
cd docker
build.bat
docker run --rm -p 8080:8080 schism-scenario-hub:latest
```

Then open [http://localhost:8080](http://localhost:8080). The same `Dockerfile` sits at the repo root for platforms that expect it there.

The image does not run Vite; it serves the production UI from FastAPI.

## Configuration

| Variable | Default | Role |
| --- | --- | --- |
| `APP_MODE` | `hub` | Comparison hub (do not set to `viewer` in this repo) |
| `VITE_APP_MODE` | `hub` | Baked into the UI at Docker build / local Vite |
| `SCENARIOS_FILE` | `config/scenarios.json` | Named A/B catalog |
| `DATA_SOURCE` | `s3` | Public MinIO |
| `S3_ENDPOINT` | `https://minio.dive.edito.eu` | HEAD/GET only, no listing |
| `S3_BUCKET` | `project-foccus` | Bucket |
| `PORT` | `8080` | Container listen port |

Scenario A’s storage is applied when A changes. Overlay B and B − A read B’s Zarr against the shared mesh.

## Repository layout

```text
config/           Named scenario catalog (scenarios.json)
frontend/         React + TypeScript + Vite + CesiumJS
backend/          FastAPI: overlay tiles, A/B/diff, series, polygon stats
preprocessing/    hgrid/Zarr → surface_mesh.npz
docker/           EDITO-style image (APP_MODE=hub)
data/             Local cache only (gitignored)
```

## Documentation

- [Architecture](docs/architecture.md)
- [Data formats](docs/data-format.md)
- [Development](docs/development.md)
