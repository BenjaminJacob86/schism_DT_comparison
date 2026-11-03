"""SCHISM full-domain surface mesh + per-timestep fields from Zarr or NetCDF."""

from __future__ import annotations

import base64
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np
import xarray as xr

from app.config import settings
from app.services.colormaps import resolve_colormap
from app.services.overlay import (
    TILE_SIZE,
    cesium_geographic_tile_bbox,
    empty_png,
    render_cesium_tile,
    render_elevation_png,
)
from app.services.vertical import (
    ZCOR_NAME,
    discover_layered,
    inspect_layered_nc,
    interp_column_to_z,
    interp_sigma_to_z,
    mask_below_bottom,
    outputs_stamp,
    resolve_layer,
    stack_files,
)

DEFAULT_MODEL_ID = "sample_data"
MODEL_ORDER = (DEFAULT_MODEL_ID,)
# Different grid (476273 nodes, EPSG:25832). Keep files on disk; do not list or load.
HIDDEN_MODELS = frozenset({"sample_data2"})


def _models_root() -> Path:
    return settings.data_root / "models"


def _full_path(model_id: str) -> Path:
    from app.services.mesh_prep import ensure_surface_mesh

    return ensure_surface_mesh(model_id)


def _mesh_path(model_id: str) -> Path:
    return _full_path(model_id)


def available_model_ids() -> list[str]:
    from app.services.mesh_prep import cached_model_ids, ensure_surface_mesh

    found: set[str] = set()
    if settings.data_source not in {"s3", "zarr"}:
        root = _models_root()
        if root.exists():
            for path in root.glob("*/surface_mesh.npz"):
                if path.stat().st_size > 1024:
                    found.add(path.parent.name)
    found |= cached_model_ids()
    try:
        path = ensure_surface_mesh(DEFAULT_MODEL_ID)
        if path.exists():
            found.add(DEFAULT_MODEL_ID)
    except Exception as exc:
        print(f"surface mesh not ready: {exc}", flush=True)
    found -= HIDDEN_MODELS
    ordered = [model_id for model_id in MODEL_ORDER if model_id in found]
    extra = sorted(found - set(MODEL_ORDER))
    return ordered + extra


def _b64_f32(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype="<f4").tobytes()).decode("ascii")


def _b64_u8(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype=np.uint8).tobytes()).decode("ascii")


def _b64_i32(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype="<i4").tobytes()).decode("ascii")


@lru_cache(maxsize=8)
def _load_npz_cached(path_str: str, mtime: float) -> dict[str, np.ndarray]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. The API builds surface_mesh.npz at startup from hgrid.ll "
            "and/or Zarr into the cache if those sources are available."
        )
    with np.load(path, allow_pickle=True) as data:
        return {k: np.array(data[k]) for k in data.files}


def _load_npz(path: Path) -> dict[str, np.ndarray]:
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return _load_npz_cached(str(path), mtime)


def load_surface(model_id: str) -> dict[str, np.ndarray]:
    return _load_npz(_full_path(model_id))


def _as_str(value: object) -> str:
    if isinstance(value, np.ndarray):
        return str(value.reshape(-1)[0]) if value.size else "unknown"
    return str(value)


def _coord_source(surf: dict[str, np.ndarray]) -> str:
    return _as_str(surf["coord_source"]) if "coord_source" in surf else "unknown"


