# Data formats

## Buildings (source)

Hamburg official CityGML 2.0, LoD3, with `rgbTexture` appearances.

Inspected in Area 1 (`lod3-hh_area1_2023_12_14_180710_snap_1`):

- CRS: **EPSG:25832** (ETRS89 / UTM zone 32N), `srsDimension="3"`
- Coordinates: easting, northing, ellipsoidal/NN height in metres
- Building IDs: `gml:id` plus `citygrid_UnitID`
- Useful attributes: `Grundfläche 2D`, `Grundhöhe NN`

CityGML is **preprocessing input only**. Runtime format is 3D Tiles (`tileset.json` + batched tiles). Preserve building IDs through conversion so picking can later join to model results.

## Buildings (runtime)

```text
data/buildings/hamburg/area1/tileset.json
```

Areas 1–5 stay as separate root tilesets. Do not map zoom levels to areas.

## Hydrodynamics

Local reference run: `C:\Users\jacobb\Desktop\agent_dev_studio\schismview-refactor\sample_data2`

SCHISM **new I/O**, 15 hourly-day stacks:

| Files | Role |
|-------|------|
| `out2d_1.nc` … `_15.nc` | Mesh, `elevation`, `depth`, wet/dry, depth-averaged velocity |
| `zCoordinates_*.nc` | 21 vertical layers |
| `horizontalVelX_*.nc` / `horizontalVelY_*.nc` | 3-D horizontal velocity |

Inspected in `out2d_1.nc`:

- CRS: node `x/y` are **EPSG:25832** metres (not lon/lat). No `hgrid.ll` in this folder.
- Mesh: **476,273** nodes, **941,084** triangles, 24 steps/file (3600–86400 s)
- Domain: lon **5.12–10.40**, lat **53.04–55.63** (German Bight / Elbe)
- Hamburg Area 1 overlap: **704 nodes** (~0.15%). Greater Hamburg ~3,670 nodes.
- `elevation` t0 over Hamburg: about **-0.26 … 0.07 m** (water level, not bathymetry)
- `depth` is bathymetry (negative/positive depending on SCHISM convention)

The browser must never receive this whole dataset. Runtime plotting uses
`surface_mesh.npz` (full-domain topology) plus Zarr/NetCDF fields; the API
rasterizes PNG tiles and never sends the mesh JSON to Cesium.

Variable mapping:

| NetCDF | Twin viewer |
|--------|-------------|
| `elevation` | Water-level surface |
| `dryFlagElement` / `dryFlagNode` | Wet/dry mask |
| `depthAverageVelX/Y` | First velocity overlay |
| `horizontalVelX/Y` + layer `k` | 3-D velocity |
| `zCoordinates[..., k=-1]` | Surface z for the 3-D water mesh |
