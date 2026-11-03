"""Inspect a local SCHISM new-I/O directory and write model metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr

from coords import resolve_lonlat


def inspect(combined: Path, run_dir: Path | None = None) -> dict:
    out2d = sorted(combined.glob("out2d_*.nc"), key=lambda p: int(p.stem.split("_")[1]))
    if not out2d:
        raise FileNotFoundError(f"No out2d_*.nc in {combined}")

    ds = xr.open_dataset(out2d[0], decode_times=False)
    x = np.asarray(ds["SCHISM_hgrid_node_x"].values, dtype=float)
    y = np.asarray(ds["SCHISM_hgrid_node_y"].values, dtype=float)
    lon, lat, coord_source = resolve_lonlat(x, y, combined, run_dir)

    time = np.asarray(ds["time"].values, dtype=float)
    elev = ds["elevation"].isel(time=0).values
    prefixes = sorted({p.name.rsplit("_", 1)[0] for p in combined.glob("*_*.nc")})
    model_id = combined.name if combined.name != "outputs" else combined.parent.name

    meta = {
        "id": model_id,
        "name": f"SCHISM {model_id}",
        "path": str(combined),
        "run_dir": str(run_dir) if run_dir else None,
        "format": "schism-new-io",
        "coord_source": coord_source,
        "n_nodes": int(x.size),
        "n_faces": int(ds.sizes["nSCHISM_hgrid_face"]),
        "n_stacks": len(out2d),
        "steps_per_stack": int(time.size),
        "n_times_total": int(time.size * len(out2d)),
        "dt_seconds": float(time[1] - time[0]) if time.size > 1 else None,
        "time_in_file_seconds": [float(time[0]), float(time[-1])],
        "variables": [name for name in (
            "elevation",
            "depth",
            "dryFlagElement",
            "dryFlagNode",
            "depthAverageVelX",
            "depthAverageVelY",
            "horizontalVelX",
            "horizontalVelY",
            "zCoordinates",
            "sigWaveHeight",
        ) if name in ds or any(p.name.startswith(f"{name}_") for p in combined.glob("*.nc"))],
        "extent": {
            "west": float(np.min(lon)),
            "south": float(np.min(lat)),
            "east": float(np.max(lon)),
            "north": float(np.max(lat)),
        },
        "elevation_t0": {
            "min": float(np.nanmin(elev)),
            "max": float(np.nanmax(elev)),
        },
        "file_prefixes": prefixes,
        "notes": (
            "Lon/lat from hgrid.ll when node counts match (schismview). "
            "Runtime plotting uses the full-domain surface_mesh.npz plus Zarr/NetCDF fields; "
            "do not send the mesh JSON to the browser."
        ),
    }
    ds.close()
    return meta


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    meta = inspect(args.dir, args.run_dir)
    out = args.output or root / "data" / "models" / meta["id"] / "metadata.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