def model_metadata(model_id: str) -> dict:
    surf = load_surface(model_id)
    t = surf["time_seconds"]
    bbox = surf["bbox"]
    if "elev_min" in surf:
        elev_min = float(np.asarray(surf["elev_min"]).reshape(-1)[0])
        elev_max = float(np.asarray(surf["elev_max"]).reshape(-1)[0])
    else:
        elev = surf["elevation"] if "elevation" in surf else None
        if elev is not None:
            elev_min = float(np.nanmin(elev))
            elev_max = float(np.nanmax(elev))
        else:
            elev_min, elev_max = -2.0, 2.0
    n_times = int(surf["elevation"].shape[0]) if "elevation" in surf else int(t.size)
    if _use_zarr():
        from app.services import zarr_store

        t = zarr_store.time_seconds()
        n_times = int(t.size)
    n_nodes = int(surf["lon"].size)
    n_tris = int(surf["tris"].shape[0]) if surf["tris"].ndim == 2 else int(surf["tris"].size // 3)
    default_name = f"SCHISM {model_id}"
    names = {
        "sample_data": "SCHISM sample_data",
    }
    catalog = variable_catalog(model_id)
    var_ids = [item["id"] for item in catalog]
    water = next((item for item in catalog if item["id"] == "elevation"), catalog[0] if catalog else None)
    if water is not None and "elev_min" not in surf:
        elev_min = float(water["min"])
        elev_max = float(water["max"])
    elev_min, elev_max = _widen_elevation(elev_min, elev_max)
    return {
        "id": model_id,
        "name": names.get(model_id, default_name),
        "crs": "EPSG:4326",
        "coordSource": _coord_source(surf),
        "variables": var_ids,
        "variableMeta": catalog,
        "defaultVariable": "elevation" if "elevation" in var_ids else (var_ids[0] if var_ids else "elevation"),
        "nTimes": n_times,
        "nLayers": next((int(item["nLayers"]) for item in catalog if item.get("vertical")), None),
        "nNodes": n_nodes,
        "nTriangles": n_tris,
        "dtSeconds": float(t[1] - t[0]) if t.size > 1 else 3600.0,
        "timeStartSeconds": float(t[0]),
        "timeEndSeconds": float(t[-1]),
        "timeStart": None,
        "timeEnd": None,
        "elevationMin": elev_min,
        "elevationMax": elev_max,
        "extent": {
            "west": float(bbox[0]),
            "south": float(bbox[1]),
            "east": float(bbox[2]),
            "north": float(bbox[3]),
        },
        "subset": "full",
        "hasOverlay": True,
    }


def list_model_metadata() -> list[dict]:
    ids = available_model_ids()
    if not ids:
        raise FileNotFoundError(
            f"No surface_mesh.npz for any model. The API looks in data/models, "
            f"the S3 cache, then builds from hgrid.ll / Zarr."
        )
    return [model_metadata(model_id) for model_id in ids]


def mesh_payload(model_id: str) -> dict:
    surf = load_surface(model_id)
    meta = model_metadata(model_id)
    tris = surf["tris"]
    if tris.ndim == 2:
        tris_flat = tris.reshape(-1)
    else:
        tris_flat = tris
    return {
        **meta,
        "lon": _b64_f32(surf["lon"]),
        "lat": _b64_f32(surf["lat"]),
        "depth": _b64_f32(surf["depth"]),
        "tris": _b64_i32(tris_flat),
        "timeSeconds": surf["time_seconds"].astype(np.float64).tolist(),
    }


def _stack_index(surf: dict[str, np.ndarray], time_index: int) -> tuple[int, int]:
    counts = np.asarray(surf["stack_n_times"], dtype=int)
    acc = 0
    for stack, n in enumerate(counts):
        if time_index < acc + n:
            return stack, time_index - acc
        acc += n
    raise IndexError(f"time index {time_index} out of range")


_ds_cache: tuple[str, xr.Dataset] | None = None


def _open_nc(path: Path) -> xr.Dataset:
    global _ds_cache
    key = str(path)
    if _ds_cache is not None and _ds_cache[0] == key:
        return _ds_cache[1]
    if _ds_cache is not None:
        _ds_cache[1].close()
    ds = xr.open_dataset(path, decode_times=False)
    _ds_cache = (key, ds)
    return ds


def _source_dir(surf: dict[str, np.ndarray]) -> Path:
    if settings.data_source == "s3":
        from app.services.remote import cache_dir

        return cache_dir()
    return Path(_as_str(surf["source_dir"]))


def _n_stacks(surf: dict[str, np.ndarray]) -> int:
    if "stack_n_times" in surf:
        return int(np.asarray(surf["stack_n_times"]).size)
    return 1


def _nc_stack_file(surf: dict[str, np.ndarray], prefix: str, stack: int) -> Path:
    """Resolve one stack file. On S3 this HEADs/GETs a known key (no listing)."""
    if settings.data_source == "s3":
        from app.services.remote import ensure_file

        return ensure_file(f"{prefix}_{int(stack) + 1}.nc")
    files = stack_files(_source_dir(surf), prefix)
    return files[int(stack)]


_SKIP_NC_VARS = frozenset(
    {
        "dryFlagNode",
        "dryFlagElement",
        "dryFlagSide",
        "SCHISM_hgrid",
        "SCHISM_hgrid_face_nodes",
        "SCHISM_hgrid_edge_nodes",
        "minimum_depth",
        "bottom_index_node",
        "SCHISM_hgrid_node_x",
        "SCHISM_hgrid_node_y",
        "SCHISM_hgrid_face_x",
        "SCHISM_hgrid_face_y",
        "SCHISM_hgrid_edge_x",
        "SCHISM_hgrid_edge_y",
        "time",
    }
)
_PAIR_VARS = (
    ("bottomStress", "bottomStressX", "bottomStressY"),
    ("depthAverageVel", "depthAverageVelX", "depthAverageVelY"),
)
_LABELS = {
    "elevation": ("Water level", "m"),
    "depth": ("Bathymetry", "m"),
    "sigWaveHeight": ("Significant wave height", "m"),
    "meanWavePeriod": ("Mean wave period", "s"),
    "zeroDowncrossPeriod": ("Zero-downcross period", "s"),
    "meanWaveDirection": ("Mean wave direction", "deg"),
    "meanDirSpreading": ("Directional spreading", "deg"),
    "peakPeriod": ("Peak period", "s"),
    "dominantDirection": ("Dominant direction", "deg"),
    "peakSpreading": ("Peak spreading", "deg"),
    "bottomStress": ("Bottom stress", "Pa"),
    "depthAverageVel": ("Depth-averaged speed", "m/s"),
    "temperature": ("Temperature", "°C"),
}
_PREFERRED = (
    "elevation",
    "temperature",
    "depth",
    "sigWaveHeight",
    "peakPeriod",
    "meanWavePeriod",
    "bottomStress",
    "depthAverageVel",
    "meanWaveDirection",
    "dominantDirection",
)
DEFAULT_VARIABLE = "elevation"
_NC_LOCK = threading.RLock()


def _widen_elevation(lo: float, hi: float) -> tuple[float, float]:
    """Hour 0 can be a quiet startup; keep water-level colour range at least -2 … 2 m."""
    lo = min(float(lo), -2.0)
    hi = max(float(hi), 2.0)
    if hi <= lo:
        hi = lo + 0.02
    return lo, hi


def _zarr_default_limits(spec: dict) -> tuple[float, float]:
    """Avoid scanning every Zarr array during catalog; the colour slider can refine."""
    var_id = spec["id"]
    table = {
        "elevation": (-2.0, 2.0),
        "depth": (0.0, 50.0),
        "sigWaveHeight": (0.0, 4.0),
        "peakPeriod": (1.0, 16.0),
        "meanWavePeriod": (1.0, 12.0),
        "bottomStress": (0.0, 2.0),
        "depthAverageVel": (0.0, 1.5),
        "meanWaveDirection": (0.0, 360.0),
        "dominantDirection": (0.0, 360.0),
        "temperature": (2.0, 12.0),
    }
    if var_id in table:
        return table[var_id]
    base = str(var_id).rsplit("/", 1)[-1]
    for key, rng in sorted(table.items(), key=lambda item: len(item[0]), reverse=True):
        if base == key or base.startswith(f"{key}_") or key in base:
            return rng
    cap = float(spec.get("validAbs") or 10.0)
    unit = spec.get("unit") or ""
    if unit in {"deg"}:
        return 0.0, 360.0
    return 0.0, min(cap, 10.0)


def _use_zarr() -> bool:
    return settings.data_source in {"s3", "zarr"}


def time_seconds_for(model_id: str) -> np.ndarray:
    if _use_zarr():
        from app.services import zarr_store

        return zarr_store.time_seconds()
    return np.asarray(load_surface(model_id)["time_seconds"], dtype=np.float64)


def _is_node_dim(dim: str) -> bool:
    text = dim.lower()
    return "node" in text and "face" not in text and "edge" not in text


def _zarr_variable_index() -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    from app.services import zarr_store

    inv = zarr_store.inventory()
    names = set(inv)
    node_n = 0
    for probe in ("elevation", "depth"):
        if probe in names:
            try:
                node_n = int(zarr_store.array_shape(probe)[-1])
            except Exception:
                node_n = 0
            if node_n:
                break
    time_vars: list[str] = []
    static_vars: list[str] = []
    for name, dims in inv.items():
        if name in _SKIP_NC_VARS or name.rsplit("/", 1)[-1] in _SKIP_NC_VARS:
            continue
        if len(dims) == 2 and dims[0] == "time" and _is_node_dim(dims[1]):
            time_vars.append(name)
        elif len(dims) == 1 and name != "time" and not name.endswith("/time"):
            shape: tuple[int, ...] = ()
            try:
                shape = zarr_store.array_shape(name)
            except Exception:
                shape = ()
            if _is_node_dim(dims[0]) or (node_n > 0 and shape == (node_n,)):
                static_vars.append(name)
    pairs = [p for p in _PAIR_VARS if p[1] in names and p[2] in names]
    return tuple(time_vars), tuple(static_vars), tuple(pairs)


def _zarr_layered_raw() -> tuple[dict, ...]:
    from app.services import zarr_store

    found: list[dict] = []
    for name, dims in zarr_store.inventory().items():
        if name in {"zCoordinates", "zcor"} or name in _SKIP_NC_VARS:
            continue
        if len(dims) == 3 and dims[0] == "time":
            found.append(
                {
                    "id": name,
                    "prefix": name,
                    "nc": name,
                    "nLayers": zarr_store.n_layers(name),
                    "units": _LABELS.get(name, ("", ""))[1],
                }
            )
    return tuple(found)


def _out2d_files(surf: dict[str, np.ndarray]) -> list[Path]:
    if settings.data_source == "s3":
        return [_nc_stack_file(surf, "out2d", i) for i in range(_n_stacks(surf))]
    files = sorted(_source_dir(surf).glob("out2d_*.nc"), key=lambda p: int(p.stem.split("_")[1]))
    if not files:
        raise FileNotFoundError(f"No out2d_*.nc in {_source_dir(surf)}")
    return files


def _layered_raw(surf: dict[str, np.ndarray]) -> tuple[dict, ...]:
    if _use_zarr():
        return _zarr_layered_raw()
    if settings.data_source == "s3":
        from app.services.remote import ensure_file_if_exists

        path = ensure_file_if_exists("temperature_1.nc")
        if path is None:
            return ()
        return tuple(inspect_layered_nc(path))
    source = _source_dir(surf)
    return discover_layered(str(source), outputs_stamp(source))


def _layered_spec(item: dict) -> dict:
    var_id = item["id"]
    unit = item.get("units") or _LABELS.get(var_id, (_pretty_label(var_id), ""))[1]
    label = _LABELS.get(var_id, (_pretty_label(var_id), unit))[0]
    return {
        "id": var_id,
        "kind": "layered",
        "prefix": item["prefix"],
        "nc": item["nc"],
        "nLayers": int(item["nLayers"]),
        "timeVarying": True,
        "vertical": True,
        "label": label,
        "unit": unit or "°C" if var_id == "temperature" else unit,
        "validAbs": _valid_abs_for(var_id, unit or "°C"),
    }


@lru_cache(maxsize=8)
def _layered_specs_cached(source_str: str, stamp: float) -> dict[str, dict]:
    surf = {"source_dir": np.array(source_str)}
    del stamp
    return {item["id"]: _layered_spec(item) for item in _layered_raw(surf)}


def _layered_specs(surf: dict[str, np.ndarray]) -> dict[str, dict]:
    if _use_zarr():
        return {item["id"]: _layered_spec(item) for item in _zarr_layered_raw()}
    source = _source_dir(surf)
    return _layered_specs_cached(str(source), outputs_stamp(source))


def _slice_args(spec: dict, layer: int | None, z_meters: float | None) -> tuple[int, str]:
    if spec.get("kind") != "layered":
        return -1, ""
    if z_meters is not None and np.isfinite(z_meters):
        return -1, f"{float(z_meters):.4f}"
    return resolve_layer(int(spec["nLayers"]), layer), ""


@lru_cache(maxsize=4)
def _bottom_index_cached(path_str: str, mtime: float) -> np.ndarray | None:
    del mtime
    from netCDF4 import Dataset

    with _NC_LOCK:
        with Dataset(path_str) as nc:
            if "bottom_index_node" not in nc.variables:
                return None
            return np.asarray(nc.variables["bottom_index_node"][:], dtype=np.int32)


def _bottom_index(surf: dict[str, np.ndarray]) -> np.ndarray | None:
    if _use_zarr():
        from app.services import zarr_store

        if not zarr_store.has("bottom_index_node"):
            return None
        return np.asarray(zarr_store.read_time_node("bottom_index_node", 0), dtype=np.int32)
    path = _nc_stack_file(surf, "out2d", 0)
    return _bottom_index_cached(str(path), path.stat().st_mtime)


def _pretty_label(nc_name: str) -> str:
    name = nc_name.rsplit("/", 1)[-1]
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return re.sub(r"\s+", " ", spaced.replace("_", " ")).strip(" _").capitalize()


def _inherited_meta(var_id: str) -> tuple[str, str]:
    """Pretty label; reuse units from a related known field. Units are not required on the Zarr array."""
    name = var_id.rsplit("/", 1)[-1]
    if name in _LABELS:
        return _LABELS[name]
    unit = ""
    for key, (_label, known_unit) in sorted(_LABELS.items(), key=lambda item: len(item[0]), reverse=True):
        if name == key or name.startswith(f"{key}_") or key in name:
            unit = known_unit
            break
    return _pretty_label(name), unit


def _valid_abs_for(var_id: str, unit: str) -> float:
    if var_id == "elevation":
        return 30.0
    if var_id == "temperature":
        return 50.0
    if var_id == "depth":
        return 200.0
    if unit in {"deg"}:
        return 400.0
    if unit in {"s"}:
        return 120.0
    if "stress" in var_id.lower():
        return 1.0e4
    if "vel" in var_id.lower() or "speed" in var_id.lower():
        return 20.0
    return 80.0


@lru_cache(maxsize=8)
def _nc_variable_index(path_str: str, mtime: float) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[str, str, str], ...]]:
    """Return (time_node_vars, static_node_vars, available_pairs)."""
    del mtime
    from netCDF4 import Dataset

    with _NC_LOCK:
        with Dataset(path_str) as nc:
            time_vars: list[str] = []
            static_vars: list[str] = []
            names = set(nc.variables)
            for name, var in nc.variables.items():
                if name in _SKIP_NC_VARS:
                    continue
                dims = tuple(var.dimensions)
                if dims == ("time", "nSCHISM_hgrid_node"):
                    time_vars.append(name)
                elif dims == ("nSCHISM_hgrid_node",):
                    static_vars.append(name)
            pairs = [p for p in _PAIR_VARS if p[1] in names and p[2] in names]
    return tuple(time_vars), tuple(static_vars), tuple(pairs)


