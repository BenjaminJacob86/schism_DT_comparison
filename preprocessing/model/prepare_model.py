"""Build surface_mesh.npz for the Cesium viewer (full SCHISM domain, no clip).

One preprocessing step. Topology comes from ``hgrid.ll`` and/or the Zarr/NetCDF
grid; time axis and elevation min/max come from Zarr or ``out2d_*.nc``.
Upload the NPZ next to the Zarr on S3. The browser never receives this file.

Examples::

    python preprocessing/model/prepare_model.py --hgrid hgrid.ll --zarr schism.zarr --id my_run
    python preprocessing/model/prepare_model.py --hgrid hgrid.ll --zarr https://minio.example/bucket/schism.zarr --id my_run
    python preprocessing/model/prepare_model.py --dir path/to/outputs --run-dir path/to/run --id my_run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import xarray as xr
import zarr

from coords import load_hgrid, resolve_lonlat

SAMPLE_DATA = Path(r"C:\Users\jacobb\Desktop\agent_dev_studio\schismview-refactor\sample_data")

_FACE_NAMES = (
    "SCHISM_hgrid_face_nodes",
    "face_nodes",
    "element",
)
_X_NAMES = ("SCHISM_hgrid_node_x", "node_x", "lon", "longitude")
_Y_NAMES = ("SCHISM_hgrid_node_y", "node_y", "lat", "latitude")
_DEPTH_NAMES = ("depth", "bathymetry")
_TIME_NAMES = ("time",)
_ELEV_NAMES = ("elevation", "elev", "zeta")


def triangulate_faces(faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Same split as schismview.grid.mesh.triangulate_faces (0-based, -1 pad)."""
    faces = np.asarray(faces, dtype=float)
    nfaces = faces.shape[0]
    fourth = faces[:, 3]
    is_quad = np.isfinite(fourth) & (fourth >= 0)
    counts = np.where(is_quad, 2, 1).astype(np.int64)
    offsets = np.cumsum(counts) - counts
    ntri = int(counts.sum())
    tris = np.empty((ntri, 3), dtype=np.int64)
    origins = np.empty(ntri, dtype=np.int64)
    idx = np.arange(nfaces, dtype=np.int64)
    tri_mask = ~is_quad
    if tri_mask.any():
        o = offsets[tri_mask]
        tris[o] = faces[tri_mask][:, :3]
        origins[o] = idx[tri_mask]
    if is_quad.any():
        o = offsets[is_quad]
        q = faces[is_quad]
        tris[o] = q[:, [0, 1, 2]]
        tris[o + 1] = q[:, [0, 2, 3]]
        origins[o] = idx[is_quad]
        origins[o + 1] = idx[is_quad]
    return tris, origins


def to_zero_based(faces: np.ndarray) -> np.ndarray:
    raw = np.asarray(faces, dtype=float)
    if raw.ndim != 2:
        raise ValueError(f"face array must be 2-D, got {raw.shape}")
    if raw.shape[1] == 3:
        padded = np.full((raw.shape[0], 4), np.nan, dtype=np.float64)
        padded[:, :3] = raw
        raw = padded
    elif raw.shape[1] < 3:
        raise ValueError(f"face array needs 3 or 4 columns, got {raw.shape}")
    out = np.empty((raw.shape[0], 4), dtype=np.int64)
    out[:, :3] = np.where(raw[:, :3] > 0, raw[:, :3] - 1, -1)
    fourth = raw[:, 3]
    out[:, 3] = np.where(np.isfinite(fourth) & (fourth > 0), fourth - 1, -1)
    return out


def normalize_faces(raw: np.ndarray) -> np.ndarray:
    """Accept 1-based SCHISM faces or already 0-based arrays."""
    arr = np.asarray(raw, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"face array must be 2-D, got {arr.shape}")
    valid = arr[:, :3][np.isfinite(arr[:, :3])]
    if valid.size and float(np.nanmin(valid)) >= 1.0:
        return to_zero_based(arr)
    out = np.full((arr.shape[0], 4), -1, dtype=np.int64)
    cols = min(4, arr.shape[1])
    finite = np.isfinite(arr[:, :cols]) & (arr[:, :cols] >= 0)
    out[:, :cols][finite] = arr[:, :cols][finite].astype(np.int64)
    return out


