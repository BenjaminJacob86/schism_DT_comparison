# Backend

Python scientific API. React never opens NetCDF or Zarr; this service rasterizes
the full-domain SCHISM mesh (`surface_mesh.npz`) as PNG overlay tiles.

Build the mesh once:

```powershell
python preprocessing/model/prepare_model.py --hgrid hgrid.ll --zarr schism.zarr --id sample_data
```

```powershell
# from backend/, using the schismview conda env
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

| Route | Purpose |
| --- | --- |
| `GET /health` | liveness |
| `GET /api/models` | model list / metadata |
| `GET /api/models/{id}/tiles/{t}/{z}/{x}/{y}.png` | draped hydro overlay |
| `GET /api/models/{id}/series` | nearest-node time series |
