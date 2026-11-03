# Commercial use: CesiumJS vs Cesium ion

This project uses the **open-source CesiumJS library**, not Cesium ion cloud services.

CesiumJS is free for both commercial and research use. A paid Cesium ion account is only required if you use ion’s cloud services, tiling pipelines, or curated datasets (for example Cesium World Terrain) for funded or production work. See Cesium’s [Content Usage and Attribution Guide](https://cesium.com/learn/ion/ion-attribution/).

## What this app uses

| Component | Source | Cesium ion? |
| --- | --- | --- |
| Globe engine | CesiumJS (`cesium` npm package) | No |
| Terrain | WGS84 ellipsoid (`EllipsoidTerrainProvider`) | No |
| Satellite basemap | Esri World Imagery (URL tiles) | No |
| Hamburg buildings | Our 3D Tiles on public MinIO | No |
| SCHISM water overlay | FastAPI PNG tiles from Zarr | No |

`VITE_CESIUM_ION_TOKEN` is optional and unused. The viewer and scenario hub run with that token empty. `Ion.defaultAccessToken` is set only if someone later fills the env var.

## What would require a paid ion account

You would need ion (and its commercial terms) only if you later switched to ion-hosted assets or pipelines, for example:

- Cesium World Terrain or other ion terrain
- Cesium OSM Buildings or other ion 3D Tiles
- ion tiling / 3D Tiles generation in the cloud
- other ion curated datasets

This repo does none of that.

## Esri imagery (separate from Cesium)

The basemap is Esri World Imagery, not a Cesium ion dataset. Esri has its own terms. The app already shows their required credit: “Tiles © Esri — Esri, Maxar, Earthstar Geographics, and the GIS User Community.” Keep that attribution.