def _elev_limits(sample: np.ndarray) -> tuple[float, float]:
    finite = sample[np.isfinite(sample) & (np.abs(sample) < 20.0)]
    if finite.size:
        elev_min = float(np.percentile(finite, 1))
        elev_max = float(np.percentile(finite, 99))
    else:
        elev_min, elev_max = -4.0, 4.0
    pad = max(0.5, 0.1 * (elev_max - elev_min))
    elev_min -= pad
    elev_max += pad
    return min(elev_min, -2.0), max(elev_max, 2.0)


def assemble(
    lon: np.ndarray,
    lat: np.ndarray,
    depth: np.ndarray,
    faces: np.ndarray,
    time_seconds: np.ndarray,
    stack_n: np.ndarray,
    elev_min: float,
    elev_max: float,
    coord_source: str,
    source: str,
) -> dict[str, np.ndarray]:
    n0, n1, n2 = faces[:, 0], faces[:, 1], faces[:, 2]
    valid = (n0 >= 0) & (n1 >= 0) & (n2 >= 0)
    used = np.unique(faces[valid][:, :3].ravel())
    used = used[used >= 0]
    if used.size == 0:
        raise ValueError("No valid triangular faces in the grid")
    bbox_arr = np.array(
        [
            float(np.nanmin(lon[used])),
            float(np.nanmin(lat[used])),
            float(np.nanmax(lon[used])),
            float(np.nanmax(lat[used])),
        ],
        dtype=np.float64,
    )
    remap = np.full(lon.size, -1, dtype=np.int64)
    remap[used] = np.arange(used.size, dtype=np.int64)
    raw_faces = faces[valid]
    local_faces = np.full(raw_faces.shape, -1, dtype=np.int64)
    valid_nodes = raw_faces >= 0
    local_faces[valid_nodes] = remap[raw_faces[valid_nodes]]
    tris, origins = triangulate_faces(local_faces)
    glob_faces = np.flatnonzero(valid)
    face_for_tri = glob_faces[origins].astype(np.int32)
    print(
        f"nodes={used.size} faces={int(valid.sum())} tris={len(tris)} "
        f"(from {lon.size} / {len(faces)}) coords={coord_source} "
        f"bbox=({bbox_arr[0]:.3f},{bbox_arr[1]:.3f},{bbox_arr[2]:.3f},{bbox_arr[3]:.3f})",
        flush=True,
    )
    return {
        "lon": lon[used].astype(np.float32),
        "lat": lat[used].astype(np.float32),
        "depth": np.asarray(depth, dtype=np.float32)[used],
        "tris": tris.astype(np.int32),
        "node_global": used.astype(np.int32),
        "face_for_tri": face_for_tri,
        "time_seconds": np.asarray(time_seconds, dtype=np.float64),
        "stack_n_times": np.asarray(stack_n, dtype=np.int32),
        "bbox": bbox_arr,
        "coord_source": np.array(coord_source),
        "elev_min": np.array(elev_min, dtype=np.float64),
        "elev_max": np.array(elev_max, dtype=np.float64),
        "source_dir": np.array(source),
    }


def _first_named(mapping, names: tuple[str, ...]):
    for name in names:
        if name in mapping:
            return name, mapping[name]
    return None, None


def _open_zarr(path_or_url: str):
    text = str(path_or_url).rstrip("/")
    if text.startswith("http://") or text.startswith("https://"):
        store = zarr.storage.FsspecStore.from_url(text, read_only=True)
        return zarr.open_group(store, mode="r")
    return zarr.open_group(text, mode="r")


def _zarr_array(root, names: tuple[str, ...]):
    name, arr = _first_named(root, names)
    if arr is None:
        return None, None
    return name, arr