def _spec_for(var_id: str, time_vars: tuple[str, ...], static_vars: tuple[str, ...], pairs: tuple[tuple[str, str, str], ...]) -> dict:
    for pid, cx, cy in pairs:
        if var_id == pid:
            label, unit = _inherited_meta(pid)
            return {
                "id": pid,
                "kind": "pair",
                "x": cx,
                "y": cy,
                "timeVarying": True,
                "label": label,
                "unit": unit,
                "validAbs": _valid_abs_for(pid, unit),
            }
    if var_id in time_vars:
        label, unit = _inherited_meta(var_id)
        return {
            "id": var_id,
            "kind": "field",
            "nc": var_id,
            "timeVarying": True,
            "label": label,
            "unit": unit,
            "validAbs": _valid_abs_for(var_id, unit),
        }
    if var_id in static_vars:
        label, unit = _inherited_meta(var_id)
        return {
            "id": var_id,
            "kind": "field",
            "nc": var_id,
            "timeVarying": False,
            "label": label,
            "unit": unit,
            "validAbs": _valid_abs_for(var_id, unit),
        }
    raise LookupError(f"Unknown variable {var_id}")


def _catalog_ids(time_vars: tuple[str, ...], static_vars: tuple[str, ...], pairs: tuple[tuple[str, str, str], ...]) -> list[str]:
    skip_components = {c for p in pairs for c in p[1:]}
    ids = [p[0] for p in pairs]
    ids.extend(v for v in time_vars if v not in skip_components)
    ids.extend(v for v in static_vars if v not in skip_components)
    preferred = [v for v in _PREFERRED if v in ids]
    extra = sorted(v for v in ids if v not in preferred)
    if "elevation" not in preferred and "elevation" in ids:
        preferred = ["elevation", *preferred]
    return preferred + extra


def _limits_of(values: np.ndarray, valid_abs: float) -> tuple[float, float]:
    v = np.asarray(values, dtype=np.float64)
    v = v[np.isfinite(v) & (np.abs(v) < valid_abs)]
    if v.size == 0:
        return 0.0, 1.0
    lo = float(np.percentile(v, 2))
    hi = float(np.percentile(v, 98))
    if hi <= lo:
        hi = lo + 0.01
    return round(lo, 3), round(hi, 3)


def _sample_nodes(n_nodes: int, n: int = 4000) -> np.ndarray:
    if n_nodes <= n:
        return np.arange(n_nodes, dtype=np.int64)
    return np.linspace(0, n_nodes - 1, n).astype(np.int64)


def _read_sample(nc, spec: dict, gnodes: np.ndarray) -> np.ndarray:
    if spec["kind"] == "pair":
        x = np.asarray(nc.variables[spec["x"]][0, gnodes], dtype=np.float64)
        y = np.asarray(nc.variables[spec["y"]][0, gnodes], dtype=np.float64)
        return np.sqrt(x * x + y * y)
    var = nc.variables[spec["nc"]]
    if spec["timeVarying"]:
        return np.asarray(var[0, gnodes], dtype=np.float64)
    return np.asarray(var[gnodes], dtype=np.float64)


@lru_cache(maxsize=8)
def _variable_catalog(model_id: str, mtime: float) -> tuple[dict, ...]:
    del mtime
    surf = load_surface(model_id)
    if "elevation" in surf:
        elev = np.asarray(surf["elevation"], dtype=np.float32)
        lo, hi = _limits_of(elev, 30.0)
        return (
            {
                "id": "elevation",
                "label": "Water level",
                "unit": "m",
                "timeVarying": True,
                "min": lo,
                "max": hi,
                "validAbs": 30.0,
            },
        )
    if _use_zarr():
        time_vars, static_vars, pairs = _zarr_variable_index()
        ids = _catalog_ids(time_vars, static_vars, pairs)
        out: list[dict] = []
        for var_id in ids:
            spec = _spec_for(var_id, time_vars, static_vars, pairs)
            if var_id == "elevation":
                try:
                    mesh_path = _full_path(model_id)
                    field_mtime = mesh_path.stat().st_mtime if mesh_path.exists() else 0.0
                    _field_cached(model_id, 0, field_mtime, "elevation", -1, "")
                except Exception:
                    pass
                if "elev_min" in surf:
                    lo = float(np.asarray(surf["elev_min"]).reshape(-1)[0])
                    hi = float(np.asarray(surf["elev_max"]).reshape(-1)[0])
                else:
                    lo, hi = _zarr_default_limits(spec)
                lo, hi = _widen_elevation(lo, hi)
            else:
                lo, hi = _zarr_default_limits(spec)
            out.append(
                {
                    "id": spec["id"],
                    "label": spec["label"],
                    "unit": spec["unit"],
                    "timeVarying": spec["timeVarying"],
                    "vertical": False,
                    "min": lo,
                    "max": hi,
                    "validAbs": spec["validAbs"],
                    "vector": spec.get("kind") == "pair",
                }
            )
        layered_items: list[dict] = []
        for spec in _layered_specs(surf).values():
            lo, hi = _zarr_default_limits(spec)
            layered_items.append(
                {
                    "id": spec["id"],
                    "label": spec["label"],
                    "unit": spec["unit"],
                    "timeVarying": True,
                    "vertical": True,
                    "nLayers": int(spec["nLayers"]),
                    "min": lo,
                    "max": hi,
                    "validAbs": spec["validAbs"],
                }
            )
        elev_at = next((i for i, item in enumerate(out) if item["id"] == "elevation"), -1)
        out[elev_at + 1 : elev_at + 1] = layered_items
        return tuple(out)
    files0 = _nc_stack_file(surf, "out2d", 0)
    from netCDF4 import Dataset

    time_vars, static_vars, pairs = _nc_variable_index(str(files0), files0.stat().st_mtime)
    ids = _catalog_ids(time_vars, static_vars, pairs)
    gnodes = np.asarray(surf["node_global"], dtype=np.int64)[_sample_nodes(int(surf["lon"].size))]
    out: list[dict] = []
    with _NC_LOCK:
        with Dataset(str(files0)) as nc:
            for var_id in ids:
                spec = _spec_for(var_id, time_vars, static_vars, pairs)
                sample = _read_sample(nc, spec, gnodes)
                lo, hi = _limits_of(sample, spec["validAbs"])
                if var_id == "elevation" and "elev_min" in surf:
                    lo = float(np.asarray(surf["elev_min"]).reshape(-1)[0])
                    hi = float(np.asarray(surf["elev_max"]).reshape(-1)[0])
                if var_id == "elevation":
                    lo, hi = _widen_elevation(lo, hi)
                out.append(
                    {
                        "id": spec["id"],
                        "label": spec["label"],
                        "unit": spec["unit"],
                        "timeVarying": spec["timeVarying"],
                        "vertical": False,
                        "min": lo,
                        "max": hi,
                        "validAbs": spec["validAbs"],
                        "vector": spec.get("kind") == "pair",
                    }
                )
        layered_items: list[dict] = []
        for spec in _layered_specs(surf).values():
            files3 = _nc_stack_file(surf, spec["prefix"], 0)
            layer = resolve_layer(int(spec["nLayers"]), None)
            with Dataset(str(files3)) as nc:
                sample = np.asarray(nc.variables[spec["nc"]][0, gnodes, layer], dtype=np.float64)
            lo, hi = _limits_of(sample, spec["validAbs"])
            layered_items.append(
                {
                    "id": spec["id"],
                    "label": spec["label"],
                    "unit": spec["unit"],
                    "timeVarying": True,
                    "vertical": True,
                    "nLayers": int(spec["nLayers"]),
                    "min": lo,
                    "max": hi,
                    "validAbs": spec["validAbs"],
                }
            )
        elev_at = next((i for i, item in enumerate(out) if item["id"] == "elevation"), -1)
        out[elev_at + 1 : elev_at + 1] = layered_items
    return tuple(out)


