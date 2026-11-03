# Model preprocessing

One step: write the **full-domain** SCHISM topology to `surface_mesh.npz`.
Time-varying fields stay in Zarr (or `out2d_*.nc`). There is no Hamburg clip mesh.

```powershell
conda activate schismview
cd preprocessing/model

# Typical cloud domain: hgrid.ll + Zarr (local path or HTTP URL)
python prepare_model.py --hgrid path\to\hgrid.ll --zarr https://minio.dive.edito.eu/project-foccus/DigitalTwinTest/zarr/schism.zarr --id sample_data

# Local SCHISM run
python prepare_model.py --dir path\to\outputs --run-dir path\to\run --id my_run

# Topology only (hgrid.ll). Overlay needs Zarr or NetCDF at runtime.
python prepare_model.py --hgrid path\to\hgrid.ll --id my_run
```

Output: `data/models/<id>/surface_mesh.npz` (lon/lat, triangles, bbox, time axis, elev min/max).
The API also runs this automatically at startup when that file is missing: it downloads it from S3 if present, otherwise builds it from `hgrid.ll` and/or Zarr into `data/cache/s3/model/<id>/surface_mesh.npz` and reuses the cache on later starts.

Upload that file to `DigitalTwinTest/model/surface_mesh.npz` (or `.../model/<id>/surface_mesh.npz`) so a machine without `hgrid.ll` can skip the build.

If node x/y in Zarr/NetCDF are projected metres and there is no `hgrid.ll`, pass `--crs EPSG:25832` (or the domain CRS).

Inspect a local run (does not load every stack):

```powershell
python inspect_model.py --dir path\to\outputs --run-dir path\to\run
```