def topology_from_hgrid(hgrid: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    lon, lat, depth, faces = load_hgrid(hgrid)
    print(f"mesh from {hgrid} ({lon.size} nodes, {faces.shape[0]} faces)", flush=True)
    return lon, lat, depth, faces, "hgrid.ll"


def topology_from_zarr(
    root,
    source: str,
    hgrid: Path | None,
    crs: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    x_name, x_arr = _zarr_array(root, _X_NAMES)
    y_name, y_arr = _zarr_array(root, _Y_NAMES)
    f_name, f_arr = _zarr_array(root, _FACE_NAMES)
    if x_arr is None or y_arr is None or f_arr is None:
        missing = []
        if x_arr is None:
            missing.append("node x")
        if y_arr is None:
            missing.append("node y")
        if f_arr is None:
            missing.append("face_nodes")
        raise FileNotFoundError(
            f"Zarr {source} has no mesh topology ({', '.join(missing)}). "
            "Pass --hgrid hgrid.ll."
        )
    x = np.asarray(x_arr[:], dtype=np.float64)
    y = np.asarray(y_arr[:], dtype=np.float64)
    faces = normalize_faces(np.asarray(f_arr[:]))
    _, d_arr = _zarr_array(root, _DEPTH_NAMES)
    depth = np.asarray(d_arr[:], dtype=np.float32) if d_arr is not None else np.zeros(x.size, dtype=np.float32)
    lon, lat, coord_source = resolve_lonlat(x, y, Path("."), hgrid=hgrid, crs=crs)
    print(f"mesh from Zarr {x_name}/{y_name}/{f_name}", flush=True)
    return lon, lat, depth, faces, coord_source


def topology_from_netcdf(
    combined: Path,
    run_dir: Path | None,
    hgrid: Path | None,
    crs: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]:
    files = sorted(combined.glob("out2d_*.nc"), key=lambda p: int(p.stem.split("_")[1]))
    if not files:
        raise FileNotFoundError(f"No out2d_*.nc in {combined}")
    print(f"mesh from {files[0].name}", flush=True)
    ds0 = xr.open_dataset(files[0], decode_times=False)
    x = np.asarray(ds0["SCHISM_hgrid_node_x"].values, dtype=np.float64)
    y = np.asarray(ds0["SCHISM_hgrid_node_y"].values, dtype=np.float64)
    depth = np.asarray(ds0["depth"].values, dtype=np.float32)
    faces = to_zero_based(np.asarray(ds0["SCHISM_hgrid_face_nodes"].values))
    lon, lat, coord_source = resolve_lonlat(x, y, combined, run_dir, hgrid=hgrid, crs=crs)
    ds0.close()
    return lon, lat, depth, faces, coord_source


def times_from_zarr(root) -> tuple[np.ndarray, np.ndarray, float, float]:
    t_name, t_arr = _zarr_array(root, _TIME_NAMES)
    e_name, e_arr = _zarr_array(root, _ELEV_NAMES)
    if t_arr is not None:
        time_seconds = np.asarray(t_arr[:], dtype=np.float64)
    elif e_arr is not None and e_arr.ndim >= 1:
        n = int(e_arr.shape[0])
        time_seconds = np.arange(1, n + 1, dtype=np.float64) * 3600.0
    else:
        time_seconds = np.array([3600.0], dtype=np.float64)
    elev_min, elev_max = -4.0, 4.0
    if e_arr is not None:
        print(f"elevation range from Zarr {e_name}[0]", flush=True)
        sample = np.asarray(e_arr[0, :] if e_arr.ndim >= 2 else e_arr[:], dtype=np.float32)
        elev_min, elev_max = _elev_limits(sample)
    stack_n = np.array([int(time_seconds.size)], dtype=np.int32)
    return time_seconds, stack_n, elev_min, elev_max


def times_from_netcdf(combined: Path) -> tuple[np.ndarray, np.ndarray, float, float]:
    files = sorted(combined.glob("out2d_*.nc"), key=lambda p: int(p.stem.split("_")[1]))
    if not files:
        raise FileNotFoundError(f"No out2d_*.nc in {combined}")
    time_parts: list[np.ndarray] = []
    stack_n: list[int] = []
    prev_end = -1.0
    elev_min, elev_max = -4.0, 4.0
    for i, path in enumerate(files, start=1):
        print(f"  [{i}/{len(files)}] {path.name} (time axis)", flush=True)
        ds = xr.open_dataset(path, decode_times=False)
        t = np.asarray(ds["time"].values, dtype=np.float64)
        if prev_end >= 0 and t[0] <= prev_end + 1e-6:
            t = t + prev_end
        prev_end = float(t[-1])
        if i == 1 and "elevation" in ds:
            elev = np.asarray(ds["elevation"].values, dtype=np.float32)
            elev_min, elev_max = _elev_limits(elev[0] if elev.ndim == 2 else elev)
        time_parts.append(t)
        stack_n.append(int(t.size))
        ds.close()
    return np.concatenate(time_parts, axis=0), np.array(stack_n, dtype=np.int32), elev_min, elev_max


def extract(
    combined: Path | None,
    run_dir: Path | None,
    hgrid: Path | None,
    zarr_path: str | None,
    crs: str,
) -> dict[str, np.ndarray]:
    root = None
    source = ""
    if zarr_path:
        print(f"Opening Zarr {zarr_path}", flush=True)
        root = _open_zarr(zarr_path)
        source = str(zarr_path)
    if hgrid is not None:
        lon, lat, depth, faces, coord_source = topology_from_hgrid(hgrid)
        if root is not None:
            e_name, e_arr = _zarr_array(root, _ELEV_NAMES)
            if e_arr is not None:
                n_field = int(e_arr.shape[1] if e_arr.ndim >= 2 else e_arr.shape[0])
                if n_field != lon.size:
                    raise ValueError(
                        f"hgrid.ll has {lon.size} nodes but Zarr {e_name} has {n_field}"
                    )
        source = source or str(Path(hgrid).resolve())
    elif root is not None:
        lon, lat, depth, faces, coord_source = topology_from_zarr(root, source, hgrid, crs)
    elif combined is not None:
        lon, lat, depth, faces, coord_source = topology_from_netcdf(combined, run_dir, hgrid, crs)
        source = str(combined.resolve())
    else:
        raise FileNotFoundError("Need --hgrid, --zarr, or --dir")

    if root is not None:
        time_seconds, stack_n, elev_min, elev_max = times_from_zarr(root)
    elif combined is not None:
        time_seconds, stack_n, elev_min, elev_max = times_from_netcdf(combined)
        source = str(combined.resolve())
    else:
        time_seconds = np.array([3600.0], dtype=np.float64)
        stack_n = np.array([1], dtype=np.int32)
        elev_min, elev_max = -4.0, 4.0

    return assemble(
        lon,
        lat,
        depth,
        faces,
        time_seconds,
        stack_n,
        elev_min,
        elev_max,
        coord_source,
        source,
    )


def _write(arrays: dict[str, np.ndarray], output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.stem + "_partial.npz")
    np.savez_compressed(tmp, **arrays)
    tmp.replace(output)
    bbox = arrays["bbox"].tolist()
    meta = {
        "file": str(output),
        "source_dir": str(arrays["source_dir"]),
        "n_nodes": int(arrays["lon"].size),
        "n_tris": int(arrays["tris"].shape[0]),
        "n_times": int(arrays["time_seconds"].size),
        "stack_n_times": arrays["stack_n_times"].tolist(),
        "elev_min": float(arrays["elev_min"]),
        "elev_max": float(arrays["elev_max"]),
        "bbox": bbox,
        "coord_source": str(arrays["coord_source"]),
        "subset": "full",
    }
    output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)
    return meta


def _model_id(args: argparse.Namespace) -> str:
    if args.id:
        return args.id
    if args.dir is not None:
        name = args.dir.name
        return args.dir.parent.name if name.lower() == "outputs" else name
    if args.hgrid is not None:
        return args.hgrid.parent.name
    return "model"


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=None, help="Directory with out2d_*.nc")
    parser.add_argument("--run-dir", type=Path, default=None, help="Directory with hgrid.ll")
    parser.add_argument("--hgrid", type=Path, default=None, help="SCHISM hgrid.ll (lon/lat + faces)")
    parser.add_argument("--zarr", type=str, default=None, help="Local Zarr path or HTTP URL")
    parser.add_argument("--id", type=str, default=None, help="Model id (output folder under data/models)")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--crs",
        type=str,
        default="EPSG:25832",
        help="Projected CRS if node x/y are metres and no hgrid.ll is found",
    )
    args = parser.parse_args()

    combined = args.dir
    run_dir = args.run_dir
    hgrid = args.hgrid
    zarr_path = args.zarr
    if combined is None and hgrid is None and zarr_path is None:
        if (SAMPLE_DATA / "outputs").is_dir() and (SAMPLE_DATA / "hgrid.ll").is_file():
            combined = SAMPLE_DATA / "outputs"
            run_dir = SAMPLE_DATA
            hgrid = SAMPLE_DATA / "hgrid.ll"
            args.id = args.id or "sample_data"
        else:
            parser.error("Provide --hgrid and/or --zarr, or --dir with out2d_*.nc")

    model_id = _model_id(args)
    output = args.output or root / "data" / "models" / model_id / "surface_mesh.npz"
    print(f"\n=== {model_id} -> {output} ===", flush=True)
    arrays = extract(combined, run_dir, hgrid, zarr_path, args.crs)
    _write(arrays, output)


if __name__ == "__main__":
    main()