def variable_catalog(model_id: str) -> list[dict]:
    path = _full_path(model_id)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    try:
        if _use_zarr():
            from app.services import zarr_store

            stamp = float(zarr_store.n_times())
        else:
            stamp = outputs_stamp(_source_dir(load_surface(model_id)))
    except Exception:
        stamp = 0.0
    return [dict(item) for item in _variable_catalog(model_id, mtime + stamp)]


def _var_meta(model_id: str, var_id: str) -> dict:
    for item in variable_catalog(model_id):
        if item["id"] == var_id:
            return item
    raise LookupError(f"Unknown variable {var_id}")


def _resolve_spec(model_id: str, variable: str | None) -> dict:
    surf = load_surface(model_id)
    var_id = variable or DEFAULT_VARIABLE
    if var_id in ("water_level", "water_depth"):
        var_id = "elevation" if var_id == "water_level" else "depth"
    if "elevation" in surf:
        if var_id not in (DEFAULT_VARIABLE, "elevation"):
            raise LookupError(f"Unknown variable {var_id}")
        return {
            "id": "elevation",
            "kind": "legacy",
            "timeVarying": True,
            "label": "Water level",
            "unit": "m",
            "validAbs": 30.0,
        }
    if _use_zarr():
        layered = _layered_specs(surf)
        if var_id in layered:
            return layered[var_id]
        time_vars, static_vars, pairs = _zarr_variable_index()
        return _spec_for(var_id, time_vars, static_vars, pairs)
    files0 = _nc_stack_file(surf, "out2d", 0)
    layered = _layered_specs(surf)
    if var_id in layered:
        return layered[var_id]
    time_vars, static_vars, pairs = _nc_variable_index(str(files0), files0.stat().st_mtime)
    return _spec_for(var_id, time_vars, static_vars, pairs)


def _read_pair_xy(surf: dict[str, np.ndarray], time_index: int, spec: dict) -> tuple[np.ndarray, np.ndarray]:
    """Eastward / northward components for a paired vector (speed is hypot of these)."""
    nodes = np.asarray(surf["node_global"], dtype=np.int64)
    if _use_zarr():
        from app.services import zarr_store

        t = zarr_store.clamp_time(time_index)
        x = np.asarray(zarr_store.read_time_node(spec["x"], t)[nodes], dtype=np.float32)
        y = np.asarray(zarr_store.read_time_node(spec["y"], t)[nodes], dtype=np.float32)
        return x, y
    stack, local = _stack_index(surf, time_index)
    path = _nc_stack_file(surf, "out2d", stack)
    from netCDF4 import Dataset

    with _NC_LOCK:
        with Dataset(str(path)) as nc:
            x = np.asarray(nc.variables[spec["x"]][local, :], dtype=np.float32)[nodes]
            y = np.asarray(nc.variables[spec["y"]][local, :], dtype=np.float32)[nodes]
    return x, y


@lru_cache(maxsize=48)
def _cached_pair_xy(
    model_id: str, time_index: int, mtime: float, variable: str
) -> tuple[np.ndarray, np.ndarray] | None:
    del mtime
    spec = _resolve_spec(model_id, variable)
    if spec.get("kind") != "pair":
        return None
    return _read_pair_xy(load_surface(model_id), time_index, spec)


def _field_dry_zarr(
    surf: dict[str, np.ndarray],
    time_index: int,
    spec: dict,
    layer: int | None,
    z_meters: float | None,
    store=None,
) -> tuple[np.ndarray, np.ndarray]:
    from app.services import zarr_store

    zs = store if store is not None else zarr_store
    t = zs.clamp_time(time_index)
    nodes = np.asarray(surf["node_global"], dtype=np.int64)
    face_for_tri = np.asarray(surf["face_for_tri"], dtype=np.int64)
    dry_e = zs.read_time_face("dryFlagElement", t)
    dry = (dry_e[face_for_tri] > 0.5).astype(np.uint8)
    if spec.get("kind") == "layered":
        k, zcode = _slice_args(spec, layer, z_meters)
        if zcode:
            if not zs.has("zCoordinates"):
                raise LookupError("Z interpolation needs zCoordinates in the Zarr store")
            cube = zs.read_layered_cube(spec["nc"], t)
            zcor = zs.read_layered_cube("zCoordinates", t)
            cube = mask_below_bottom(cube, _bottom_index(surf))
            zcor = mask_below_bottom(zcor, _bottom_index(surf))
            field = interp_sigma_to_z(cube[nodes], zcor[nodes], float(zcode))
            return np.asarray(field, dtype=np.float32), dry
        field = zs.read_layered_node(spec["nc"], t, k)[nodes]
        return field, dry
    if spec.get("kind") == "pair":
        x = np.asarray(zs.read_time_node(spec["x"], t)[nodes], dtype=np.float32)
        y = np.asarray(zs.read_time_node(spec["y"], t)[nodes], dtype=np.float32)
        return np.sqrt(x * x + y * y).astype(np.float32), dry
    name = spec.get("nc", "elevation")
    field = zs.read_time_node(name, t if spec.get("timeVarying", True) else 0)[nodes]
    return field, dry


def _hub_selection():
    from app.config import settings

    if settings.app_mode != "hub":
        return None
    from app.services import hub_state

    return hub_state.current()


def _hub_cache_token() -> str:
    sel = _hub_selection()
    if sel is None:
        return ""
    return f"{sel.a}|{sel.b}|{sel.view}"


def _hub_view_label(base: str) -> str:
    sel = _hub_selection()
    if sel is None or sel.view == "a":
        return base
    try:
        from app.services.hub_catalog import catalog

        cat = catalog()
        label_a = cat.by_id(sel.a).label
        label_b = cat.by_id(sel.b).label
    except Exception:
        label_a, label_b = sel.a, sel.b
    if sel.view == "b":
        return f"{base} · {label_b}"
    return f"{base} · {label_b} − {label_a}"


def _hub_store_for(slot: str):
    """Zarr store for hub scenario A or B, independent of the current map view."""
    sel = _hub_selection()
    if sel is None:
        return None
    from app.services import zarr_store
    from app.services.hub_catalog import catalog

    scen = catalog().by_id(sel.a if slot == "a" else sel.b)
    return zarr_store.store_for(scen.zarr_prefix, scen.endpoint, scen.bucket)


def _hub_b_store():
    """Scenario B Zarr, or None when the default store already matches the hub view."""
    from app.config import settings

    sel = _hub_selection()
    if sel is None or sel.view == "a":
        return None
    from app.services.hub_catalog import catalog

    scen_b = catalog().by_id(sel.b)
    if sel.view == "b" and settings.s3_zarr_prefix.strip("/") == scen_b.zarr_prefix.strip("/"):
        return None
    return _hub_store_for("b")


def _encode_series_values(series: np.ndarray, cap: float) -> list[float | None]:
    return [
        None if not np.isfinite(v) or abs(float(v)) >= cap else round(float(v), 4) for v in series
    ]


def _hub_compare_series(
    surf: dict[str, np.ndarray],
    node_index: int,
    spec: dict,
    layer: int | None,
    z_meters: float | None,
    series_a: np.ndarray,
    cap: float,
) -> dict | None:
    sel = _hub_selection()
    if sel is None:
        return None
    from app.services.hub_catalog import catalog

    cat = catalog()
    scen_a = cat.by_id(sel.a)
    scen_b = cat.by_id(sel.b)
    same = (
        scen_a.zarr_prefix.strip("/") == scen_b.zarr_prefix.strip("/")
        and scen_a.endpoint.rstrip("/") == scen_b.endpoint.rstrip("/")
        and scen_a.bucket.strip("/") == scen_b.bucket.strip("/")
    )
    if same:
        series_b = series_a
    else:
        store_b = _hub_store_for("b")
        if store_b is None:
            return None
        series_b = _node_field_series(surf, node_index, spec, layer, z_meters, store=store_b)
    return {
        "a": {"id": sel.a, "label": scen_a.label, "values": _encode_series_values(series_a, cap)},
        "b": {"id": sel.b, "label": scen_b.label, "values": _encode_series_values(series_b, cap)},
    }


