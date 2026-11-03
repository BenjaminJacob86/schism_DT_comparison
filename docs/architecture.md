# Architecture

React is the UI. Cesium owns the globe. Python owns scientific I/O. The browser never receives raw CityGML or a full NetCDF/Zarr file.

```text
                    WEB BROWSER
                         |
                React + TypeScript
                         |
                     CesiumJS
                         |
        +----------------+----------------+
        |                |                |
     Terrain         3D Buildings      Scientific
                    3D Tiles           overlays
                         |
              local files now / S3 later
                         |
              Python scientific backend (Phase 7)
                         |
                    xarray / Zarr / NetCDF
```

## Frontend modules

| Folder | Responsibility |
|--------|----------------|
| `cesium/` | Viewer lifecycle. One `Viewer` for the session. |
| `layers/` | Terrain, buildings, scientific overlays behind `VisualizationLayer`. |
| `controls/` | Camera, layer toggles, future time/model UI. |
| `api/` | HTTP client. Empty until Phase 7. |
| `model/` | Types for hydro metadata. No I/O. |

Camera / time / layer changes must **update layers**, not remount Cesium.

## Data sources (replaceable)

- **Buildings:** Hamburg CityGML → 3D Tiles. Areas 1–5 are source partitions; Cesium LOD/SSE decides what to fetch.
- **Terrain:** abstracted as `TerrainSource`. Phase 1 uses the WGS84 ellipsoid.
- **Hydrodynamics:** SCHISM unstructured mesh from `schismview-refactor/sample_data2` (EPSG:25832, German Bight/Elbe). NetCDF now, Zarr later.

## Scientific reference (schismview)

schismview is the 2D scientific prototype. This app does not embed it. Variable names and mesh semantics should stay compatible:

| schismview | This viewer (later phases) |
|------------|----------------------------|
| `elevation` | Water-level surface |
| wet/dry (`dryFlagElement`) | Mask dry elements |
| `horizontalVel` / `hvel` | Velocity arrows / particles |
| `zCoordinates` | Vertical structure |
| time index + layer `k` | Time slider + optional layer |
| `hgrid.ll` lon/lat | Geographic placement on the globe |

The mesh is **unstructured** (triangles/quads on nodes). Do not assume a regular lon/lat raster.

## Storage

`VITE_ASSET_BASE_URL` and `VITE_API_BASE_URL` keep local paths and future S3 interchangeable. Generated 3D Tiles are immutable and cacheable.
