# Data

Large datasets stay **out of Git**. This folder is the local stand-in for object storage (S3 / R2 later).

## Intended layout

```text
data/
    buildings/hamburg/area1/     # 3D Tiles (generated, Phase 4)
    terrain/                     # quantized-mesh / Cesium terrain (Phase 2)
    models/                      # NetCDF / Zarr subsets (Phase 7+)
    raw/                         # CityGML and other source files
```

## Current local sources

| Dataset | Location | Notes |
|---------|----------|--------|
| Hamburg CityGML LoD3 Area 1 | `../lod3-hh_area1_2023_12_14_180710_snap_1/` | CRS **EPSG:25832**. Textured LoD3. Do not send GML to the browser. |
| SCHISM hydrodynamics | `C:\Users\jacobb\Desktop\agent_dev_studio\schismview-refactor\sample_data2` | New I/O, EPSG:25832, German Bight + Elbe. Subset by bbox/time. |

Runtime assets should be addressed with `VITE_ASSET_BASE_URL` (local now, S3 later). Do not hard-code bucket URLs in Cesium layers.