def _apply_hub_view(
    surf: dict[str, np.ndarray],
    time_index: int,
    spec: dict,
    layer: int | None,
    z_meters: float | None,
    field: np.ndarray,
    dry: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    sel = _hub_selection()
    store_b = _hub_b_store()
    if sel is None or store_b is None:
        return field, dry
    field_b, dry_b = _field_dry_zarr(surf, time_index, spec, layer, z_meters, store=store_b)
    if sel.view == "b":
        return field_b, dry_b
    if field.shape != field_b.shape:
        raise LookupError(
            f"Cannot subtract scenarios: A has {field.size} values, B has {field_b.size}"
        )
    return (np.asarray(field_b, dtype=np.float32) - np.asarray(field, dtype=np.float32)), dry


def _field_dry(
    surf: dict[str, np.ndarray],
    time_index: int,
    spec: dict,
    layer: int | None = None,
    z_meters: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    if "elevation" in surf:
        return _step_from_legacy(surf, time_index)
    if _use_zarr():
        field, dry = _field_dry_zarr(surf, time_index, spec, layer, z_meters)
        return _apply_hub_view(surf, time_index, spec, layer, z_meters, field, dry)
    stack, local = _stack_index(surf, time_index)
    nodes = np.asarray(surf["node_global"], dtype=np.int64)
    face_for_tri = np.asarray(surf["face_for_tri"], dtype=np.int64)
    out2d = _nc_stack_file(surf, "out2d", stack)
    layered = spec.get("kind") == "layered"
    nc3_path = _nc_stack_file(surf, spec["prefix"], stack) if layered else None
    k, zcode = _slice_args(spec, layer, z_meters) if layered else (-1, "")
    zpath = _nc_stack_file(surf, ZCOR_NAME, stack) if layered and zcode else None
    from netCDF4 import Dataset

    with _NC_LOCK:
        with Dataset(str(out2d)) as nc:
            dry_e = np.asarray(nc.variables["dryFlagElement"][local, :], dtype=np.float32)
            dry = (dry_e[face_for_tri] > 0.5).astype(np.uint8)
            if layered:
                field = None
            elif spec.get("kind") == "pair":
                x = np.asarray(nc.variables[spec["x"]][local, :], dtype=np.float32)[nodes]
                y = np.asarray(nc.variables[spec["y"]][local, :], dtype=np.float32)[nodes]
                field = np.sqrt(x * x + y * y)
            elif spec.get("kind") == "legacy" or spec.get("id") == "elevation":
                field = np.asarray(nc.variables["elevation"][local, :], dtype=np.float32)[nodes]
            elif not spec.get("timeVarying", True):
                field = np.asarray(nc.variables[spec["nc"]][:], dtype=np.float32)[nodes]
            else:
                field = np.asarray(nc.variables[spec["nc"]][local, :], dtype=np.float32)[nodes]
        if layered:
            with Dataset(str(nc3_path)) as nc3:
                if zcode:
                    cube = np.asarray(nc3.variables[spec["nc"]][local, :, :], dtype=np.float32)
                else:
                    field = np.asarray(nc3.variables[spec["nc"]][local, :, k], dtype=np.float32)[nodes]
            if zcode:
                z_target = float(zcode)
                with Dataset(str(zpath)) as znc:
                    zcor = np.asarray(znc.variables[ZCOR_NAME][local, :, :], dtype=np.float32)
                cube = mask_below_bottom(cube, _bottom_index(surf))
                zcor = mask_below_bottom(zcor, _bottom_index(surf))
                field = interp_sigma_to_z(cube[nodes], zcor[nodes], z_target)
    return field, dry


@lru_cache(maxsize=48)
def _cached_field_dry(
    model_id: str,
    time_index: int,
    mtime: float,
    variable: str,
    layer: int = -1,
    zcode: str = "",
    hub: str = "",
) -> tuple[np.ndarray, np.ndarray]:
    del mtime, hub
    surf = load_surface(model_id)
    spec = _resolve_spec(model_id, variable)
    z_meters = float(zcode) if zcode else None
    k = None if z_meters is not None or layer < 0 else int(layer)
    return _field_dry(surf, time_index, spec, k, z_meters)


def _field_cached(
    model_id: str,
    time_index: int,
    mtime: float,
    variable: str,
    layer: int = -1,
    zcode: str = "",
) -> tuple[np.ndarray, np.ndarray]:
    """Serialize the first Zarr/NetCDF read so parallel Cesium tiles share one fetch."""
    with _NC_LOCK:
        return _cached_field_dry(
            model_id, time_index, mtime, variable, layer, zcode, _hub_cache_token()
        )


def _view_field(
    model_id: str,
    time_index: int,
    variable: str | None,
    layer: int | None = None,
    z_meters: float | None = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    spec = _resolve_spec(model_id, variable)
    path = _full_path(model_id)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    k, zcode = _slice_args(spec, layer, z_meters)
    field, dry = _field_cached(model_id, time_index, mtime, spec["id"], k, zcode)
    return field, dry, spec


def _step_from_netcdf(surf: dict[str, np.ndarray], time_index: int) -> tuple[np.ndarray, np.ndarray]:
    if _use_zarr():
        spec = {"id": "elevation", "kind": "field", "nc": "elevation", "timeVarying": True}
        return _field_dry_zarr(surf, time_index, spec, None, None)
    stack, local = _stack_index(surf, time_index)
    nodes = np.asarray(surf["node_global"], dtype=np.int64)
    face_for_tri = np.asarray(surf["face_for_tri"], dtype=np.int64)
    path = _nc_stack_file(surf, "out2d", stack)
    with _NC_LOCK:
        ds = _open_nc(path)
        elev = np.asarray(ds["elevation"].isel(time=local).values, dtype=np.float32)[nodes]
        dry_e = np.asarray(ds["dryFlagElement"].isel(time=local).values, dtype=np.float32)
    dry = (dry_e[face_for_tri] > 0.5).astype(np.uint8)
    return elev, dry


def _step_from_legacy(surf: dict[str, np.ndarray], time_index: int) -> tuple[np.ndarray, np.ndarray]:
    elev = np.asarray(surf["elevation"][time_index], dtype=np.float32)
    dry = np.asarray(surf["dry"][time_index], dtype=np.uint8)
    return elev, dry


def step_payload(model_id: str, time_index: int) -> dict:
    surf = load_surface(model_id)
    meta = model_metadata(model_id)
    n_times = int(meta["nTimes"])
    t = max(0, min(n_times - 1, int(time_index)))
    if "elevation" in surf:
        elev, dry = _step_from_legacy(surf, t)
    else:
        elev, dry = _step_from_netcdf(surf, t)
    return {
        "id": model_id,
        "timeIndex": t,
        "timeSeconds": float(surf["time_seconds"][t]),
        "elevation": _b64_f32(elev),
        "dry": _b64_u8(dry),
    }


MAX_PICK_METERS = 2500.0


def _nearest_node(lon: np.ndarray, lat: np.ndarray, qlon: float, qlat: float) -> tuple[int, float]:
    dlat = np.radians(lat - qlat)
    dlon = np.radians(lon - qlon)
    x = dlon * np.cos(np.radians(qlat))
    dist = 6_371_000.0 * np.sqrt(x * x + dlat * dlat)
    idx = int(np.argmin(dist))
    return idx, float(dist[idx])


def _node_field_series(
    surf: dict[str, np.ndarray],
    node_index: int,
    spec: dict,
    layer: int | None = None,
    z_meters: float | None = None,
    store=None,
) -> np.ndarray:
    n_times = int(np.asarray(surf["time_seconds"]).size)
    if "elevation" in surf:
        return np.asarray(surf["elevation"][:, node_index], dtype=np.float32)
    if _use_zarr():
        from app.services import zarr_store

        zs = store if store is not None else zarr_store
        gnode = int(np.asarray(surf["node_global"], dtype=np.int64)[node_index])
        if spec.get("kind") == "layered":
            k, zcode = _slice_args(spec, layer, z_meters)
            if zcode:
                raise LookupError("Z interpolation needs zCoordinates in the Zarr store")
            return zs.read_series_layered(spec["nc"], gnode, k)
        if spec.get("kind") == "pair":
            x = zs.read_series_node(spec["x"], gnode)
            y = zs.read_series_node(spec["y"], gnode)
            return np.sqrt(x * x + y * y).astype(np.float32)
        return zs.read_series_node(spec.get("nc", "elevation"), gnode)
    from netCDF4 import Dataset

    gnode = int(np.asarray(surf["node_global"], dtype=np.int64)[node_index])
    counts = np.asarray(surf["stack_n_times"], dtype=int)
    out = np.empty(n_times, dtype=np.float32)
    acc = 0
    if spec.get("kind") == "layered":
        k, zcode = _slice_args(spec, layer, z_meters)
        for stack, n in enumerate(counts):
            nc3_path = _nc_stack_file(surf, spec["prefix"], stack)
            zpath = _nc_stack_file(surf, ZCOR_NAME, stack) if zcode else None
            with _NC_LOCK:
                with Dataset(str(nc3_path)) as nc:
                    if zcode:
                        col = np.asarray(nc.variables[spec["nc"]][:, gnode, :], dtype=np.float32)
                    else:
                        chunk = np.asarray(nc.variables[spec["nc"]][:, gnode, k], dtype=np.float32).reshape(-1)
                if zcode:
                    with Dataset(str(zpath)) as znc:
                        zcol = np.asarray(znc.variables[ZCOR_NAME][:, gnode, :], dtype=np.float32)
                    z_target = float(zcode)
                    chunk = np.empty(col.shape[0], dtype=np.float32)
                    for i in range(col.shape[0]):
                        chunk[i] = interp_column_to_z(col[i], zcol[i], z_target)
            take = int(n)
            out[acc : acc + take] = chunk[:take]
            acc += take
        return out

    files0 = _nc_stack_file(surf, "out2d", 0)
    if not spec.get("timeVarying", True):
        with _NC_LOCK:
            with Dataset(str(files0)) as nc:
                val = float(np.asarray(nc.variables[spec["nc"]][gnode]).reshape(-1)[0])
        return np.full(n_times, val, dtype=np.float32)
    for stack, n in enumerate(counts):
        path = _nc_stack_file(surf, "out2d", stack)
        with _NC_LOCK:
            with Dataset(str(path)) as nc:
                if spec.get("kind") == "pair":
                    x = np.asarray(nc.variables[spec["x"]][:, gnode], dtype=np.float32).reshape(-1)
                    y = np.asarray(nc.variables[spec["y"]][:, gnode], dtype=np.float32).reshape(-1)
                    chunk = np.sqrt(x * x + y * y)
                else:
                    name = spec.get("nc", "elevation")
                    chunk = np.asarray(nc.variables[name][:, gnode], dtype=np.float32).reshape(-1)
        take = int(n)
        out[acc : acc + take] = chunk[:take]
        acc += take
    return out


def _apply_hub_series(
    surf: dict[str, np.ndarray],
    node_index: int,
    spec: dict,
    layer: int | None,
    z_meters: float | None,
    series: np.ndarray,
) -> np.ndarray:
    sel = _hub_selection()
    store_b = _hub_b_store()
    if sel is None or store_b is None:
        return series
    series_b = _node_field_series(surf, node_index, spec, layer, z_meters, store=store_b)
    if sel.view == "b":
        return series_b
    if series.shape != series_b.shape:
        raise LookupError(
            f"Cannot subtract series: A has {series.size} steps, B has {series_b.size}"
        )
    return np.asarray(series_b, dtype=np.float32) - np.asarray(series, dtype=np.float32)


def _apply_hub_column(spec: dict, time_index: int, gnode: int, vals: np.ndarray) -> np.ndarray:
    sel = _hub_selection()
    store_b = _hub_b_store()
    if sel is None or store_b is None:
        return vals
    vals_b = np.asarray(store_b.read_column(spec["nc"], time_index, gnode), dtype=np.float64)
    if sel.view == "b":
        return vals_b
    va = np.asarray(vals, dtype=np.float64).reshape(-1)
    vb = vals_b.reshape(-1)
    n = min(va.size, vb.size)
    return vb[:n] - va[:n]


def series_payload(
    model_id: str,
    lon: float,
    lat: float,
    variable: str | None = None,
    layer: int | None = None,
    z_meters: float | None = None,
) -> dict:
    """Time series at the nearest mesh node. Raises LookupError if the click is on land."""
    surf = load_surface(model_id)
    spec = _resolve_spec(model_id, variable)
    limits = _var_meta(model_id, spec["id"])
    slon = np.asarray(surf["lon"], dtype=np.float64)
    slat = np.asarray(surf["lat"], dtype=np.float64)
    idx, dist = _nearest_node(slon, slat, float(lon), float(lat))
    if dist > MAX_PICK_METERS:
        raise LookupError("No mesh node near click")
    series_a = _node_field_series(surf, idx, spec, layer, z_meters)
    series = _apply_hub_series(surf, idx, spec, layer, z_meters, series_a)
    times = time_seconds_for(model_id)
    cap = float(spec["validAbs"])
    values = _encode_series_values(series, cap)
    k, zcode = _slice_args(spec, layer, z_meters)
    compare = _hub_compare_series(surf, idx, spec, layer, z_meters, series_a, cap)
    sel = _hub_selection()
    view = None if sel is None else sel.view
    return {
        "id": model_id,
        "nodeIndex": idx,
        "lon": float(slon[idx]),
        "lat": float(slat[idx]),
        "distanceMeters": round(dist, 1),
        "variable": spec["id"],
        "label": _hub_view_label(spec["label"]) if view == "diff" else spec["label"],
        "unit": spec["unit"],
        "timeVarying": spec["timeVarying"],
        "vertical": spec.get("kind") == "layered",
        "nLayers": spec.get("nLayers"),
        "layer": None if zcode else (k if spec.get("kind") == "layered" else None),
        "zMeters": float(zcode) if zcode else None,
        "timeSeconds": times.astype(float).tolist(),
        "values": values,
        "elevation": values,
        "compare": None if view == "diff" else compare,
        "view": view,
        "min": limits["min"],
        "max": limits["max"],
        "elevationMin": limits["min"],
        "elevationMax": limits["max"],
    }


def profile_payload(
    model_id: str,
    lon: float,
    lat: float,
    time_index: int = 0,
    variable: str | None = None,
) -> dict:
    """Vertical profile at the nearest node (SCHISM zCoordinates vs field)."""
    surf = load_surface(model_id)
    spec = _resolve_spec(model_id, variable)
    if spec.get("kind") != "layered":
        raise LookupError(f"{spec['id']} has no vertical layers")
    slon = np.asarray(surf["lon"], dtype=np.float64)
    slat = np.asarray(surf["lat"], dtype=np.float64)
    idx, dist = _nearest_node(slon, slat, float(lon), float(lat))
    if dist > MAX_PICK_METERS:
        raise LookupError("No mesh node near click")
    meta = model_metadata(model_id)
    n_times = int(meta["nTimes"])
    t = max(0, min(n_times - 1, int(time_index)))
    gnode = int(np.asarray(surf["node_global"], dtype=np.int64)[idx])
    from netCDF4 import Dataset

    if _use_zarr():
        from app.services import zarr_store

        vals = _apply_hub_column(spec, t, gnode, zarr_store.read_column(spec["nc"], t, gnode))
        if zarr_store.has("zCoordinates"):
            z = zarr_store.read_column("zCoordinates", t, gnode)
        else:
            z = np.arange(vals.size, dtype=np.float64)
        b = _bottom_index(surf)
        bnode = int(b[gnode]) if b is not None and gnode < b.size else 1
        cap = float(spec["validAbs"])
        z_out: list[float | None] = []
        v_out: list[float | None] = []
        layers: list[int] = []
        for k, (zk, vk) in enumerate(zip(z, vals)):
            if k < bnode - 1:
                continue
            z_ok = bool(np.isfinite(zk))
            v_ok = bool(np.isfinite(vk) and abs(float(vk)) < cap)
            z_out.append(round(float(zk), 4) if z_ok else None)
            v_out.append(round(float(vk), 4) if v_ok else None)
            layers.append(k)
        return {
            "id": model_id,
            "nodeIndex": idx,
            "lon": float(slon[idx]),
            "lat": float(slat[idx]),
            "distanceMeters": round(dist, 1),
            "variable": spec["id"],
            "label": _hub_view_label(spec["label"]),
            "unit": spec["unit"],
            "timeIndex": t,
            "timeSeconds": float(zarr_store.time_seconds()[t]),
            "nLayers": int(spec["nLayers"]),
            "layers": layers,
            "z": z_out,
            "values": v_out,
            "zIsLayerIndex": not zarr_store.has("zCoordinates"),
        }
    stack, local = _stack_index(surf, t)

    files3 = _nc_stack_file(surf, spec["prefix"], stack)
    zfile = _nc_stack_file(surf, ZCOR_NAME, stack)
    with _NC_LOCK:
        with Dataset(str(files3)) as nc:
            vals = np.asarray(nc.variables[spec["nc"]][local, gnode, :], dtype=np.float64)
        with Dataset(str(zfile)) as znc:
            z = np.asarray(znc.variables[ZCOR_NAME][local, gnode, :], dtype=np.float64)
    b = _bottom_index(surf)
    bnode = int(b[gnode]) if b is not None and gnode < b.size else 1
    cap = float(spec["validAbs"])
    z_out: list[float | None] = []
    v_out: list[float | None] = []
    layers: list[int] = []
    for k, (zk, vk) in enumerate(zip(z, vals)):
        if k < bnode - 1:
            continue
        z_ok = bool(np.isfinite(zk))
        v_ok = bool(np.isfinite(vk) and abs(float(vk)) < cap)
        z_out.append(round(float(zk), 4) if z_ok else None)
        v_out.append(round(float(vk), 4) if v_ok else None)
        layers.append(k)
    return {
        "id": model_id,
        "nodeIndex": idx,
        "lon": float(slon[idx]),
        "lat": float(slat[idx]),
        "distanceMeters": round(dist, 1),
        "variable": spec["id"],
        "label": _hub_view_label(spec["label"]),
        "unit": spec["unit"],
        "timeIndex": t,
        "timeSeconds": float(np.asarray(surf["time_seconds"])[t]),
        "nLayers": int(spec["nLayers"]),
        "layers": layers,
        "z": z_out,
        "values": v_out,
    }


MAX_POLYGON_VERTICES = 200


def _as_tri_index(tris: np.ndarray) -> np.ndarray:
    t = np.asarray(tris)
    if t.ndim == 1:
        t = t.reshape(-1, 3)
    return np.ascontiguousarray(t, dtype=np.int64)


def _wet_node_mask(n_nodes: int, tris: np.ndarray, dry: np.ndarray) -> np.ndarray:
    faces = _as_tri_index(tris)
    n_tri = int(faces.shape[0])
    wet = np.ones(n_tri, dtype=bool)
    flag = np.asarray(dry).reshape(-1)
    if flag.size >= n_tri:
        wet = flag[:n_tri] < 0.5
    mask = np.zeros(n_nodes, dtype=bool)
    if n_tri and wet.any():
        mask[faces[wet].reshape(-1)] = True
    return mask


def _points_in_ring(lon: np.ndarray, lat: np.ndarray, ring: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon. `ring` is (N, 2) lon/lat, not necessarily closed."""
    pts = np.asarray(ring, dtype=np.float64)
    if pts.shape[0] >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    inside = np.zeros(lon.shape, dtype=bool)
    nvert = int(pts.shape[0])
    if nvert < 3:
        return inside
    j = nvert - 1
    for i in range(nvert):
        xi, yi = float(pts[i, 0]), float(pts[i, 1])
        xj, yj = float(pts[j, 0]), float(pts[j, 1])
        dy = yj - yi
        frac = ((lat - yi) / dy) if abs(dy) > 1e-18 else 0.0
        hit = ((yi > lat) != (yj > lat)) & (lon < (xj - xi) * frac + xi)
        inside ^= hit
        j = i
    return inside


def _ring_area_km2(ring: np.ndarray) -> float:
    """Approximate geodesic area of a lon/lat ring (km²)."""
    if ring.shape[0] < 3:
        return 0.0
    lon = np.deg2rad(np.asarray(ring[:, 0], dtype=np.float64))
    lat = np.deg2rad(np.asarray(ring[:, 1], dtype=np.float64))
    lat0 = float(np.mean(lat))
    x = lon * np.cos(lat0) * 6371.0088
    y = lat * 6371.0088
    x = np.append(x, x[0])
    y = np.append(y, y[0])
    return float(abs(0.5 * np.dot(x[:-1], y[1:]) - 0.5 * np.dot(x[1:], y[:-1])))


N_HIST_BINS = 32


def _parse_ring(ring: list[list[float]]) -> np.ndarray:
    if len(ring) < 3:
        raise ValueError("Polygon needs at least 3 vertices")
    if len(ring) > MAX_POLYGON_VERTICES:
        raise ValueError(f"Polygon is limited to {MAX_POLYGON_VERTICES} vertices")
    try:
        ring_arr = np.asarray([[float(pt[0]), float(pt[1])] for pt in ring], dtype=np.float64)
    except (TypeError, ValueError, IndexError) as exc:
        raise ValueError("Each vertex must be [lon, lat]") from exc
    if not np.isfinite(ring_arr).all():
        raise ValueError("Polygon vertices must be finite lon/lat")
    return ring_arr


def _resolve_critical(critical: float | None) -> float:
    if critical is not None and np.isfinite(critical):
        return float(critical)
    from app.services import hub_state

    sel = hub_state.current()
    return float(sel.critical) if sel is not None else 0.0


def _triangle_areas_km2(lon: np.ndarray, lat: np.ndarray, faces: np.ndarray) -> np.ndarray:
    i0, i1, i2 = faces[:, 0], faces[:, 1], faces[:, 2]
    lat_c = (lat[i0] + lat[i1] + lat[i2]) / 3.0
    m_lon = 111.32 * np.cos(np.deg2rad(lat_c))
    m_lat = 111.32
    x0, y0 = lon[i0] * m_lon, lat[i0] * m_lat
    x1, y1 = lon[i1] * m_lon, lat[i1] * m_lat
    x2, y2 = lon[i2] * m_lon, lat[i2] * m_lat
    return np.abs(0.5 * ((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)))


def _polygon_selection(
    model_id: str,
    ring: list[list[float]],
    time_index: int,
    variable: str | None,
    layer: int | None,
    z_meters: float | None,
    critical: float | None,
) -> dict:
    ring_arr = _parse_ring(ring)
    meta = model_metadata(model_id)
    n_times = int(meta["nTimes"])
    t = max(0, min(n_times - 1, int(time_index)))
    field, dry, spec = _view_field(model_id, t, variable, layer, z_meters)
    k, zcode = _slice_args(spec, layer, z_meters)
    surf = load_surface(model_id)
    lon = np.asarray(surf["lon"], dtype=np.float64)
    lat = np.asarray(surf["lat"], dtype=np.float64)
    faces = _as_tri_index(surf["tris"])
    vals = np.asarray(field, dtype=np.float64)
    cap = float(spec["validAbs"])
    crit = _resolve_critical(critical)

    wet_nodes = _wet_node_mask(int(lon.size), faces, dry)
    west, east = float(ring_arr[:, 0].min()), float(ring_arr[:, 0].max())
    south, north = float(ring_arr[:, 1].min()), float(ring_arr[:, 1].max())
    pad_x = max((east - west) * 0.03, 1e-5)
    pad_y = max((north - south) * 0.03, 1e-5)
    node_cand = wet_nodes & (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    node_inside = np.zeros(lon.size, dtype=bool)
    if node_cand.any():
        node_inside[node_cand] = _points_in_ring(lon[node_cand], lat[node_cand], ring_arr)
    node_ok = node_inside & np.isfinite(vals) & (np.abs(vals) < cap)

    n_tri = int(faces.shape[0])
    wet_tri = np.ones(n_tri, dtype=bool)
    flag = np.asarray(dry).reshape(-1)
    if flag.size >= n_tri:
        wet_tri = flag[:n_tri] < 0.5
    i0, i1, i2 = faces[:, 0], faces[:, 1], faces[:, 2]
    face_mean = (vals[i0] + vals[i1] + vals[i2]) / 3.0
    cx = (lon[i0] + lon[i1] + lon[i2]) / 3.0
    cy = (lat[i0] + lat[i1] + lat[i2]) / 3.0
    face_cand = (
        wet_tri
        & np.isfinite(face_mean)
        & (np.abs(face_mean) < cap)
        & (cx >= west)
        & (cx <= east)
        & (cy >= south)
        & (cy <= north)
    )
    face_inside = np.zeros(n_tri, dtype=bool)
    if face_cand.any():
        face_inside[face_cand] = _points_in_ring(cx[face_cand], cy[face_cand], ring_arr)

    return {
        "model_id": model_id,
        "spec": spec,
        "surf": surf,
        "t": t,
        "k": k,
        "zcode": zcode,
        "ring": ring_arr,
        "lon": lon,
        "lat": lat,
        "faces": faces,
        "vals": vals,
        "crit": crit,
        "node_ok": node_ok,
        "face_inside": face_inside,
        "face_mean": face_mean,
        "west": west - pad_x,
        "south": south - pad_y,
        "east": east + pad_x,
        "north": north + pad_y,
    }


def polygon_stats(
    model_id: str,
    ring: list[list[float]],
    time_index: int,
    variable: str | None = None,
    layer: int | None = None,
    z_meters: float | None = None,
    critical: float | None = None,
) -> dict:
    """Wet-node mean plus triangle exceedance stats inside the polygon."""
    sel = _polygon_selection(model_id, ring, time_index, variable, layer, z_meters, critical)
    spec = sel["spec"]
    surf = sel["surf"]
    t = int(sel["t"])
    k, zcode = sel["k"], sel["zcode"]
    crit = float(sel["crit"])
    node_ok = sel["node_ok"]
    vals = sel["vals"]
    n = int(node_ok.sum())
    if n == 0:
        mean = min_v = max_v = None
    else:
        picked = vals[node_ok]
        mean = round(float(picked.mean()), 4)
        min_v = round(float(picked.min()), 4)
        max_v = round(float(picked.max()), 4)

    face_inside = sel["face_inside"]
    face_mean = sel["face_mean"]
    faces = sel["faces"]
    n_faces = int(face_inside.sum())
    hist_counts = [0] * N_HIST_BINS
    hist_area = [0.0] * N_HIST_BINS
    hist_edges = [0.0] * (N_HIST_BINS + 1)
    area_km2 = area_above = area_below = 0.0
    n_above = n_below = 0
    if n_faces:
        tri_vals = face_mean[face_inside]
        areas = _triangle_areas_km2(sel["lon"], sel["lat"], faces[face_inside])
        ok_area = areas > 0
        tri_vals = tri_vals[ok_area]
        areas = areas[ok_area]
        if tri_vals.size:
            area_km2 = float(areas.sum())
            above = tri_vals > crit
            area_above = float(areas[above].sum())
            area_below = area_km2 - area_above
            n_above = int(np.count_nonzero(above))
            n_below = int(tri_vals.size - n_above)
            counts, edges = np.histogram(tri_vals, bins=N_HIST_BINS)
            hist_a, _ = np.histogram(tri_vals, bins=edges, weights=areas)
            hist_counts = [int(v) for v in counts]
            hist_area = [round(float(v), 6) for v in hist_a]
            hist_edges = [round(float(v), 6) for v in edges]
    if area_km2 <= 0:
        area_km2 = _ring_area_km2(sel["ring"])

    return {
        "id": model_id,
        "variable": spec["id"],
        "label": _hub_view_label(spec["label"]),
        "unit": spec["unit"],
        "timeIndex": t,
        "timeSeconds": float(np.asarray(surf["time_seconds"])[t]),
        "nNodes": n,
        "nFaces": n_faces,
        "mean": mean,
        "min": min_v,
        "max": max_v,
        "method": "wet_node_mean",
        "nVertices": int(sel["ring"].shape[0]),
        "vertical": spec.get("kind") == "layered",
        "layer": None if zcode else (k if spec.get("kind") == "layered" else None),
        "zMeters": float(zcode) if zcode else None,
        "critical": crit,
        "nAbove": n_above,
        "nBelow": n_below,
        "areaKm2": round(float(area_km2), 4),
        "areaAboveKm2": round(float(area_above), 4),
        "areaBelowKm2": round(float(area_below), 4),
        "histCounts": hist_counts,
        "histArea": hist_area,
        "histEdges": hist_edges,
        "extent": {
            "west": float(sel["west"]),
            "south": float(sel["south"]),
            "east": float(sel["east"]),
            "north": float(sel["north"]),
        },
    }


def polygon_threshold_png(
    model_id: str,
    ring: list[list[float]],
    time_index: int,
    variable: str | None = None,
    layer: int | None = None,
    z_meters: float | None = None,
    critical: float | None = None,
) -> tuple[bytes, tuple[float, float, float, float]]:
    from app.services.overlay import empty_png, render_threshold_png

    sel = _polygon_selection(model_id, ring, time_index, variable, layer, z_meters, critical)
    west, south, east, north = sel["west"], sel["south"], sel["east"], sel["north"]
    keep = sel["face_inside"]
    if not bool(keep.any()):
        return empty_png(64, 64), (west, south, east, north)
    png = render_threshold_png(
        sel["lon"],
        sel["lat"],
        sel["faces"],
        sel["face_mean"],
        keep,
        west,
        south,
        east,
        north,
        float(sel["crit"]),
    )
    return png, (west, south, east, north)


def surface_payload(model_id: str) -> dict:
    """Back-compat: mesh plus timestep 0 (not the full time cube)."""
    mesh = mesh_payload(model_id)
    step = step_payload(model_id, 0)
    return {**mesh, "elevation": step["elevation"], "dry": step["dry"]}


def _elev_dry(surf: dict[str, np.ndarray], time_index: int) -> tuple[np.ndarray, np.ndarray]:
    if "elevation" in surf:
        return _step_from_legacy(surf, time_index)
    return _step_from_netcdf(surf, time_index)


def _color_range(
    fallback_min: float, fallback_max: float, vmin: float | None, vmax: float | None
) -> tuple[float, float]:
    lo = float(fallback_min) if vmin is None else float(vmin)
    hi = float(fallback_max) if vmax is None else float(vmax)
    lo = round(lo, 3)
    hi = round(hi, 3)
    if hi <= lo:
        hi = round(lo + 0.01, 3)
    return lo, hi


@lru_cache(maxsize=36)
def overlay_png(
    model_id: str,
    time_index: int,
    mtime: float,
    variable: str,
    vmin: float,
    vmax: float,
    valid_abs: float,
    colormap: str,
    layer: int,
    zcode: str,
    hub: str = "",
) -> tuple[bytes, tuple[float, float, float, float]]:
    del hub
    surf = load_surface(model_id)
    field, dry = _field_cached(model_id, time_index, mtime, variable, layer, zcode)
    bbox = surf["bbox"]
    extent = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    png = render_elevation_png(
        surf["lon"],
        surf["lat"],
        surf["tris"],
        field,
        dry,
        vmin,
        vmax,
        *extent,
        valid_abs=valid_abs,
        colormap=colormap,
    )
    return png, extent


def overlay_png_for(
    model_id: str,
    time_index: int,
    vmin: float | None = None,
    vmax: float | None = None,
    variable: str | None = None,
    colormap: str | None = None,
    layer: int | None = None,
    z_meters: float | None = None,
) -> tuple[bytes, tuple[float, float, float, float]]:
    path = _full_path(model_id)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    spec = _resolve_spec(model_id, variable)
    limits = _var_meta(model_id, spec["id"])
    meta = model_metadata(model_id)
    n_times = int(meta["nTimes"])
    t = max(0, min(n_times - 1, int(time_index)))
    lo, hi = _color_range(limits["min"], limits["max"], vmin, vmax)
    cmap = resolve_colormap(colormap)
    k, zcode = _slice_args(spec, layer, z_meters)
    return overlay_png(
        model_id, t, mtime, spec["id"], lo, hi, float(spec["validAbs"]), cmap, k, zcode, _hub_cache_token()
    )


def _hub_diff_limits(
    lo: float, hi: float, vmin: float | None, vmax: float | None
) -> tuple[float, float]:
    from app.config import settings
    from app.services import hub_state

    if settings.app_mode != "hub" or vmin is not None or vmax is not None:
        return lo, hi
    sel = hub_state.current()
    if sel is None or sel.view != "diff":
        return lo, hi
    span = max(abs(lo), abs(hi), 0.25)
    return -span, span


@lru_cache(maxsize=2048)
def overlay_tile(
    model_id: str,
    time_index: int,
    level: int,
    x: int,
    y: int,
    mtime: float,
    variable: str,
    vmin: float,
    vmax: float,
    valid_abs: float,
    colormap: str,
    layer: int,
    zcode: str,
    hub: str = "",
) -> tuple[bytes, tuple[float, float, float, float]]:
    del hub
    west, south, east, north = cesium_geographic_tile_bbox(level, x, y)
    extent = (west, south, east, north)
    surf = load_surface(model_id)
    bbox = np.asarray(surf["bbox"], dtype=np.float64)
    if east < bbox[0] or west > bbox[2] or north < bbox[1] or south > bbox[3]:
        return empty_png(TILE_SIZE, TILE_SIZE), extent
    field, dry = _field_cached(model_id, time_index, mtime, variable, layer, zcode)
    png = render_cesium_tile(
        surf["lon"],
        surf["lat"],
        surf["tris"],
        field,
        dry,
        vmin,
        vmax,
        west,
        south,
        east,
        north,
        valid_abs=valid_abs,
        colormap=colormap,
    )
    return png, extent


def overlay_tile_for(
    model_id: str,
    time_index: int,
    level: int,
    x: int,
    y: int,
    vmin: float | None = None,
    vmax: float | None = None,
    variable: str | None = None,
    colormap: str | None = None,
    layer: int | None = None,
    z_meters: float | None = None,
) -> tuple[bytes, tuple[float, float, float, float]]:
    path = _full_path(model_id)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    spec = _resolve_spec(model_id, variable)
    limits = _var_meta(model_id, spec["id"])
    meta = model_metadata(model_id)
    n_times = int(meta["nTimes"])
    t = max(0, min(n_times - 1, int(time_index)))
    z = max(0, min(19, int(level)))
    lo, hi = _color_range(limits["min"], limits["max"], vmin, vmax)
    lo, hi = _hub_diff_limits(lo, hi, vmin, vmax)
    cmap = resolve_colormap(colormap)
    k, zcode = _slice_args(spec, layer, z_meters)
    return overlay_tile(
        model_id,
        t,
        z,
        int(x),
        int(y),
        mtime,
        spec["id"],
        lo,
        hi,
        float(spec["validAbs"]),
        cmap,
        k,
        zcode,
        _hub_cache_token(),
    )


def reset_field_caches() -> None:
    global _ds_cache
    if _ds_cache is not None:
        try:
            _ds_cache[1].close()
        except Exception:
            pass
        _ds_cache = None
    _load_npz_cached.cache_clear()
    _layered_specs_cached.cache_clear()
    _bottom_index_cached.cache_clear()
    _nc_variable_index.cache_clear()
    _variable_catalog.cache_clear()
    _cached_pair_xy.cache_clear()
    _cached_field_dry.cache_clear()
    overlay_png.cache_clear()
    overlay_tile.cache_clear()
